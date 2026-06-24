import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from ..services.meeting_service import get_all_meetings, get_meeting_with_tasks
from ..services.task_service import get_task_stats, get_priority_tasks
from ..services.storage_service import upload_audio_to_storage
from ..utils.auth_middleware import login_required
from ..utils.supabase_client import get_supabase
from ..utils.role_middleware import role_required
from .meeting_routes import validate_audio_file

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
    file = request.files.get("audio")

    # Run upload validations
    val_error = validate_audio_file(file)
    if val_error:
        # If there's an error, we render the page with an error or return it.
        # To align with user experience, we can return a bad request or redirect with error.
        return jsonify({"error": val_error}), 400

    # Upload to Supabase Storage
    audio_url = upload_audio_to_storage(file)

    # Save meeting in DB
    supabase = get_supabase()

    recording_status = "uploaded"
    data = {
        "title": request.form.get("title"),
        "description": request.form.get("description"),
        "meeting_date": request.form.get("meeting_date"),
        "audio_url": audio_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "org_id": session["org_id"],
        "created_by": session["user_id"],
        "recording_status": recording_status,
        "processing_step": "uploaded",
        "processing_logs": ["upload_started", "upload_completed"],
        "processing_history": [{
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "event": "upload_completed",
            "message": "Audio file uploaded and validated successfully."
        }],
        "is_deleted": False,
        "deletion_queued": False
    }

    response = supabase.table("meetings").insert(data).execute()
    meeting_id = response.data[0]["id"]

    # Redirect immediately to the meeting details page without waiting for processing
    return redirect(url_for(
        "dashboard.meeting_detail",
        id=meeting_id
    ))

@dashboard_bp.route("/meeting/<id>")
@login_required
def meeting_detail(id):
    # Verify ownership inside service layer
    data = get_meeting_with_tasks(id)
    if not data or data.get("meeting") is None:
        return "Meeting not found", 404

    meeting = data["meeting"]
    tasks = data["tasks"]

    return render_template(
        "meeting_detail.html",
        meeting=meeting,
        transcript=meeting.get("transcript"),
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
        # Check if parent meeting is deleted.
        # (Though soft-delete sweeps tasks async, filters here act as safety guard).
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
    # Direct Python call to get statistics, avoiding loopback HTTP requests
    stats = get_task_stats()
    return render_template(
        "analytics.html",
        stats=stats
    )

@dashboard_bp.route("/add-meeting-link")
@login_required
def add_meeting_link_page():
    return render_template("add_meeting_link.html")
