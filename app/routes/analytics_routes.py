from flask import Blueprint, jsonify
from ..utils.supabase_client import get_supabase

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/task-stats")
def stats():

    supabase = get_supabase()

    tasks = supabase.table("tasks").select("status").execute()

    stats = {
        "total": len(tasks.data),
        "completed": 0,
        "pending": 0,
        "overdue": 0
    }

    for t in tasks.data:

        if t["status"] == "completed":
            stats["completed"] += 1

        elif t["status"] == "pending":
            stats["pending"] += 1

    return stats

