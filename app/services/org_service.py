import uuid
from ..utils.supabase_client import get_supabase
from .email_service import send_invite_email
from flask import session
import os


def invite_user(email, role):

    supabase = get_supabase()

    invite_code = str(uuid.uuid4())

    org_id = session["org_id"]

    # Get org name
    org = supabase.table("organizations") \
        .select("name") \
        .eq("id", org_id) \
        .single() \
        .execute()

    org_name = org.data["name"]

    # Save invite
    supabase.table("org_invitations").insert({
        "org_id": org_id,
        "email": email,
        "role": role,
        "invite_code": invite_code,
        "status": "pending"
    }).execute()

    invite_link = f"{os.getenv('APP_BASE_URL')}/join/{invite_code}"

    send_invite_email(
        email,
        invite_link,
        org_name
    )

    return invite_link

def get_org_members(org_id):

    supabase = get_supabase()

    members = supabase.table("users") \
        .select("*") \
        .eq("org_id", org_id) \
        .order("created_at") \
        .execute()

    return members.data
