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
    redistribute_app_fee,
    supabase,
    add_payment,
)
from datetime import datetime, date
import urllib.parse
from io import BytesIO

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm



# ============================================================
# CONTEXT PROCESSOR
# ============================================================

@app.context_processor
def inject_profile_status():
    profile_incomplete = False

    if session.get("user_id"):
        user_id = session["user_id"]
        res = supabase.table("users").select(
            "phone_number, payment_method"
        ).eq("user_id", user_id).execute()

        if res.data:
            u = res.data[0]
            if not u.get("phone_number") or not u.get("payment_method"):
                profile_incomplete = True

    return dict(profile_incomplete=profile_incomplete)



# ============================================================
# LOGIN REQUIRED
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
# LOGIN / LOGOUT
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
# GROUP LIST
# ============================================================


@app.route("/groups")
@login_required
def groups_list():
    user_id = session["user_id"]
    groups_raw = get_user_groups(user_id)

    groups = []
    for g in groups_raw:
        group_id = g["group_id"]
        balances = get_balances_for_group(group_id)

        my_balance = next(
            (b["saldo"] for b in balances if b["user_id"] == user_id),
            0.0
        )

        # ------------------------------
        # EINDE-DATUM CHECK (VERLOPEN)
        # ------------------------------
        end_date = g.get("end_date")
        is_expired = False

        if end_date:
            try:
                # Als end_date string is (zoals meestal)
                if isinstance(end_date, str):
                    ed = datetime.strptime(end_date, "%Y-%m-%d").date()
                else:
                    ed = end_date  # fallback als het al een date is

                if date.today() > ed:
                    is_expired = True
            except:
                pass

        # ------------------------------
        # GROEP TOEVOEGEN AAN LIJST
        # ------------------------------
        groups.append({
            "group_id": group_id,
            "name": g["name"],
            "start_date": g.get("start_date"),
            "end_date": end_date,
            "icon": g.get("icon") or "👥",
            "my_balance": round(my_balance, 2),
            "expired": is_expired,   # 👈 BELANGRIJK
        })

    return render_template("groups_list.html", groups=groups)




# ============================================================
# CREATE GROUP
# ============================================================

@app.route("/groups/create", methods=["GET", "POST"])
@login_required
def groups_create():
    if request.method == "POST":
        name = request.form["name"].strip()
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        icon = request.form.get("icon")
        organizer_id = session["user_id"]

        if not name:
            flash("Geef een groepsnaam in.", "error")
            return redirect(url_for("groups_create"))
        
         # NIEUWE CHECK: icoon verplicht
        if not icon:
            flash("Kies een icoon voor de groep.", "error")
            return redirect(url_for("groups_create"))

        # datum controle
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            if ed < sd:
                flash("Einddatum mag niet vóór startdatum liggen.", "error")
                return redirect(url_for("groups_create"))
        except:
            flash("Ongeldige datum.", "error")
            return redirect(url_for("groups_create"))

        create_group(name, start_date, end_date, organizer_id, icon)
        flash("Groep aangemaakt!", "group_success")
        return redirect(url_for("groups_list"))

    return render_template("groups_create.html")



# ============================================================
# GROUP RENAME  (fix voor jouw fout!)
# ============================================================

@app.route("/groups/<int:group_id>/rename", methods=["POST"])
@login_required
def group_rename(group_id):
    new_name = request.form.get("new_name", "").strip()

    if not new_name:
        flash("Naam mag niet leeg zijn.", "error")
        return redirect(url_for("group_detail", group_id=group_id))

    supabase.table("groups").update({"name": new_name}).eq("group_id", group_id).execute()
    flash("Groepsnaam gewijzigd!", "success")
    return redirect(url_for("group_detail", group_id=group_id))



# ============================================================
# GROUP DETAIL
# ============================================================

@app.route("/groups/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_detail(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.", "error")
        return redirect(url_for("groups_list"))

    # --------------------------------
    # Check of de groep verlopen is
    # --------------------------------
    is_expired = False
    end_date = group.get("end_date")

    if end_date:
        try:
            # end_date kan bv. "2025-12-08" of "2025-12-08T00:00:00+00:00" zijn
            end_str = str(end_date)[:10]          # eerste 10 tekens: YYYY-MM-DD
            ed = datetime.strptime(end_str, "%Y-%m-%d").date()

            if date.today() > ed:
                is_expired = True
        except Exception as e:
            print("Fout bij parsen einddatum groep:", e)

    # -------------------------------
    # POST = nieuwe uitgave
    # -------------------------------
    if request.method == "POST":

        # als groep verlopen is → niks meer toevoegen
        if is_expired:
            flash("Deze groep is verlopen. Je kunt geen uitgaven meer toevoegen.", "error")
            return redirect(url_for("group_detail", group_id=group_id))

        try:
            description = request.form.get("description", "").strip()
            total_amount = float(request.form.get("total_amount", "0").replace(",", "."))
            paid_by = int(request.form["paid_by"])
            split_type = request.form.get("split_type", "equal")
            member_ids = [int(x) for x in request.form.getlist("members")]

            if not description or total_amount <= 0 or not member_ids:
                flash("Vul alle velden correct in.", "error")
                return redirect(url_for("group_detail", group_id=group_id))

            # -------------------------------
            # VERDELING
            # -------------------------------
            shares = {}
            if split_type == "equal":
                total_cents = int(round(total_amount * 100))
                base = total_cents // len(member_ids)
                rem = total_cents % len(member_ids)
                for i, uid in enumerate(member_ids):
                    shares[uid] = (base + (1 if i < rem else 0)) / 100
            else:
                for m in members:
                    uid = m["users"]["user_id"]
                    if uid in member_ids:
                        val = float(request.form.get(f"amount_{uid}", "0").replace(",", "."))
                        shares[uid] = val
                if abs(sum(shares.values()) - total_amount) > 0.01:
                    flash("De verdeling klopt niet met het totaal.", "error")
                    return redirect(url_for("group_detail", group_id=group_id))

            add_expense(group_id, paid_by, description, total_amount, shares)
            flash("Uitgave toegevoegd!", "expense_success")

        except Exception as e:
            print("ERROR:", e)
            flash("Er ging iets mis.", "error")

        return redirect(url_for("group_detail", group_id=group_id))

    # -------------------------------
    # GET = gegevens ophalen
    # -------------------------------

    expenses = (
        supabase.table("expenses").select("*").eq("group_id", group_id).execute().data or []
    )

    # Shares ophalen
    exp_ids = [e["expense_id"] for e in expenses] or [-1]
    shares_raw = (
        supabase.table("expense_shares").select("*").in_("expense_id", exp_ids).execute().data or []
    )

    for e in expenses:
        e["shares"] = {
            s["user_id"]: float(s["amount"])
            for s in shares_raw
            if s["expense_id"] == e["expense_id"]
        }

    # Balansen
    balances = get_balances_for_group(group_id)
    current_user = session["user_id"]

    my_balance = next((b for b in balances if b["user_id"] == current_user), {"saldo": 0})
    netto = round(my_balance["saldo"], 2)
    krijg_je = netto if netto > 0 else 0
    je_schuld = -netto if netto < 0 else 0

    # Payments
    payments = supabase.table("payments").select("*").eq("group_id", group_id).execute().data or []

    # Map voor namen
    user_map = {m["users"]["user_id"]: m["users"]["name"] for m in members}

    return render_template(
        "group_detail.html",
        group=group,
        members=members,
        expenses=expenses,
        balances=balances,
        netto=netto,
        krijg_je=krijg_je,
        je_schuld=je_schuld,
        payments=payments,
        user_map=user_map,
        group_expired=is_expired,   # kan je in de template gebruiken als je wil
    )




# ============================================================
# SHARE VIA WHATSAPP
# ============================================================

@app.route("/group/<int:group_id>/share")
def share_group(group_id):
    url = url_for("join_group", group_id=group_id, _external=True)
    text = f"Join mijn FairSplit groep: {url}"
    encoded = urllib.parse.quote(text)
    return redirect(f"https://wa.me/?text={encoded}")



# ============================================================
# JOIN GROUP  (met fee-herverdeling)
# ============================================================

@app.route("/group/<int:group_id>/join", methods=["GET", "POST"])
def join_group(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.", "error")
        return redirect(url_for("groups_list"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not username:
            flash("Geef een naam in.", "error")
            return redirect(url_for("join_group", group_id=group_id))

        existing = get_user_by_name(username)
        user = existing[0] if existing else create_user(username)
        uid = user["user_id"]

        # indien nog geen lid → toevoegen
        if not any(m["users"]["user_id"] == uid for m in members):
            supabase.table("group_members").insert({
                "group_id": group_id,
                "user_id": uid
            }).execute()

            # fee correct herverdelen
            redistribute_app_fee(group_id)

        session["user_id"] = uid
        session["username"] = user["name"]

        flash("Welkom in de groep!", "success-confetti")
        return redirect(url_for("group_detail", group_id=group_id))

    return render_template("join_group.html", group=group)



# ============================================================
# BALANCES
# ============================================================

@app.route("/groups/<int:group_id>/balances")
@login_required
def balances_route(group_id):
    group, _ = get_group_detail(group_id)
    balances = get_balances_for_group(group_id)
    optimal_transactions = compute_optimal_transactions(balances)

    payments = (
        supabase.table("payments").select("*").eq("group_id", group_id).execute().data or []
    )

    return render_template(
        "balances.html",
        group=group,
        balances=balances,
        optimal_transactions=optimal_transactions,
        payments=payments
    )



# ============================================================
# REGISTER PAYMENT
# ============================================================

@app.post("/groups/<int:group_id>/pay")
@login_required
def mark_payment(group_id):
    from_user_id = session["user_id"]
    to_user_id = int(request.form["to_user_id"])
    amount = float(request.form["amount"])

    add_payment(group_id, from_user_id, to_user_id, amount)

    flash("Betaling geregistreerd!", "success")
    return redirect(url_for("balances_route", group_id=group_id))



# ============================================================
# ADD MEMBER (met fee-herverdeling)
# ============================================================

@app.route("/groups/<int:group_id>/add_member", methods=["GET", "POST"])
@login_required
def add_member(group_id):
    group, members = get_group_detail(group_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Naam mag niet leeg zijn.", "error")
            return redirect(url_for("add_member", group_id=group_id))

        existing = get_user_by_name(name)
        user = existing[0] if existing else create_user(name)

        supabase.table("group_members").insert({
            "group_id": group_id,
            "user_id": user["user_id"]
        }).execute()

        redistribute_app_fee(group_id)

        flash("Lid toegevoegd!", "success-confetti")
        return redirect(url_for("group_detail", group_id=group_id))

    return render_template("add_member.html", group=group, members=members)



# ============================================================
# DELETE EXPENSE
# ============================================================

@app.post("/expenses/<int:expense_id>/delete")
@login_required
def delete_expense(expense_id):
    supabase.table("expenses").delete().eq("expense_id", expense_id).execute()
    flash("Uitgave verwijderd!", "success")
    return redirect(request.referrer or url_for("groups_list"))



# ============================================================
# PROFILE
# ============================================================

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]

    data = supabase.table("users").select("*").eq("user_id", user_id).execute().data
    user = data[0] if data else None

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        iban = request.form.get("iban", "").strip()

        if not phone or not iban:
            flash("Vul alle velden in.", "error")
            return redirect(url_for("profile"))

        supabase.table("users").update({
            "phone_number": phone,
            "payment_method": iban
        }).eq("user_id", user_id).execute()

        flash("Profiel bijgewerkt!", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", user=user)



# ============================================================
# PDF EXPORT (mooie spacing + nette tabellen)
# ============================================================

@app.route("/group/<int:group_id>/download_pdf")
def download_pdf(group_id):
    balances = get_balances_for_group(group_id)

    # Groepsinfo ophalen
    group = (
        supabase.table("groups")
        .select("name")
        .eq("group_id", group_id)
        .execute()
        .data[0]
    )

    # Uitgaven ophalen
    expenses = (
        supabase.table("expenses")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    # Usernamen map
    users = supabase.table("users").select("*").execute().data
    user_map = {u["user_id"]: u["name"] for u in users}

    # Optimale betalingen
    optimal_transactions = compute_optimal_transactions(balances)

    # PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    content = []

    # ------------------------------------------
    # TITEL
    # ------------------------------------------
    content.append(Paragraph(
        f"FairSplit+ Overzicht – {group['name']}",
        ParagraphStyle("Title", fontSize=24, alignment=1, spaceAfter=20)
    ))

    content.append(Paragraph(
        f"Gegenereerd op {datetime.now().strftime('%d-%m-%Y %H:%M')}",
        ParagraphStyle("SubTitle", fontSize=11, alignment=1, textColor=colors.grey, spaceAfter=40)
    ))


    # ------------------------------------------
    # UITGAVEN
    # ------------------------------------------
    content.append(Paragraph("Uitgaven", ParagraphStyle("H1", fontSize=16, spaceAfter=10)))

    if not expenses:
        content.append(Paragraph("Geen uitgaven.", styles["Normal"]))
    else:
        rows = [["Omschrijving", "Bedrag", "Betaald door"]]

        for e in expenses:
            rows.append([
                e["description"],
                f"€{float(e['total_amount']):.2f}",
                user_map.get(e["paid_by"], "?")
            ])

        t = Table(rows, colWidths=[6.5*cm, 3*cm, 4.5*cm])
        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ]))
        content.append(t)

    content.append(Spacer(1, 25))


    # ------------------------------------------
    # BALANS PER PERSOON
    # ------------------------------------------
    content.append(Paragraph("Balans per persoon", ParagraphStyle("H1", fontSize=16, spaceAfter=10)))

    rows = [["Naam", "Saldo"]]
    for b in balances:
        rows.append([b["name"], f"€{b['saldo']:.2f}"])

    t = Table(rows, colWidths=[7.5*cm, 3.5*cm])
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f0ff")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))
    content.append(t)

    content.append(Spacer(1, 30))


    # ------------------------------------------
    # OPTIMALE BETALINGEN
    # ------------------------------------------
    content.append(Paragraph("Optimale afbetalingen", ParagraphStyle("H1", fontSize=16, spaceAfter=10)))

    if optimal_transactions:
        rows = [["Betaler", "Ontvanger", "Bedrag"]]

        for tdata in optimal_transactions:
            receiver = tdata["to_name"]
            if tdata.get("to_iban"):
                receiver += f" ({tdata['to_iban']})"

            rows.append([
                tdata["from_name"],
                receiver,
                f"€{tdata['amount']:.2f}"
            ])

        t = Table(rows, colWidths=[6*cm, 6*cm, 3*cm])
        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0ffe8")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ]))
        content.append(t)
    else:
        content.append(Paragraph(
            "Iedereen staat op €0 — geen betalingen nodig.",
            styles["Normal"]
        ))

    # Klaar
    doc.build(content)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=group_{group_id}_balans.pdf"
    return response

# ============================================================
# INDEX
# ============================================================

@app.route("/")
def index():
    return redirect(url_for("login"))