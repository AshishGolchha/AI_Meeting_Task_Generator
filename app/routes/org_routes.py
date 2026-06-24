from flask import Blueprint, request, render_template, redirect, session
from ..services.org_service import invite_user, get_org_members
from ..utils.auth_middleware import login_required
from ..utils.supabase_client import get_supabase
from ..utils.role_middleware import role_required

org_bp = Blueprint(
    "org",
    __name__,
    template_folder="../templates"
)

@org_bp.route("/invite", methods=["GET", "POST"])
@login_required
@role_required(["owner","admin"])
def invite():
    if request.method == "GET":
        return render_template("invite_user.html")

    email = request.form.get("email")
    role = request.form.get("role")

    invite_user(email, role)

    return redirect("/dashboard")

@org_bp.route("/join/<invite_code>")
def join(invite_code):
    supabase = get_supabase()

    invite = supabase.table("org_invitations") \
        .select("*") \
        .eq("invite_code", invite_code) \
        .single() \
        .execute()

    if not invite.data:
        return "Invalid invite"

    return render_template(
        "join_org.html",
        invite_code=invite_code,
        email=invite.data["email"]
    )

@org_bp.route("/members")
@login_required
@role_required(["owner","admin"])
def members():
    org_id = session["org_id"]
    members = get_org_members(org_id)
    return render_template(
        "org_members.html",
        members=members
    )

@org_bp.route("/remove-user/<user_id>")
@login_required
@role_required(["owner","admin"])
def remove_user(user_id):
    supabase = get_supabase()
    org_id = session["org_id"]

    # BOLA Security check: Verify target user is in the same organization
    user_res = supabase.table("users") \
        .select("org_id") \
        .eq("id", user_id) \
        .execute()
        
    if not user_res.data or user_res.data[0].get("org_id") != org_id:
        return "Forbidden or user not found", 403

    # Remove organization reference
    supabase.table("users").update({
        "org_id": None
    }).eq("id", user_id).eq("org_id", org_id).execute()

    return redirect("/members")
