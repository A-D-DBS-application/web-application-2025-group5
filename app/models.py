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


def create_group(name, start_date, end_date, organizer_id):
    """Maak groep + voeg organizer toe aan group_members."""
    group = supabase.table("groups").insert({
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "organizer_id": organizer_id,
        "app_fee": 3.00  # <- Hier voeg je de fee direct toe
    }).execute().data[0]

    # Organizer automatisch als lid toevoegen
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
    members = supabase.table("group_members").select("*, users(*)").eq("group_id", group_id).execute().data
    return (group[0] if group else None), members


# ============================
# EXPENSES
# ============================

def add_expense(group_id, paid_by, description, total_amount, shares_dict):
    # 1. Expense aanmaken
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

    # 2. Shares wegschrijven (zonder item_id!)
    for user_id, amount in shares_dict.items():
        supabase.table("expense_shares").insert({
            "expense_id": expense_id,
            "user_id": user_id,
            "amount": amount
        }).execute()

    return expense



# ============================
# BALANCES
# ============================

def get_balances_for_group(group_id):
    """Bereken balans per persoon voor de balanspagina en toon de app-fee."""

    # leden ophalen
    members = supabase.table("group_members").select("user_id").eq("group_id", group_id).execute().data

    # Alle gebruikers opvragen (naam mapping)
    users = supabase.table("users").select("user_id, name").execute().data
    user_dict = {u["user_id"]: u["name"] for u in users}

    # Alle expenses ophalen
    expenses = supabase.table("expenses").select("*").eq("group_id", group_id).execute().data or []
    expense_ids = [e["expense_id"] for e in expenses]

    if not expense_ids:
        expense_ids = [-1]

    # Alle shares ophalen voor deze expenses
    shares = supabase.table("expense_shares") \
        .select("*") \
        .in_("expense_id", expense_ids) \
        .execute().data or []

    # App fee ophalen uit de groups-tabel
    group_list = supabase.table("groups").select("app_fee").eq("group_id", group_id).execute().data
    app_fee = float(group_list[0]["app_fee"]) if group_list and "app_fee" in group_list[0] else 0.0

    n_members = len(members)
    # Fee per persoon berekenen
    fee_per_person = round(app_fee / n_members, 2) if (app_fee > 0 and n_members > 0) else 0.0

    # Totaal betaald per persoon
    paid = {m["user_id"]: 0.0 for m in members}
    for exp in expenses:
        if exp["paid_by"] in paid:
            paid[exp["paid_by"]] += float(exp["total_amount"])

    # Totaal verschuldigd per persoon
    owed = {m["user_id"]: 0.0 for m in members}
    for share in shares:
        if share["user_id"] in owed:
            owed[share["user_id"]] += float(share["amount"])

    # Balansen berekenen (en fee direct tonen in het resultaat)
    balances = []
    for m in members:
        uid = m["user_id"]
        saldo = round(paid[uid] - owed[uid] - fee_per_person, 2)
        balances.append({
            "user_id": uid,
            "name": user_dict.get(uid, "Onbekend"),
            "saldo": saldo,
            "app_fee": fee_per_person  # Zo kun je direct op je balances.html laten zien: "Min app fee: € fee_per_person"
        })

    return balances

