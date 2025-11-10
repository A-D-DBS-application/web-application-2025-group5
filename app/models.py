from supabase import create_client
import os
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_user_by_name(username):
    return supabase.table("users").select("*").eq("name", username).execute().data

def create_user(username):
    return supabase.table("users").insert({"name": username}).execute().data[0]

def get_user_groups(user_id):
    result = supabase.rpc("get_user_groups", {"uid": user_id}).execute()
    return result.data if result.data else []

def create_group(name, start_date, end_date, organizer_id):
    group = supabase.table("groups").insert({
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "organizer_id": organizer_id
    }).execute().data[0]
    supabase.table("group_members").insert({
        "group_id": group["group_id"],
        "user_id": organizer_id,
        "role": "organizer"
    }).execute()
    return group

def get_group_members(group_id):
    return supabase.table('group_members').select('*').eq('group_id', group_id).execute().data

def get_group_detail(group_id):
    group = supabase.table('groups').select('*').eq('group_id', group_id).execute().data
    members = supabase.table('group_members').select('*, users(*)').eq('group_id', group_id).execute().data
    return (group[0] if group else None), members


def add_expense(group_id, paid_by, description, total_amount, shares_dict):
    expense = supabase.table("expenses").insert({
        "group_id": group_id,
        "paid_by": paid_by,
        "description": description,
        "total_amount": total_amount
    }).execute().data[0]
    for user_id, amount in shares_dict.items():
        try:
            supabase.table("expense_shares").insert({
                "expense_id": expense["expense_id"],
                "user_id": user_id,
                "amount": amount,
                "item_id": expense["expense_id"]  # Zet item_id = expense_id
            }).execute()
        except Exception as e:
            print(f"FOUT bij expense_shares insert: {e}", flush=True)


def get_balances_for_group(group_id):
    members = supabase.table('group_members').select('user_id').eq('group_id', group_id).execute().data
    users = supabase.table('users').select('user_id,name').execute().data
    user_dict = {u['user_id']: u['name'] for u in users}
    expenses = supabase.table('expenses').select('*').eq('group_id', group_id).execute().data or []
    expense_ids = [e['expense_id'] for e in expenses]
    if not expense_ids:
        expense_ids = [-1]
    shares = supabase.table('expense_shares').select('*').in_('expense_id', expense_ids).execute().data or []
    paid = {m['user_id']: 0 for m in members}
    owed = {m['user_id']: 0 for m in members}
    for exp in expenses:
        if exp['paid_by'] in paid:
            paid[exp['paid_by']] += float(exp['total_amount'])
    for share in shares:
        if share['user_id'] in owed:
            owed[share['user_id']] += float(share['amount'])
    balances = []
    for user in members:
        saldo = round(paid[user['user_id']] - owed[user['user_id']], 2)
        balances.append({'user_id': user['user_id'], 'name': user_dict.get(user['user_id'], '?'), 'saldo': saldo})
    return balances
