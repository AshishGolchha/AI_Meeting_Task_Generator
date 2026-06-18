from ..utils.supabase_client import get_supabase
from flask import session

def get_meeting_with_tasks(meeting_id):

    supabase = get_supabase()

    meeting = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .single() \
        .execute()

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("meeting_id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .execute()

    return {
        "meeting": meeting.data,
        "tasks": tasks.data
    }

def get_all_meetings():

    supabase = get_supabase()

    meetings = supabase.table("meetings") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .order("created_at", desc=True) \
        .execute()

    return meetings.data