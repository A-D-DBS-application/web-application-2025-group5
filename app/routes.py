from flask import render_template, request, redirect, url_for, session, flash
from app import app
from app.models import (
    get_user_by_name,
    create_user,
    get_user_groups,
    create_group,
    get_group_detail,
    get_group_members,
    add_expense,
    get_balances_for_group,
    supabase,
)
from datetime import datetime  # <-- toegevoegd
import urllib.parse    

# 1. Hulpfunctie: login_required
def login_required(route_function):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Je moet eerst inloggen.", "error")
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)

    wrapper.__name__ = route_function.__name__
    return wrapper

# 2. LOGIN
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

# 3. LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.", "success")
    return redirect(url_for("login"))

# 4. GROEPEN OVERZICHT & AANMAKEN
@app.route("/groups")
@login_required
def groups_list():
    user_id = session["user_id"]
    groups = get_user_groups(user_id)
    return render_template("groups_list.html", groups=groups)

# [4A] AANGEPASTE ROUTE: VALIDATIE BEGIN- EN EINDDATUM
@app.route("/groups/create", methods=["GET", "POST"])
@login_required
def groups_create():
    if request.method == "POST":
        name = request.form["name"].strip()
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        organizer_id = session["user_id"]

        if not name:
            flash("Geef een naam voor de groep in.", "error")
            return redirect(url_for("groups_create"))

        # Validatie: einddatum niet vóór startdatum
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            flash("Ongeldige datum opgegeven.", "error")
            return redirect(url_for("groups_create"))
        if end_date_obj < start_date_obj:
            flash("De einddatum mag niet vóór de startdatum liggen.", "error")
            return redirect(url_for("groups_create"))

        create_group(name, start_date, end_date, organizer_id)
        flash("Groep aangemaakt.", "success")
        return redirect(url_for("groups_list"))

    return render_template("groups_create.html")

# 5. GROEPSDETAIL: alles-in-één-pagina
@app.route("/groups/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_detail(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.", "error")
        return redirect(url_for("groups_list"))

    # ===========================
    # UITGAVE TOEVOEGEN (POST)
    # ===========================
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

            paid_by = int(request.form.get("paid_by"))
            split_type = request.form.get("split_type", "equal")  # default: gelijk delen
            member_ids = [int(uid) for uid in request.form.getlist("members")]

            if not member_ids:
                flash("Je moet minstens één persoon selecteren.", "error")
                return redirect(url_for("group_detail", group_id=group_id))

            shares = {}
            selected_ids = set(member_ids)

            # ---------------------------
            # 5.1 Equal split
            # ---------------------------
            if split_type == "equal":
                n = len(member_ids)
                # werk in centen voor nette afronding
                total_cents = int(round(total_amount * 100))
                base = total_cents // n
                remainder = total_cents % n

                for i, uid in enumerate(member_ids):
                    share_cents = base + (1 if i < remainder else 0)
                    shares[uid] = share_cents / 100.0

            # ---------------------------
            # 5.2 Manual split
            # ---------------------------
            else:  # split_type == "manual"
                for m in members:
                    uid = m["users"]["user_id"]
                    if uid in selected_ids:
                        key = f"amount_{uid}"
                        value_str = (request.form.get(key) or "0").replace(",", ".")
                        amount = float(value_str)
                        shares[uid] = amount

                som = sum(shares.values())
                if abs(som - total_amount) > 0.01:
                    flash(
                        "De ingegeven bedragen zijn samen niet gelijk aan het totaal.",
                        "error",
                    )
                    return redirect(url_for("group_detail", group_id=group_id))

            # ---------------------------
            # 5.3 Wegschrijven via models.add_expense
            # ---------------------------
            add_expense(group_id, paid_by, description, total_amount, shares)
            flash("Uitgave succesvol toegevoegd.", "success")
            return redirect(url_for("group_detail", group_id=group_id))

        except Exception as e:
            # Hier vangen we alle fouten op zodat de pagina niet crasht
            print("Fout bij toevoegen uitgave:", e)
            flash("Er ging iets mis bij het toevoegen van de uitgave.", "error")
            return redirect(url_for("group_detail", group_id=group_id))

    # ===========================
    # GET: UITGAVEN & BALANS
    # ===========================
    expenses = (
        supabase.table("expenses")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data
        or []
    )

    expense_ids = [e["expense_id"] for e in expenses]
    if not expense_ids:
        expense_ids = [-1]  # zodat de query niet faalt bij lege lijst

    shares_all = (
        supabase.table("expense_shares")
        .select("*")
        .in_("expense_id", expense_ids)
        .execute()
        .data
        or []
    )

    # shares toevoegen aan elke expense
    for expense in expenses:
        expense["shares"] = {}
        for share in shares_all:
            if share["expense_id"] == expense["expense_id"]:
                expense["shares"][share["user_id"]] = float(share["amount"])

    total = sum(float(e["total_amount"]) for e in expenses)

    # Totaal betaald per persoon
    paid = {m["users"]["user_id"]: 0.0 for m in members}
    for expense in expenses:
        uid = expense["paid_by"]
        paid[uid] = paid.get(uid, 0.0) + float(expense["total_amount"])

    # Totaal verschuldigd per persoon (via shares)
    verschuldigd = {m["users"]["user_id"]: 0.0 for m in members}
    for expense in expenses:
        for uid, amount in expense.get("shares", {}).items():
            verschuldigd[int(uid)] += float(amount)

    # Saldo = betaald - verschuldigd
    saldo = {uid: paid[uid] - verschuldigd[uid] for uid in verschuldigd}

    # Settlement berekenen
    uid_naam = {m["users"]["user_id"]: m["users"]["name"] for m in members}

    saldo_lijst = [
        {"uid": uid, "naam": uid_naam[uid], "bedrag": round(bedrag, 2)}
        for uid, bedrag in saldo.items()
    ]

    debtors = [p.copy() for p in saldo_lijst if p["bedrag"] < -0.01]
    creditors = [p.copy() for p in saldo_lijst if p["bedrag"] > 0.01]

    debtors.sort(key=lambda x: x["bedrag"])  # meest negatief eerst
    creditors.sort(key=lambda x: -x["bedrag"])  # meest positief eerst

    settlements = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        te_betalen = min(-debtor["bedrag"], creditor["bedrag"])

        if te_betalen < 0.01:
            break

        settlements.append(
            {
                "from": debtor["naam"],
                "to": creditor["naam"],
                "amount": round(te_betalen, 2),
            }
        )

        debtor["bedrag"] += te_betalen
        creditor["bedrag"] -= te_betalen

        if abs(debtor["bedrag"]) < 0.01:
            i += 1
        if creditor["bedrag"] < 0.01:
            j += 1

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
    )



# 6. BALANSOVERZICHT
@app.route("/groups/<int:group_id>/balances")
@login_required
def balances_route(group_id):
    group, _ = get_group_detail(group_id)
    balances = get_balances_for_group(group_id)
    return render_template("balances.html", group=group, balances=balances)

# 7. STARTPAGINA
@app.route("/")
def index():
    return redirect(url_for("login"))

# 8. LID TOEVOEGEN
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

        supabase.table("group_members").insert(
            {"group_id": group_id, "user_id": user["user_id"]}
        ).execute()

        flash("Lid toegevoegd.", "success")
        return redirect(url_for("group_detail", group_id=group_id))

    return render_template("add_member.html", group=group, members=members)

# 8b. WHATSAPP-LINK MAKEN MET JOIN-URL
@app.route("/group/<int:group_id>/share")
@login_required
def share_group(group_id):
    # Haal groep op voor een mooie naam in het bericht
    group, _ = get_group_detail(group_id)
    group_name = group["name"] if group else "mijn FairSplit+ groep"

    # Dit is de URL waar de genodigden terechtkomen en hun naam invullen
    invite_url = url_for("join_group", group_id=group_id, _external=True)

    text = f"Join mijn FairSplit+ groep '{group_name}': {invite_url}"
    encoded = urllib.parse.quote(text)

    whatsapp_url = f"https://wa.me/?text={encoded}"
    return redirect(whatsapp_url)


# 8c. JOIN-PAGINA: NAAM INGEVEN EN AUTOMATISCH LID WORDEN
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

        # Bestaat deze user al?
        existing = get_user_by_name(username)
        user = existing[0] if existing else create_user(username)
        user_id = user["user_id"]

        # Zit deze user al in de groep?
        already_member = any(m["user_id"] == user_id for m in members)
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


# 9. UITGAVE VERWIJDEREN
@app.post("/expenses/<int:expense_id>/delete")
@login_required
def delete_expense(expense_id):
    # dankzij ON DELETE CASCADE verdwijnen ook de shares automatisch
    supabase.table("expenses").delete().eq("expense_id", expense_id).execute()
    flash("Uitgave verwijderd.", "success")
    # ga terug naar de vorige pagina (meestal group_detail)
    return redirect(request.referrer or url_for("groups_list"))

# 10. PDF toevoegen
from flask import make_response
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from io import BytesIO
from datetime import datetime

@app.route('/group/<int:group_id>/download_pdf')
def download_pdf(group_id):

    # ---------------------------------
    # DATA OPHALEN
    # ---------------------------------
    balances = get_balances_for_group(group_id)

    group = (
        supabase.table("groups")
        .select("name")
        .eq("group_id", group_id)
        .execute()
        .data
    )[0]

    expenses = (
        supabase.table("expenses")
        .select("expense_id, description, total_amount, paid_by")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )

    users = supabase.table("users").select("user_id, name").execute().data
    user_dict = {u["user_id"]: u["name"] for u in users}

    # ---------------------------------
    # PDF SETUP
    # ---------------------------------
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    content = []

    # Stijlen aanmaken
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Title'],
        fontSize=22,
        alignment=1,  # center
        spaceAfter=20
    )

    subtitle_style = ParagraphStyle(
        'Subtitle',
        fontSize=11,
        textColor='#555555',
        alignment=1,
        spaceAfter=20
    )

    section_title = ParagraphStyle(
        'SectionTitle',
        fontSize=16,
        spaceBefore=10,
        spaceAfter=10
    )

    # ---------------------------------
    # TITEL
    # ---------------------------------
    content.append(Paragraph(f"FairSplit+ Overzicht – {group['name']}", title_style))
    content.append(Paragraph(f"Gegenereerd op {datetime.now().strftime('%d-%m-%Y %H:%M')}", subtitle_style))

    # ---------------------------------
    # UITGAVEN TABEL
    # ---------------------------------
    content.append(Paragraph("Uitgaven", section_title))

    if not expenses:
        content.append(Paragraph("Geen uitgaven geregistreerd.", styles['Normal']))
    else:
        table_data = [["Omschrijving", "Bedrag", "Betaald door"]]

        for e in expenses:
            payer = user_dict.get(e["paid_by"], "Onbekend")
            table_data.append([
                e["description"],
                f"€{float(e['total_amount']):.2f}",
                payer
            ])

        t = Table(table_data, colWidths=[7*cm, 3*cm, 5*cm])
        t.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BOTTOMPADDING", (0,0), (-1,0), 8),

            # Alignment
            ("ALIGN", (0,1), (0,-1), "LEFT"),    # Omschrijving
            ("ALIGN", (1,1), (1,-1), "RIGHT"),   # Bedrag
            ("ALIGN", (2,1), (2,-1), "RIGHT"),   # Betaald door
        ]))

        content.append(t)

    # ---------------------------------
    # BALANS TABEL
    # ---------------------------------
    content.append(Paragraph("Eindbalans per persoon", section_title))

    balance_table = [["Naam", "Saldo", "App fee"]]

    for b in balances:
        balance_table.append([
            b["name"],
            f"€{b['saldo']:.2f}",
            f"€{b['app_fee']:.2f}"
        ])

    tb = Table(balance_table, colWidths=[7*cm, 3*cm, 3*cm])
    tb.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f0ff")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0,0), (-1,0), 8),

        # Alignments
        ("ALIGN", (0,1), (0,-1), "LEFT"),     # Naam
        ("ALIGN", (1,1), (2,-1), "RIGHT"),    # Saldo & App fee rechts
    ]))

    # CONDITIONELE KLEUR VOOR SALDO'S
    for row_idx, b in enumerate(balances, start=1):
        saldo = b['saldo']
        color = colors.green if saldo > 0 else colors.red if saldo < 0 else colors.black
        tb.setStyle(TableStyle([
            ("TEXTCOLOR", (1, row_idx), (1, row_idx), color)
        ]))

    content.append(tb)

    # ---------------------------------
    # PDF AFMAKEN
    # ---------------------------------
    doc.build(content)

    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=balans_{group_id}.pdf'

    return response
