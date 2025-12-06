from flask import (
    render_template, request, redirect,
    url_for, session, flash, make_response
)

from app import app
from app.models import (
    get_user_by_name,
    create_user,
    get_user_groups,
    create_group,
    get_group_detail,
    add_expense,
    get_balances_for_group,
    compute_optimal_transactions,
    supabase,
    add_payment,
)
from datetime import datetime

import urllib.parse
from io import BytesIO

# PDF libraries
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm

@app.context_processor
def inject_profile_status():
    profile_incomplete = False

    if session.get("user_id"):
        user_id = session["user_id"]
        res = supabase.table("users").select("phone_number, payment_method").eq("user_id", user_id).execute()
        if res.data:
            u = res.data[0]
            phone_ok = bool(u.get("phone_number"))
            iban_ok = bool(u.get("payment_method"))
            profile_incomplete = not (phone_ok and iban_ok)

    return dict(profile_incomplete=profile_incomplete)

# ============================================================
# 1. LOGIN REQUIRED DECORATOR
# ============================================================

def login_required(route_function):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Je moet eerst inloggen.", "error")
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)

    wrapper.__name__ = route_function.__name__
    return wrapper


# ============================================================
# 2. LOGIN / LOGOUT
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        if not username:
            flash("Vul een gebruikersnaam in.", "error")
            return redirect(url_for("login"))

        existing = get_user_by_name(username)
        user = existing[0] if existing else create_user(username)

        session["user_id"] = user["user_id"]
        session["username"] = user["name"]
        return redirect(url_for("groups_list"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.", "success")
    return redirect(url_for("login"))


# ============================================================
# 3. GROUP LIST & CREATE
# ============================================================
@app.route("/groups/<int:group_id>/rename", methods=["POST"])
@login_required
def group_rename(group_id):
    new_name = request.form.get("new_name", "").strip()

    if not new_name:
        flash("Naam mag niet leeg zijn.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    # Naam updaten
    supabase.table("groups").update({"name": new_name}).eq("group_id", group_id).execute()

    # GEEN enkele melding
    return redirect(url_for("group_detail", group_id=group_id))



@app.route("/groups")
@login_required
def groups_list():
    user_id = session["user_id"]
    groups_raw = get_user_groups(user_id)
    groups = []

    def fmt_date(d):
        if not d:
            return ""
        if isinstance(d, str):
            try:
                dt = datetime.fromisoformat(d)
            except ValueError:
                return d
        else:
            dt = d
        return dt.strftime("%d-%m-%Y")

    for g in groups_raw:
        group_id = g["group_id"]

        # balans per user ophalen
        balances = get_balances_for_group(group_id)

        # saldo van ingelogde gebruiker zoeken
        my_balance = 0.0
        for b in balances:
            if b["user_id"] == user_id:
                my_balance = b["saldo"]
                break

        groups.append({
    "group_id": g["group_id"],
    "name": g["name"],
    "start_date": g.get("start_date"),
    "end_date": g.get("end_date"),
    "icon": g.get("icon") or "👥",
    "my_balance": round(my_balance, 2)
})



    return render_template("groups_list.html", groups=groups)


@app.route("/groups/create", methods=["GET", "POST"])
@login_required
def groups_create():
    if request.method == "POST":
        name = request.form["name"].strip()
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        icon = request.form.get("icon", "👥")
        organizer_id = session["user_id"]

        if not name:
            flash("Geef een naam voor de groep in.", "error")
            return redirect(url_for("groups_create"))

        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            flash("Ongeldige datum opgegeven.", "error")
            return redirect(url_for("groups_create"))

        if end_date_obj < start_date_obj:
            flash("De einddatum mag niet vóór de startdatum liggen.", "error")
            return redirect(url_for("groups_create"))

        create_group(name, start_date, end_date, organizer_id, icon)
        flash("Groep aangemaakt.", "group_success")
        return redirect(url_for("groups_list"))

    return render_template("groups_create.html")



# ============================================================
# 4. GROUP DETAIL + EXPENSES + PAYMENTS
# ============================================================

@app.route("/groups/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_detail(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.", "error")
        return redirect(url_for("groups_list"))

    # 👉 dezelfde balanslogica als op /balances
    balances = get_balances_for_group(group_id)
    current_user_id = session["user_id"]
    my_balance = next((b for b in balances if b["user_id"] == current_user_id), None)

    def fmt(d):
        if isinstance(d, str):
            try:
                dt = datetime.fromisoformat(d)
            except ValueError:
                return d
        else:
            dt = d
        return dt.strftime("%d-%m-%Y")

    start_date_fmt = fmt(group["start_date"])
    end_date_fmt = fmt(group["end_date"])

    # ----------------------------
    # POST: Expense toevoegen
    # ----------------------------
    if request.method == "POST":
        try:
            description = request.form.get("description", "").strip()
            if not description:
                flash("Geef een beschrijving in.", "error")
                return redirect(url_for("group_detail", group_id=group_id))

            total_amount_str = request.form.get("total_amount", "0").replace(",", ".")
            total_amount = float(total_amount_str)

            if total_amount <= 0:
                flash("Totaal bedrag moet groter dan 0 zijn.", "error")
                return redirect(url_for("group_detail", group_id=group_id))

            paid_by = int(request.form["paid_by"])
            split_type = request.form.get("split_type", "equal")
            member_ids = [int(uid) for uid in request.form.getlist("members")]

            if not member_ids:
                flash("Je moet minstens één persoon selecteren.", "error")
                return redirect(url_for("group_detail", group_id=group_id))

            shares = {}

            if split_type == "equal":
                n = len(member_ids)
                total_cents = int(round(total_amount * 100))
                base = total_cents // n
                remainder = total_cents % n

                for i, uid in enumerate(member_ids):
                    shares[uid] = (base + (1 if i < remainder else 0)) / 100.0

            else:
                for m in members:
                    uid = m["users"]["user_id"]
                    if uid in member_ids:
                        key = f"amount_{uid}"
                        amount = float((request.form.get(key) or "0").replace(",", "."))
                        shares[uid] = amount

                if abs(sum(shares.values()) - total_amount) > 0.01:
                    flash("De ingegeven bedragen zijn samen niet gelijk aan het totaal.", "error")
                    return redirect(url_for("group_detail", group_id=group_id))

            add_expense(group_id, paid_by, description, total_amount, shares)
            flash("Uitgave toegevoegd.", "expense_success")
            return redirect(url_for("group_detail", group_id=group_id))

        except Exception as e:
            print("Fout bij toevoegen uitgave:", e)
            flash("Er ging iets mis bij het toevoegen van de uitgave.", "error")
            return redirect(url_for("group_detail", group_id=group_id))

    # ----------------------------
    # GET: expenses ophalen
    # ----------------------------
    expenses = (
        supabase.table("expenses")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    expense_ids = [e["expense_id"] for e in expenses] or [-1]

    shares_all = (
        supabase.table("expense_shares")
        .select("*")
        .in_("expense_id", expense_ids)
        .execute()
        .data or []
    )

    for expense in expenses:
        expense["shares"] = {
            share["user_id"]: float(share["amount"])
            for share in shares_all
            if share["expense_id"] == expense["expense_id"]
        }

    total = sum(float(e["total_amount"]) for e in expenses)

    # totals per user (alleen nog voor settlement/overzicht)
    paid = {m["users"]["user_id"]: 0.0 for m in members}
    for e in expenses:
        paid[e["paid_by"]] += float(e["total_amount"])

    verschuldigd = {m["users"]["user_id"]: 0.0 for m in members}
    for e in expenses:
        for uid, amount in e["shares"].items():
            verschuldigd[int(uid)] += amount

    saldo = {uid: paid[uid] - verschuldigd[uid] for uid in paid}

    # 👉 nieuwe je_schuld / krijg_je / netto op basis van balances
    if my_balance:
        netto = round(my_balance["saldo"], 2)
        je_schuld = round(-netto, 2) if netto < 0 else 0.0
        krijg_je = round(netto, 2) if netto > 0 else 0.0
    else:
        netto = 0.0
        je_schuld = 0.0
        krijg_je = 0.0

    uid_naam = {m["users"]["user_id"]: m["users"]["name"] for m in members}

    saldo_lijst = [
        {"uid": uid, "naam": uid_naam[uid], "bedrag": round(amount, 2)}
        for uid, amount in saldo.items()
    ]

    debtors = [d.copy() for d in saldo_lijst if d["bedrag"] < -0.01]
    creditors = [c.copy() for c in saldo_lijst if c["bedrag"] > 0.01]

    debtors.sort(key=lambda x: x["bedrag"])
    creditors.sort(key=lambda x: -x["bedrag"])

    settlements = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]

        amount = min(-debtor["bedrag"], creditor["bedrag"])

        settlements.append({
            "from": debtor["naam"],
            "to": creditor["naam"],
            "amount": round(amount, 2),
        })

        debtor["bedrag"] += amount
        creditor["bedrag"] -= amount

        if debtor["bedrag"] >= -0.01:
            i += 1
        if creditor["bedrag"] <= 0.01:
            j += 1

    # payments voor verrichtingen
    payments = (
        supabase.table("payments")
        .select("payment_id, from_user, to_user, amount, payment_date, status")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    user_map = {m["users"]["user_id"]: m["users"]["name"] for m in members}

    return render_template(
        "group_detail.html",
        group=group,
        members=members,
        expenses=expenses,
        total=total,
        paid=paid,
        verschuldigd=verschuldigd,
        saldo=saldo,
        settlements=settlements,
        uid_naam=uid_naam,
        start_date_fmt=start_date_fmt,
        end_date_fmt=end_date_fmt,
        je_schuld=je_schuld,
        krijg_je=krijg_je,
        netto=netto,
        payments=payments,
        user_map=user_map,
    )



# ============================================================
# 5. WHATSAPP SHARE LINK
# ============================================================

@app.route("/group/<int:group_id>/share")
def share_group(group_id):
    invite_url = url_for("join_group", group_id=group_id, _external=True)
    text = f"Join mijn FairSplit groep: {invite_url}"
    encoded = urllib.parse.quote(text)
    return redirect(f"https://wa.me/?text={encoded}")


@app.route("/group/<int:group_id>/join", methods=["GET", "POST"])
def join_group(group_id):
    # Haal groep + huidige leden op
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.", "error")
        return redirect(url_for("groups_list"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username:
            flash("Geef een naam in.", "error")
            return redirect(url_for("join_group", group_id=group_id))

        # Bestaat deze user al?
        existing = get_user_by_name(username)
        user = existing[0] if existing else create_user(username)
        user_id = user["user_id"]

        # Zit deze user al in de groep?
        already_member = any(m["users"]["user_id"] == user_id for m in members)
        if not already_member:
            supabase.table("group_members").insert({
                "group_id": group_id,
                "user_id": user_id,
                "role": "member"
            }).execute()

        # Log de user direct in
        session["user_id"] = user_id
        session["username"] = user["name"]

        flash("Welkom in de groep!", "success")
        return redirect(url_for("group_detail", group_id=group_id))

    # GET: toon de join-pagina
    return render_template("join_group.html", group=group)


# ============================================================
# 6. BALANS OVERZICHT (NIEUW ALGORITME)
# ============================================================

@app.route("/groups/<int:group_id>/balances")
@login_required
def balances_route(group_id):
    group, _ = get_group_detail(group_id)
    balances = get_balances_for_group(group_id)

    # 1. normale optimale betalingen tussen personen
    optimal_transactions = compute_optimal_transactions(balances)

    # 2. extra FairSplit-transactie toevoegen zolang de app-fee nog niet als betaald gemarkeerd is
    app_fee_paid = group.get("app_fee_paid", False)
    current_user_id = session["user_id"]

    if not app_fee_paid:
        # fee-betaler = huidige gebruiker
        me = next((b for b in balances if b["user_id"] == current_user_id), None)

        # fee-ontvanger = organisator van de groep
        organizer_id = group.get("organizer_id")
        receiver = next((b for b in balances if b["user_id"] == organizer_id), None)

        # zolang de fee niet betaald is en er zowel een betaler als ontvanger is,
        # altijd één FairSplit-transactie tonen
        if me and receiver:
            fee_amount = 3.00  # vaste app-fee per groep

            optimal_transactions.append({
                "from_user_id": me["user_id"],
                "from_name": me["name"],
                "to_user_id": receiver["user_id"],
                "to_name": "FairSplit+",
                "to_iban": receiver["iban"],
                "amount": round(fee_amount, 2),
            })




    # alle payments voor deze groep ophalen (voor verrichtingen)
    payments = (
        supabase.table("payments")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    return render_template(
        "balances.html",
        group=group,
        balances=balances,
        optimal_transactions=optimal_transactions,
        payments=payments,
    )



# ============================================================
# 6b. BETALING REGISTREREN ("IK HEB BETAALD")
# ============================================================

@app.post("/groups/<int:group_id>/pay")
@login_required
def mark_payment(group_id):
    from_user_id = session["user_id"]
    to_user_id = int(request.form["to_user_id"])
    amount = float(request.form["amount"])
    is_fee = request.form.get("is_fee", "0")

    # Altijd een payment registreren (ook voor de app-fee)
    add_payment(group_id, from_user_id, to_user_id, amount)

    # Voor de UI onthouden dat de app-fee betaald is
    if is_fee == "1":
        supabase.table("groups").update({
            "app_fee_paid": True
        }).eq("group_id", group_id).execute()
        flash("App-fee gemarkeerd als betaald.", "success")
    else:
        flash("Betaling geregistreerd.", "success")

    return redirect(url_for("balances_route", group_id=group_id))


# ============================================================
# 7. ADD MEMBER
# ============================================================

@app.route("/groups/<int:group_id>/add_member", methods=["GET", "POST"])
@login_required
def add_member(group_id):
    group, members = get_group_detail(group_id)

    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Geef een naam in.", "error")
            return redirect(url_for("add_member", group_id=group_id))

        user_list = get_user_by_name(name)
        user = user_list[0] if user_list else create_user(name)

        supabase.table("group_members").insert({
            "group_id": group_id,
            "user_id": user["user_id"]
        }).execute()

        flash("Added! Expenses just got a bit softer.", "success-confetti") 
        return redirect(url_for("group_detail", group_id=group_id))

    return render_template("add_member.html", group=group, members=members)


# ============================================================
# 8. DELETE EXPENSE
# ============================================================

@app.post("/expenses/<int:expense_id>/delete")
@login_required
def delete_expense(expense_id):
    supabase.table("expenses").delete().eq("expense_id", expense_id).execute()
    flash("Expense successfully deleted.", "success")
    return redirect(request.referrer or url_for("groups_list"))


# ============================================================
# 9. INDEX
# ============================================================

@app.route("/")
def index():
    return redirect(url_for("login"))


# ============================================================
# 10. PROFIEL
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]

    # Huidige gegevens ophalen
    result = supabase.table("users").select("*").eq("user_id", user_id).execute()
    user = result.data[0] if result.data else None

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        iban = request.form.get("iban", "").strip()

        if not phone or not iban:
            flash("Vul zowel je telefoonnummer als je bankrekeningnummer (IBAN) in.", "error")
            return redirect(url_for("profile"))

        supabase.table("users").update({
            "phone_number": phone,
            "payment_method": iban
        }).eq("user_id", user_id).execute()

        flash("Je profiel is bijgewerkt.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", user=user)


# ============================================================
# 11. PDF DOWNLOAD (MET OPTIMALE BETALINGEN!)
# ============================================================

@app.route('/group/<int:group_id>/download_pdf')
def download_pdf(group_id):
    balances = get_balances_for_group(group_id)

    group = (
        supabase.table("groups")
        .select("name")
        .eq("group_id", group_id)
        .execute()
        .data[0]
    )

    expenses = (
        supabase.table("expenses")
        .select("expense_id, description, total_amount, paid_by")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    users = supabase.table("users").select("user_id, name").execute().data
    user_dict = {u["user_id"]: u["name"] for u in users}

    # 👉 optimale betalingen
    optimal_transactions = compute_optimal_transactions(balances)

    # PDF setup
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    content = []

    # Styles
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=22, alignment=1, spaceAfter=20)
    subtitle_style = ParagraphStyle('Subtitle', fontSize=11, textColor='#555', alignment=1, spaceAfter=20)
    section_title = ParagraphStyle('SectionTitle', fontSize=16, spaceBefore=14, spaceAfter=10)

    # Titel
    content.append(Paragraph(f"FairSplit+ Overzicht – {group['name']}", title_style))
    content.append(Paragraph(f"Gegenereerd op {datetime.now().strftime('%d-%m-%Y %H:%M')}", subtitle_style))

    # -------------------------
    # UITGAVEN TABEL
    # -------------------------
    content.append(Paragraph("Uitgaven", section_title))

    if not expenses:
        content.append(Paragraph("Geen uitgaven geregistreerd.", styles['Normal']))
    else:
        table_data = [["Omschrijving", "Bedrag", "Betaald door"]]
        for e in expenses:
            table_data.append([
                e["description"],
                f"€{float(e['total_amount']):.2f}",
                user_dict.get(e["paid_by"], "?")
            ])

        t = Table(table_data, colWidths=[7*cm, 3*cm, 5*cm])
        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold")
        ]))

        content.append(t)

    # -------------------------
    # SALDO TABEL
    # -------------------------
    content.append(Paragraph("Balans per persoon", section_title))

    bal_table = [["Naam", "Saldo", "App fee"]]
    for b in balances:
        bal_table.append([
            b["name"],
            f"€{b['saldo']:.2f}",
            f"€{b['app_fee']:.2f}",
        ])

    tb = Table(bal_table, colWidths=[7*cm, 3*cm, 3*cm])
    tb.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f0ff")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold")
    ]))

    content.append(tb)

    # CONDITIONELE KLEUREN VOOR SALDO'S
    for row_idx, b in enumerate(balances, start=1):
        saldo = b['saldo']
        if saldo > 0:
            color = colors.HexColor("#0c7b31")
        elif saldo < 0:
            color = colors.HexColor("#b00020")
        else:
            color = colors.black

        tb.setStyle(TableStyle([
            ("TEXTCOLOR", (1, row_idx), (1, row_idx), color)
        ]))

    # -------------------------
    # OPTIMALE BETALINGEN
    # -------------------------
    content.append(Paragraph("Optimale afbetalingen", section_title))

    if optimal_transactions:
        # kolommen: Betaler | Ontvanger (IBAN) | Bedrag
        opt_table = [["Betaler", "Ontvanger", "Bedrag"]]

        for tdata in optimal_transactions:
            # ontvanger + eventueel IBAN tussen haakjes
            if tdata.get("to_iban"):
                ontvanger = f"{tdata['to_name']} ({tdata['to_iban']})"
            else:
                ontvanger = tdata["to_name"]

            opt_table.append([
                tdata["from_name"],
                ontvanger,
                f"€{tdata['amount']:.2f}",
            ])

        tx = Table(opt_table, colWidths=[6*cm, 8*cm, 2*cm])
        tx.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0ffe8")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ]))

        content.append(tx)
    else:
        content.append(Paragraph("Iedereen staat op €0 – geen betalingen nodig.", styles["Normal"]))

    # Build PDF
    doc.build(content)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=balans_{group_id}.pdf'

    return response

