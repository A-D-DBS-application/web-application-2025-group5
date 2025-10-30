#hart van de app
from flask import Flask, render_template, request, redirect, url_for, session, flash
from supabase import create_client
from dotenv import load_dotenv
import os

# ------------------------------
# Laad variabelen uit .env
# ------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "fallback-secret")

# Maak verbinding met Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialiseer Flask-app
app = Flask(__name__)
app.secret_key = SECRET_KEY


# ------------------------------
# Hulpfunctie: login_required
# ------------------------------
def login_required(route_function):
    """Decorator: blokkeer toegang tot routes als user niet is ingelogd."""
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Je moet eerst inloggen.")
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    wrapper.__name__ = route_function.__name__
    return wrapper


# ------------------------------
# LOGIN (enkel username)
# ------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()

        # als niets ingevuld werd
        if not username:
            flash("Vul een gebruikersnaam in.")
            return redirect(url_for("login"))

        # bestaat user al?
        result = supabase.table("users").select("*").eq("name", username).execute()

        if result.data:
            user = result.data[0]
        else:
            # nieuwe gebruiker aanmaken
            user = supabase.table("users").insert({"name": username}).execute().data[0]

        # gegevens in session steken (soort mini-login)
        session["user_id"] = user["user_id"]
        session["username"] = user["name"]

        return redirect(url_for("groups_list"))

    return render_template("login.html")


# ------------------------------
# LOGOUT
# ------------------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.")
    return redirect(url_for("login"))


# ------------------------------
# LIJST VAN GROEPEN
# ------------------------------
@app.route("/groups")
@login_required
def groups_list():
    user_id = session["user_id"]
    result = supabase.rpc("get_user_groups", {"uid": user_id}).execute()
    groups = result.data if result.data else []
    return render_template("groups_list.html", groups=groups)


# ------------------------------
# GROEP AANMAKEN
# ------------------------------
@app.route("/groups/create", methods=["GET", "POST"])
@login_required
def groups_create():
    if request.method == "POST":
        name = request.form["name"].strip()
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        organizer_id = session["user_id"]

        # nieuwe groep opslaan
        group = supabase.table("groups").insert({
            "name": name,
            "start_date": start_date,
            "end_date": end_date,
            "organizer_id": organizer_id
        }).execute().data[0]

        # organizer ook als lid toevoegen
        supabase.table("group_members").insert({
            "group_id": group["group_id"],
            "user_id": organizer_id,
            "role": "organizer"
        }).execute()

        return redirect(url_for("groups_list"))

    return render_template("groups_create.html")


# ------------------------------
# GROEPDETAIL
# ------------------------------
@app.route("/groups/<int:group_id>")
@login_required
def group_detail(group_id):
    group = supabase.table("groups").select("*").eq("group_id", group_id).execute().data
    if not group:
        flash("Groep niet gevonden.")
        return redirect(url_for("groups_list"))

    group = group[0]
    members = supabase.table("group_members").select("*, users(*)").eq("group_id", group_id).execute().data
    return render_template("group_detail.html", group=group, members=members)


# ------------------------------
# STARTPAGINA
# ------------------------------
@app.route("/")
def index():
    return redirect(url_for("login"))


# ------------------------------
# START DE SERVER
# ------------------------------
if __name__ == "__main__":
    app.run(debug=True)
