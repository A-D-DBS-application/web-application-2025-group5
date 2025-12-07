from supabase import create_client
import os

# ============================================================
# SUPABASE CLIENT
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================
# USERS
# ============================================================

def get_user_by_name(username):
    """Zoek gebruiker op naam."""
    return (
        supabase.table("users")
        .select("*")
        .eq("name", username)
        .execute()
        .data
    )


def create_user(username):
    """Maak een nieuwe gebruiker aan."""
    return (
        supabase.table("users")
        .insert({"name": username})
        .execute()
        .data[0]
    )


# ============================================================
# GROUPS
# ============================================================

def get_user_groups(user_id):
    """Gebruik Supabase RPC om groepen van user op te halen."""
    result = supabase.rpc("get_user_groups", {"uid": user_id}).execute()
    return result.data if result.data else []


def get_group_detail(group_id):
    """
    Haal groep + alle leden met user-info op.
    Wordt gebruikt in routes.py op meerdere plaatsen.
    """
    group = (
        supabase.table("groups")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data
    )

    members = (
        supabase.table("group_members")
        .select("*, users(*)")
        .eq("group_id", group_id)
        .execute()
        .data
    )

    return (group[0] if group else None), members


def create_group(name, start_date, end_date, organizer_id, icon):
    """
    Nieuwe groep aanmaken:
    ✔ Organizer toevoegen
    ✔ Automatische app-fee expense (organizer betaalt initieel €3)
    ✔ Bij latere groepsuitbreiding → fee wordt automatisch herverdeeld
    """

    # 1. groep maken
    group = (
        supabase.table("groups")
        .insert({
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "organizer_id": organizer_id,
            "icon": icon
        })
        .execute()
        .data[0]
    )
    group_id = group["group_id"]

    # 2. organizer toevoegen
    supabase.table("group_members").insert({
        "group_id": group_id,
        "user_id": organizer_id,
        "role": "organizer"
    }).execute()

    # 3. automatische fee expense
    APP_FEE = 3.00

    exp = (
        supabase.table("expenses")
        .insert({
            "group_id": group_id,
            "paid_by": organizer_id,
            "description": "FairSplit+ app fee",
            "total_amount": APP_FEE
        })
        .execute()
        .data[0]
    )
    fee_expense_id = exp["expense_id"]

    # initieel 1 lid → hele fee gaat naar organizer
    supabase.table("expense_shares").insert({
        "expense_id": fee_expense_id,
        "user_id": organizer_id,
        "amount": APP_FEE
    }).execute()

    return group


# ============================================================
# APP-FEE HERVERDELING
# ============================================================

def redistribute_app_fee(group_id):
    """
    Herverdeel de app-fee over alle leden:
    ✔ Vind de fee expense
    ✔ Vind alle members
    ✔ Deel fee gelijk (equal split)
    ✔ Verwijder oude shares
    ✔ Voeg nieuwe shares toe
    """

    # 1. leden
    members = (
        supabase.table("group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
        .data
    )
    member_ids = [m["user_id"] for m in members]
    n = len(member_ids)

    # 2. fee expense zoeken
    fee_expense = (
        supabase.table("expenses")
        .select("expense_id, total_amount")
        .eq("group_id", group_id)
        .eq("description", "FairSplit+ app fee")
        .execute()
        .data
    )

    if not fee_expense:
        return

    expense_id = fee_expense[0]["expense_id"]
    fee_total = float(fee_expense[0]["total_amount"])

    # 3. nieuwe shares
    per_user = round(fee_total / n, 2)

    # 4. oude shares verwijderen
    supabase.table("expense_shares").delete().eq("expense_id", expense_id).execute()

    # 5. nieuwe shares aanmaken
    for uid in member_ids:
        supabase.table("expense_shares").insert({
            "expense_id": expense_id,
            "user_id": uid,
            "amount": per_user
        }).execute()


# ============================================================
# EXPENSES
# ============================================================

def add_expense(group_id, paid_by, description, total_amount, shares_dict):
    """Voeg een expense toe + een lijst shares."""
    result = (
        supabase.table("expenses")
        .insert({
            "group_id": group_id,
            "paid_by": paid_by,
            "description": description,
            "total_amount": total_amount
        })
        .execute()
    )

    expense = result.data[0]
    expense_id = expense["expense_id"]

    # shares opslaan
    for user_id, amount in shares_dict.items():
        supabase.table("expense_shares").insert({
            "expense_id": expense_id,
            "user_id": user_id,
            "amount": amount
        }).execute()

    return expense


# ============================================================
# PAYMENTS
# ============================================================

def add_payment(group_id, from_user_id, to_user_id, amount, method="bank", reference=None):
    """Registreer een betaling in payments-tabel."""
    return supabase.table("payments").insert({
        "from_user": from_user_id,
        "to_user": to_user_id,
        "group_id": group_id,
        "amount": amount,
        "method": method,
        "status": "completed",
        "reference": reference,
    }).execute()


# ============================================================
# BALANCES (som moet exact 0 zijn)
# ============================================================

def get_balances_for_group(group_id):
    """
    Balans per persoon:
    saldo = (betaald) - (verschuldigd)

    ✔ fee zit in expense → géén extra logica nodig
    ✔ saldi tellen altijd op tot 0
    ✔ werkt perfect voor optimale betalingen
    """

    # 1. members
    members = (
        supabase.table("group_members")
        .select("user_id")
        .eq("group_id", group_id)
        .execute()
        .data
    )
    member_ids = [m["user_id"] for m in members]

    # 2. user data
    users = supabase.table("users").select("*").execute().data
    name_map = {u["user_id"]: u["name"] for u in users}
    iban_map = {u["user_id"]: u.get("payment_method") for u in users}

    # 3. expenses
    expenses = (
        supabase.table("expenses")
        .select("*")
        .eq("group_id", group_id)
        .execute()
        .data or []
    )
    expense_ids = [e["expense_id"] for e in expenses] or [-1]

    # 4. shares
    shares = (
        supabase.table("expense_shares")
        .select("*")
        .in_("expense_id", expense_ids)
        .execute()
        .data or []
    )

    # 5. basisstructuren
    paid = {uid: 0.0 for uid in member_ids}
    owed = {uid: 0.0 for uid in member_ids}

    # geld voorgeschoten
    for e in expenses:
        paid[e["paid_by"]] += float(e["total_amount"])

    # verdeling van kosten
    for s in shares:
        owed[s["user_id"]] += float(s["amount"])

    # 6. payments verwerken
    payments = (
        supabase.table("payments")
        .select("*")
        .eq("group_id", group_id)
        .eq("status", "completed")
        .execute()
        .data or []
    )

    for p in payments:
        amt = float(p["amount"])
        paid[p["from_user"]] += amt
        if p["to_user"] in paid and p["to_user"] != p["from_user"]:
            paid[p["to_user"]] -= amt

    # 7. saldi
    balances = []
    for uid in member_ids:
        saldo = round(paid[uid] - owed[uid], 2)
        balances.append({
            "user_id": uid,
            "name": name_map.get(uid, "Onbekend"),
            "iban": iban_map.get(uid),
            "saldo": saldo
        })

    return balances


# ============================================================
# ONS SLIM ALGORITME VOOR OPTIMALE AFBETALINGEN
# ============================================================

def compute_optimal_transactions(ui_balances):
    """
    Berekent minimale set betalingen zoals Splitwise:

    ✔ Splits debiteuren en crediteuren
    ✔ Combineert grote bedragen eerst
    ✔ Minimaliseert aantal betalingen
    ✔ Werkt perfect omdat saldi altijd = 0 som
    """

    EPS = 0.005

    members = [{
        "user_id": b["user_id"],
        "name": b["name"],
        "iban": b["iban"],
        "amount": b["saldo"],
    } for b in ui_balances]

    debtors = []
    creditors = []

    for m in members:
        if m["amount"] < -EPS:
            debtors.append({**m, "amount": -m["amount"]})
        elif m["amount"] > EPS:
            creditors.append(m)

    debtors.sort(key=lambda x: x["amount"], reverse=True)
    creditors.sort(key=lambda x: x["amount"], reverse=True)

    transactions = []
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
