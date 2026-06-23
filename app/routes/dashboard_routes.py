import requests
from flask import Blueprint, render_template, request, redirect, url_for, session
from ..services.meeting_service import get_all_meetings
from ..services.task_service import get_task_stats, get_priority_tasks
from ..utils.auth_middleware import login_required
from ..utils.supabase_client import get_supabase
from ..utils.role_middleware import role_required

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="../templates"
)

@dashboard_bp.route("/")
def home():
    return render_template("home.html")

@dashboard_bp.route("/dashboard")
@login_required
def dashboard():

    meetings = get_all_meetings()
    stats = get_task_stats()
    priority_tasks = get_priority_tasks()

    return render_template(
        "dashboard.html",
        meetings=meetings,
        stats=stats,
        priority_tasks=priority_tasks
    )

@dashboard_bp.route("/upload", methods=["GET"])
@login_required
def upload_page():
    return render_template("upload.html")

@dashboard_bp.route("/upload", methods=["POST"])
@login_required
def upload_meeting():

    file = request.files["audio"]

    data = {
        "title": request.form.get("title"),
        "description": request.form.get("description"),
        "meeting_date": request.form.get("meeting_date"),
    }

    files = {
        "audio": (file.filename, file.stream, file.mimetype)
    }

    # 1️⃣ Upload meeting
    res = requests.post(
    "http://127.0.0.1:5000/api/meetings/upload",
    data=data,
    files=files,
    cookies=request.cookies
    )

    meeting = res.json()["meeting"][0]
    meeting_id = meeting["id"]

    # 2️⃣ Process AI
    requests.post(
    f"http://127.0.0.1:5000/api/meetings/process/{meeting_id}",
    cookies=request.cookies
    )

    return redirect(url_for(
        "dashboard.meeting_detail",
        id=meeting_id
    ))

@dashboard_bp.route("/meeting/<id>")
@login_required
def meeting_detail(id):

    res = requests.get(
        f"http://127.0.0.1:5000/api/meetings/{id}",
        cookies=request.cookies
    )

    data = res.json()

    meeting = data["meeting"]
    tasks = data["tasks"]

    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        transcript=meeting["transcript"],
        tasks=tasks,
        meeting_id=id
    )

@dashboard_bp.route("/kanban")
@login_required
def kanban():

    supabase = get_supabase()

    tasks_res = supabase.table("tasks") \
        .select("*") \
        .eq("org_id", session["org_id"]) \
        .execute()

    tasks = tasks_res.data

    pending = []
    progress = []
    completed = []

    for t in tasks:

        if t["status"] == "pending":
            pending.append(t)

        elif t["status"] == "in_progress":
            progress.append(t)

        elif t["status"] == "completed":
            completed.append(t)

    return render_template(
        "kanban.html",
        pending=pending,
        progress=progress,
        completed=completed
    )

@dashboard_bp.route("/analytics")
@login_required
@role_required(["owner","admin"])
def analytics():

    res = requests.get(
        "http://127.0.0.1:5000/api/analytics/task-stats",
        cookies=request.cookies
    )

    stats = res.json()

    return render_template(
        "analytics.html",
        stats=stats
    )

@dashboard_bp.route("/add-meeting-link")
@login_required
def add_meeting_link_page():
    return render_template("add_meeting_link.html")
