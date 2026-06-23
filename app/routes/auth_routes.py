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


@auth_bp.route("/api/auth/google")
def google_auth():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
        
    state = secrets.token_urlsafe(16)
    session["google_oauth_state"] = state
    
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    redirect_uri = current_app.config["GOOGLE_REDIRECT_URI"]
    scope = "https://www.googleapis.com/auth/drive.readonly"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }
    
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(auth_url)


@auth_bp.route("/api/auth/google/callback")
def google_auth_callback():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
        
    state = request.args.get("state")
    saved_state = session.pop("google_oauth_state", None)
    
    if not state or state != saved_state:
        return "CSRF verification failed. State mismatch.", 400
        
    code = request.args.get("code")
    if not code:
        return "Authorization code missing.", 400
        
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    client_secret = current_app.config["GOOGLE_CLIENT_SECRET"]
    redirect_uri = current_app.config["GOOGLE_REDIRECT_URI"]
    
    # Exchange code for token
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    res = requests.post(token_url, data=data)
    if res.status_code != 200:
        return f"Failed to exchange authorization code: {res.text}", 400
        
    token_data = res.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    
    # Calculate expiry
    expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)).isoformat()
    
    # Update user in DB
    supabase = get_supabase()
    
    update_data = {
        "google_access_token": access_token,
        "google_token_expiry": expiry,
        "google_connected": True
    }
    if refresh_token:
        update_data["google_refresh_token"] = refresh_token
        
    supabase.table("users").update(update_data).eq("id", session["user_id"]).execute()
    
    return redirect("/dashboard")


@auth_bp.route("/api/auth/google/disconnect", methods=["POST"])
def google_auth_disconnect():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    supabase = get_supabase()
    
    res = supabase.table("users") \
        .select("google_access_token") \
        .eq("id", session["user_id"]) \
        .single() \
        .execute()
        
    user = res.data
    if user and user.get("google_access_token"):
        try:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": user["google_access_token"]},
                timeout=10
            )
        except Exception as e:
            print(f"Failed to revoke Google token: {e}")
            
    # Clear fields in DB
    supabase.table("users").update({
        "google_access_token": None,
        "google_refresh_token": None,
        "google_token_expiry": None,
        "google_connected": False
    }).eq("id", session["user_id"]).execute()
    
    return redirect("/dashboard")
