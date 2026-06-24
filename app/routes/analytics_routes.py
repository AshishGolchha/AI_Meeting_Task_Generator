from flask import Blueprint, jsonify, session
from ..utils.supabase_client import get_supabase
from ..utils.auth_middleware import login_required

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/task-stats")
@login_required
def stats():
    supabase = get_supabase()

    # BOLA Security fix: Filter by user's organization id
    tasks = supabase.table("tasks") \
        .select("status") \
        .eq("org_id", session["org_id"]) \
        .execute()

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

    return jsonify(stats)
