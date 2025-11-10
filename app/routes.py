from flask import render_template, request, redirect, url_for, session, flash
from app import app
from app.models import get_user_by_name, create_user, get_user_groups, create_group, get_group_detail, add_expense, get_balances_for_group, supabase

# 1. Hulpfunctie: login_required
def login_required(route_function):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Je moet eerst inloggen.")
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
            flash("Vul een gebruikersnaam in.")
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
    flash("Je bent uitgelogd.")
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
        create_group(name, start_date, end_date, organizer_id)
        return redirect(url_for("groups_list"))
    return render_template("groups_create.html")

# 5. GROEPSDETAIL: alles-in-één-pagina
@app.route("/groups/<int:group_id>", methods=["GET", "POST"])
@login_required
def group_detail(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.")
        return redirect(url_for("groups_list"))
    # Uitgave toevoegen via POST
    if request.method == "POST":
        description = request.form.get('description', '').strip()
        total_amount = float(request.form.get('total_amount', 0))
        paid_by = int(request.form.get('paid_by', 0))
        shares = {}
        for member in members:
            uid = member['users']['user_id'] if member.get('users') else member['user_id']
            key = f"share_{uid}"
            shares[uid] = float(request.form.get(key, 0))
        add_expense(group_id, paid_by, description, total_amount, shares)
        return redirect(url_for('group_detail', group_id=group_id))

    # Uitgaven ophalen + totaalbedrag
    expenses = supabase.table('expenses').select('*').eq('group_id', group_id).execute().data or []
    expense_ids = [e['expense_id'] for e in expenses]
    if not expense_ids:
        expense_ids = [-1]  # zodat de query niet faalt bij lege lijst
    shares_all = supabase.table('expense_shares').select('*').in_('expense_id', expense_ids).execute().data or []

    # Voeg 'shares' dict toe aan elk expense; {user_id: amount}
    for expense in expenses:
        expense['shares'] = {}
        for share in shares_all:
            if share['expense_id'] == expense['expense_id']:
                expense['shares'][share['user_id']] = float(share['amount'])

    total = sum(float(e['total_amount']) for e in expenses)

    # Totaal betaald per persoon
    paid = {member['users']['user_id']: 0 for member in members}
    for expense in expenses:
        uid = expense['paid_by']
        paid[uid] = paid.get(uid, 0) + float(expense['total_amount'])

    # Totaal verschuldigd per persoon (via shares)
    verschuldigd = {member['users']['user_id']: 0 for member in members}
    for expense in expenses:
        print("Shares per expense:", expense['description'], expense.get('shares', {}), flush=True)
        print("Verschuldigd nu:", verschuldigd, flush=True)
        for uid, amount in expense['shares'].items():
            verschuldigd[int(uid)] += float(amount)

    # Saldo berekenen
    saldo = {uid: paid[uid] - verschuldigd[uid] for uid in verschuldigd}

    # Settlement/betalingen berekenen
    saldo_lijst = []
    uid_naam = {member['users']['user_id']: member['users']['name'] for member in members}
    for uid, bedrag in saldo.items():
        saldo_lijst.append({'uid': uid, 'naam': uid_naam[uid], 'bedrag': round(bedrag,2)})
    debtors = [persoon.copy() for persoon in saldo_lijst if persoon['bedrag'] < -0.01]
    creditors = [persoon.copy() for persoon in saldo_lijst if persoon['bedrag'] > 0.01]
    debtors.sort(key=lambda x: x['bedrag'])
    creditors.sort(key=lambda x: -x['bedrag'])

    settlements = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        te_betalen = min(-debtor['bedrag'], creditor['bedrag'])
        if te_betalen < 0.01:
            break
        settlements.append({
            'from': debtor['naam'],
            'to': creditor['naam'],
            'amount': round(te_betalen, 2)
        })
        debtor['bedrag'] += te_betalen
        creditor['bedrag'] -= te_betalen
        if abs(debtor['bedrag']) < 0.01:
            i += 1
        if creditor['bedrag'] < 0.01:
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
        settlements=settlements
    )



# 6. BALANSOVERZICHT
@app.route('/groups/<int:group_id>/balances')
@login_required
def balances_route(group_id):
    group, _ = get_group_detail(group_id)
    balances = get_balances_for_group(group_id)
    return render_template('balances.html', group=group, balances=balances)

# 7. STARTPAGINA
@app.route("/")
def index():
    return redirect(url_for("login"))

# leden toevoegen
@app.route("/groups/<int:group_id>/add_member", methods=["GET", "POST"])
@login_required
def add_member(group_id):
    group, members = get_group_detail(group_id)
    if request.method == "POST":
        name = request.form["name"].strip()
        # Controleer gebruiker, maak aan als niet bestaat
        from app.models import get_user_by_name, create_user, supabase
        user = get_user_by_name(name)
        user = user[0] if user else create_user(name)
        # Voeg aan group_members toe
        supabase.table("group_members").insert({
            "group_id": group_id,
            "user_id": user["user_id"]
        }).execute()
        return redirect(url_for("group_detail", group_id=group_id))
    return render_template("add_member.html", group=group, members=members)
