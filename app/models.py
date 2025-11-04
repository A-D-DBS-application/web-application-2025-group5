from app import supabase

# -------------------------
# USERS
# -------------------------
def get_user_by_name(username):
    return supabase.table("users").select("*").eq("name", username).execute().data

def create_user(username):
    return supabase.table("users").insert({"name": username}).execute().data[0]

# -------------------------
# GROUPS
# -------------------------
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

def get_group_detail(group_id):
    group = supabase.table("groups").select("*").eq("group_id", group_id).execute().data
    members = supabase.table("group_members").select("*, users(*)").eq("group_id", group_id).execute().data
    return (group[0] if group else None, members)
