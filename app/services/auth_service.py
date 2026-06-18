from ..utils.supabase_client import get_supabase
from ..utils.password_utils import (
    hash_password,
    verify_password
)
import uuid


# ===============================
# REGISTER OWNER
# ===============================

def register_owner(name, email, password, org_name):

    supabase = get_supabase()

    # 1️⃣ Create organization
    org = supabase.table("organizations").insert({
        "name": org_name
    }).execute()

    org_id = org.data[0]["id"]

    # 2️⃣ Hash password
    hashed_password = hash_password(password)

    # 3️⃣ Create user
    user = supabase.table("users").insert({
        "id": str(uuid.uuid4()),
        "name": name,
        "email": email,
        "password": hashed_password,
        "org_id": org_id,
        "role": "owner"
    }).execute()

    return user.data[0]


# ===============================
# LOGIN
# ===============================

def login_user(email, password):

    supabase = get_supabase()

    user = supabase.table("users") \
        .select("*") \
        .eq("email", email) \
        .single() \
        .execute()

    if not user.data:
        return None

    valid = verify_password(
        password,
        user.data["password"]
    )

    if not valid:
        return None

    return user.data
