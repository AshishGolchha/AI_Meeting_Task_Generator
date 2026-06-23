from ..utils.supabase_client import get_supabase
from .notification_service import send_task_email
from flask import session
import datetime


# ==========================================
# SAVE TASKS
# ==========================================
def save_tasks(meeting_id, tasks, org_id):

    supabase = get_supabase()

    # Delete existing tasks for same meeting_id to prevent duplicates
    try:
        supabase.table("tasks").delete().eq("meeting_id", meeting_id).execute()
        print(f"Deleted existing tasks for meeting {meeting_id} to prevent duplication.")
    except Exception as e:
        print(f"Error deleting tasks for meeting {meeting_id}: {e}")

    inserted_tasks = []

    for task in tasks:

        # Map assignee name → user_id
        user_id = map_assignee_to_user(
            task.get("assigned_to"),
            org_id=org_id
        )

        data = {
            "meeting_id": meeting_id,
            "org_id": org_id,
            "title": task.get("title"),
            "description": task.get("description"),
            "assigned_to": user_id,
            "deadline": task.get("deadline"),
            "priority": task.get("priority", "medium"),
            "status": "pending"
        }

        response = supabase.table("tasks").insert(data).execute()

        inserted_task = response.data[0]

        # ==================================
        # SEND EMAIL (if user mapped)
        # ==================================
        if user_id:

            user = supabase.table("users") \
                .select("email") \
                .eq("id", user_id) \
                .single() \
                .execute()

            if user.data:

                email = user.data["email"]

                send_task_email(
                    email,
                    inserted_task["title"],
                    inserted_task["deadline"]
                )

        inserted_tasks.append(inserted_task)

    return inserted_tasks


# ==========================================
# MAP ASSIGNEE NAME → USER ID
# ==========================================
def map_assignee_to_user(name, org_id=None):

    if not name:
        return None

    supabase = get_supabase()

    target_org_id = org_id
    if not target_org_id:
        try:
            target_org_id = session.get("org_id")
        except:
            pass

    if not target_org_id:
        return None

    users = supabase.table("users") \
        .select("id,name") \
        .eq("org_id", target_org_id) \
        .execute()

    for user in users.data:

        if user["name"].lower() in name.lower():
            return user["id"]

    return None


# ==========================================
# TASK STATS
# ==========================================
def get_task_stats():

    supabase = get_supabase()

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .execute()

    data = tasks.data

    stats = {
        "total": len(data),
        "completed": 0,
        "pending": 0,
        "in_progress": 0,
        "overdue": 0
    }

    today = datetime.date.today()

    for t in data:

        # Status counts
        if t["status"] == "completed":
            stats["completed"] += 1

        elif t["status"] == "pending":
            stats["pending"] += 1

        elif t["status"] == "in_progress":
            stats["in_progress"] += 1

        # Overdue logic
        if t["deadline"] and t["status"] != "completed":

            try:
                deadline = datetime.datetime.strptime(
                    t["deadline"],
                    "%Y-%m-%d"
                ).date()

                if deadline < today:
                    stats["overdue"] += 1

            except:
                pass

    return stats


# ==========================================
# PRIORITY TASKS
# ==========================================
def get_priority_tasks(limit=5):

    supabase = get_supabase()

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .execute()

    data = tasks.data

    # Manual priority sorting
    priority_order = {
        "high": 3,
        "medium": 2,
        "low": 1
    }

    sorted_tasks = sorted(
        data,
        key=lambda x: priority_order.get(
            x["priority"], 0
        ),
        reverse=True
    )

    return sorted_tasks[:limit]
