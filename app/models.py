from supabase import create_client
import os


# Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================
# USERS
# ============================


def get_user_by_name(username):
    """Zoek gebruiker op naam."""
    return supabase.table("users").select("*").eq("name", username).execute().data


def create_user(username):
    """Maak een nieuwe gebruiker aan."""
    return supabase.table("users").insert({"name": username}).execute().data[0]


# ============================
# GROUPS
# ============================


def get_user_groups(user_id):
    """Gebruik Supabase RPC om groepen van user op te halen."""
    result = supabase.rpc("get_user_groups", {"uid": user_id}).execute()
    return result.data if result.data else []


def create_group(name, start_date, end_date, organizer_id, icon):
    """Maak groep + voeg organizer toe aan group_members."""
    group = supabase.table("groups").insert({
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "organizer_id": organizer_id,
        "icon": icon,      # emoji opslaan
        "app_fee": 3.00    # TOTALE FEE PER GROEP
    }).execute().data[0]

    supabase.table("group_members").insert({
        "group_id": group["group_id"],
        "user_id": organizer_id,
        "role": "organizer"
    }).execute()

    return group




def get_group_members(group_id):
    """Alle leden van een groep ophalen zonder joined user-info."""
    return supabase.table("group_members").select("*").eq("group_id", group_id).execute().data


def get_group_detail(group_id):
    """Groep + alle leden mét user info ophalen."""
    group = supabase.table("groups").select("*").eq("group_id", group_id).execute().data
    members = (
        supabase.table("group_members")
        .select("*, users(*)")
        .eq("group_id", group_id)
        .execute()
        .data
    )
    return (group[0] if group else None), members


# ============================
# EXPENSES
# ============================


def add_expense(group_id, paid_by, description, total_amount, shares_dict):
    result = supabase.table("expenses").insert({
        "group_id": group_id,
        "paid_by": paid_by,
        "description": description,
        "total_amount": total_amount
    }).execute()

    if not result.data:
        raise Exception("Kon expense niet opslaan.")

    expense = result.data[0]
    expense_id = expense["expense_id"]

    for user_id, amount in shares_dict.items():
        supabase.table("expense_shares").insert({
            "expense_id": expense_id,
            "user_id": user_id,
            "amount": amount
        }).execute()

    return expense


# ============================
# PAYMENTS
# ============================


def add_payment(group_id, from_user_id, to_user_id, amount, method="bank", reference=None):
    """Registreer een betaling tussen twee users in een groep."""
    return supabase.table("payments").insert({
        "from_user": from_user_id,
        "to_user": to_user_id,
        "group_id": group_id,
        "amount": amount,
        "method": method,
        "status": "completed",   # direct voltooid
        "reference": reference,
    }).execute()


# ============================
# BALANCES (VOOR UI)
# ============================


def get_balances_for_group(group_id):
    """Bereken balans per persoon voor de balanspagina en toon de app-fee."""

    members = (
        supabase.table("group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
        .data
    )
    users = supabase.table("users").select("user_id, name, payment_method").execute().data

    user_name_dict = {u["user_id"]: u["name"] for u in users}
    user_iban_dict = {u["user_id"]: u.get("payment_method") for u in users}

    expenses = (
        supabase.table("expenses")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )
    expense_ids = [e["expense_id"] for e in expenses] or [-1]

    shares = (
        supabase.table("expense_shares")
        .select("*")
        .in_("expense_id", expense_ids)
        .execute()
        .data or []
    )

    group_list = (
        supabase.table("groups")
        .select("app_fee")
        .eq("group_id", group_id)
        .execute()
        .data
    )
    total_fee = float(group_list[0]["app_fee"]) if group_list else 0.0

    n_members = len(members)
    fee_per_person = round(total_fee / n_members, 2) if n_members else 0.0

    paid = {m["user_id"]: 0.0 for m in members}
    owed = {m["user_id"]: 0.0 for m in members}

    # uitgaven meenemen
    for exp in expenses:
        if exp["paid_by"] in paid:
            paid[exp["paid_by"]] += float(exp["total_amount"])

    for share in shares:
        if share["user_id"] in owed:
            owed[share["user_id"]] += float(share["amount"])

    # payments meenemen (status completed)
    payments = (
        supabase.table("payments")
        .select("*")
        .eq("group_id", group_id)
        .eq("status", "completed")
        .execute()
        .data or []
    )

    for p in payments:
        from_id = p["from_user"]
        to_id = p["to_user"]
        amt = float(p["amount"])

        # betaler heeft effectief meer betaald
        if from_id in paid:
            paid[from_id] += amt

        # ontvanger heeft minder voorgeschoten (zijn tegoed daalt),
        # MAAR niet als from_id == to_id (zoals bij de app-fee die je aan jezelf markeert)
        if to_id in paid and to_id != from_id:
            paid[to_id] -= amt


    balances = []
    for m in members:
        uid = m["user_id"]
        saldo = round(paid[uid] - owed[uid] - fee_per_person, 2)
        balances.append({
            "user_id": uid,
            "name": user_name_dict.get(uid, "Onbekend"),
            "iban": user_iban_dict.get(uid),
            "saldo": saldo,
            "app_fee": fee_per_person
        })

    return balances


# ============================================================
# ONS "SLIM" ALGORITME VOOR OPTIMALE BETALINGEN
# ============================================================


def compute_optimal_transactions(ui_balances):
    """
    Berekent alleen de optimale betalingen TUSSEN personen.
    De app-fee-transactie wordt later in balances_route toegevoegd.

    (SLIM ALGORITME:
    - Werkt op UI-saldi (inclusief fee)
    - Lost eerst ALLE interne schulden op
    - Combineert daarna ALLE resterende debiteuren
    - De grootste debiteur betaalt ALTIJD de volledige fee (€3)
    - Minimaliseert het aantal transacties (zoals Splitwise))
    """

    EPS = 0.005

    # 1. Netto UI-saldi
    members = [{
        "user_id": bal["user_id"],
        "name": bal["name"],
        "iban": bal["iban"],
        "amount": bal["saldo"]
    } for bal in ui_balances]

    # 2. Split in debiteuren en crediteuren
    debtors = []
    creditors = []

    for m in members:
        if m["amount"] < -EPS:
            debtors.append({**m, "amount": -m["amount"]})
        elif m["amount"] > EPS:
            creditors.append(m)

    debtors.sort(key=lambda x: x["amount"], reverse=True)   # grootste schuld eerst
    creditors.sort(key=lambda x: x["amount"], reverse=True) # grootste tegoed eerst

    transactions = []

    # 3. Optimaliseren: zo weinig mogelijk betalingen
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d = debtors[i]
        c = creditors[j]

        amount = min(d["amount"], c["amount"])

        transactions.append({
            "from_user_id": d["user_id"],
            "from_name": d["name"],
            "to_user_id": c["user_id"],
            "to_name": c["name"],
            "to_iban": c["iban"],
            "amount": round(amount, 2)
        })

        d["amount"] -= amount
        c["amount"] -= amount

        if d["amount"] <= EPS:
            i += 1
        if c["amount"] <= EPS:
            j += 1

    return transactions
