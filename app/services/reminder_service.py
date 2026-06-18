from datetime import date
from ..utils.supabase_client import get_supabase
from .notification_service import send_task_email


def send_deadline_reminders():

    today = date.today()

    supabase = get_supabase()

    tasks = supabase.table("tasks") \
        .select("*") \
        .eq("status", "pending") \
        .execute()

    for task in tasks.data:

        if task["deadline"] == str(today):

            user = supabase.table("users") \
                .select("email") \
                .eq("id", task["assigned_to"]) \
                .single() \
                .execute()

            send_task_email(
                user.data["email"],
                task["title"],
                task["deadline"]
            )
