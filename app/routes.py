from flask import render_template, request, redirect, url_for, session, flash
from app import app
from app.models import (
    get_user_by_name,
    create_user,
    get_user_groups,
    create_group,
    get_group_detail,
    add_expense,
    get_balances_for_group,
    supabase,
)

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


# 9. UITGAVE VERWIJDEREN
@app.post("/expenses/<int:expense_id>/delete")
@login_required
def delete_expense(expense_id):
    # dankzij ON DELETE CASCADE verdwijnen ook de shares automatisch
    supabase.table("expenses").delete().eq("expense_id", expense_id).execute()
    flash("Uitgave verwijderd.", "success")
    # ga terug naar de vorige pagina (meestal group_detail)
    return redirect(request.referrer or url_for("groups_list"))
