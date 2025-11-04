from flask import render_template, request, redirect, url_for, session, flash
from app import app
from app.models import get_user_by_name, create_user, get_user_groups, create_group, get_group_detail

# ------------------------------
# Hulpfunctie: login_required
# ------------------------------
def login_required(route_function):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Je moet eerst inloggen.")
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    wrapper.__name__ = route_function.__name__
    return wrapper

# ------------------------------
# LOGIN
# ------------------------------
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

# ------------------------------
# LOGOUT
# ------------------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Je bent uitgelogd.")
    return redirect(url_for("login"))

# ------------------------------
# GROEPEN
# ------------------------------
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

@app.route("/groups/<int:group_id>")
@login_required
def group_detail(group_id):
    group, members = get_group_detail(group_id)
    if not group:
        flash("Groep niet gevonden.")
        return redirect(url_for("groups_list"))
    return render_template("group_detail.html", group=group, members=members)

# ------------------------------
# STARTPAGINA
# ------------------------------
@app.route("/")
def index():
    return redirect(url_for("login"))
