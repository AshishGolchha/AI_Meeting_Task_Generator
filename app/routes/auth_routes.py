from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template, current_app
from ..services.auth_service import (
    register_owner,
    login_user
)
from ..utils.supabase_client import get_supabase
from ..utils.password_utils import hash_password
import uuid
import secrets
import urllib.parse
import requests
import datetime

auth_bp = Blueprint(
    "auth",
    __name__,
    template_folder="../templates"
)

@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    data = request.form

    invite_code = data.get("invite_code")

    # ===============================
    # CASE 1 → INVITE REGISTER
    # ===============================
    if invite_code:

        supabase = get_supabase()

        invite = supabase.table("org_invitations") \
            .select("*") \
            .eq("invite_code", invite_code) \
            .eq("status", "pending") \
            .single() \
            .execute()

        if not invite.data:
            return "Invalid or expired invite"

        org_id = invite.data["org_id"]
        role = invite.data["role"]

        # Create user
        user_data = {
            "id": str(uuid.uuid4()),
            "name": data["name"],
            "email": data["email"],
            "password": hash_password(data["password"]),
            "org_id": org_id,
            "role": role
        }

        user = supabase.table("users").insert(user_data).execute()

        # Mark invite accepted
        supabase.table("org_invitations").update({
            "status": "accepted"
        }).eq("invite_code", invite_code).execute()

        user = user.data[0]

    # ===============================
    # CASE 2 → OWNER REGISTER
    # ===============================
    else:

        user = register_owner(
            name=data["name"],
            email=data["email"],
            password=data["password"],
            org_name=data["org_name"]
        )

    session["user_id"] = user["id"]
    session["org_id"] = user["org_id"]
    session["role"] = user["role"]

    if user["role"] == "owner":
        return redirect("/invite")

    # Invited users → Dashboard
    return redirect("/dashboard")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session:
        return redirect("/dashboard")

    if request.method == "GET":
        return render_template("login.html")

    data = request.form

    user = login_user(
        email=data["email"],
        password=data["password"]
    )

    if not user:
        return render_template(
            "login.html",
            error="Invalid email or password"
        )

    session["user_id"] = user["id"]
    session["org_id"] = user["org_id"]
    session["role"] = user["role"]

    return redirect("/dashboard")

@auth_bp.route("/logout")
def logout():

    session.clear()

    return redirect("/")
