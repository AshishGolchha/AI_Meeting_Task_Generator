from ..utils.supabase_client import get_supabase
from flask import session
import datetime

def get_meeting_with_tasks(meeting_id):
    supabase = get_supabase()

    # Query without single() to avoid throwing exception on missing record
    meeting_res = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()

    if not meeting_res.data:
        return {
            "meeting": None,
            "tasks": []
        }

    meeting = meeting_res.data[0]

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("meeting_id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .execute()

    return {
        "meeting": meeting,
        "tasks": tasks.data
    }

def get_all_meetings():
    supabase = get_supabase()

    meetings = supabase.table("meetings") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .order("created_at", desc=True) \
        .execute()

    return meetings.data

def soft_delete_meeting(meeting_id, org_id):
    supabase = get_supabase()

    # 1. Verify existence and ownership
    meeting_res = supabase.table("meetings") \
        .select("id") \
        .eq("id", meeting_id) \
        .eq("org_id", org_id) \
        .eq("is_deleted", False) \
        .execute()

    if not meeting_res.data:
        return False

    # 2. Mark as soft-deleted
    now = datetime.datetime.now(datetime.timezone.utc)
    supabase.table("meetings").update({
        "is_deleted": True,
        "deletion_queued": True,
        "deleted_at": now.isoformat()
    }).eq("id", meeting_id).eq("org_id", org_id).execute()

    return True
