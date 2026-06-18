from supabase import create_client
from flask import current_app

def get_supabase():

    url = current_app.config["SUPABASE_URL"]
    key = current_app.config["SUPABASE_SERVICE_KEY"]

    supabase = create_client(url, key)

    return supabase