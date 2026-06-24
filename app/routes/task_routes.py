from flask import Blueprint, jsonify, request, session
from ..utils.supabase_client import get_supabase
from ..utils.auth_middleware import login_required

task_bp = Blueprint("tasks", __name__)

@task_bp.route("/", methods=["GET"])
@login_required
def get_tasks():
    supabase = get_supabase()

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .order("created_at", desc=True) \
        .execute()

    return jsonify(tasks.data)

@task_bp.route("/filter", methods=["GET"])
@login_required
def filter_tasks():
    priority = request.args.get("priority")
    status = request.args.get("status")

    supabase = get_supabase()

    query = supabase.table("tasks") \
        .select("*") \
        .eq("org_id", session["org_id"])

    if priority:
        query = query.eq("priority", priority)

    if status:
        query = query.eq("status", status)

    tasks = query.execute()

    return jsonify(tasks.data)

@task_bp.route("/<task_id>/status", methods=["PUT"])
@login_required
def update_task_status(task_id):
    status = request.json.get("status")

    supabase = get_supabase()

    # BOLA Check: update filters by org_id
    updated = supabase.table("tasks").update({
        "status": status
    }).eq("id", task_id) \
    .eq("org_id", session["org_id"]) \
    .execute()

    if not updated.data:
        return jsonify({"error": "Task not found or forbidden"}), 404

    return jsonify({
        "message": "Task status updated",
        "task": updated.data[0]
    })

@task_bp.route("/<task_id>/assign", methods=["PUT"])
@login_required
def assign_task(task_id):
    user_id = request.json.get("user_id")

    supabase = get_supabase()

    # BOLA Check: update filters by org_id
    updated = supabase.table("tasks").update({
        "assigned_to": user_id
    }).eq("id", task_id) \
    .eq("org_id", session["org_id"]) \
    .execute()

    if not updated.data:
        return jsonify({"error": "Task not found or forbidden"}), 404

    return jsonify({
        "message": "Task assigned",
        "task": updated.data[0]
    })

@task_bp.route("/<task_id>/deadline", methods=["PUT"])
@login_required
def update_deadline(task_id):
    deadline = request.json.get("deadline")

    supabase = get_supabase()

    # BOLA Check: update filters by org_id
    updated = supabase.table("tasks").update({
        "deadline": deadline
    }).eq("id", task_id) \
    .eq("org_id", session["org_id"]) \
    .execute()

    if not updated.data:
        return jsonify({"error": "Task not found or forbidden"}), 404

    return jsonify(updated.data[0])