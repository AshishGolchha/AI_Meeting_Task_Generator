from flask import Blueprint, request, jsonify, send_file, session
from ..services.storage_service import upload_audio_to_storage
from ..services.speech_service import transcribe_audio
from ..services.llm_service import extract_tasks_from_transcript
from ..services.task_service import save_tasks
from ..services.meeting_service import get_meeting_with_tasks
from ..services.pdf_service import generate_mom_pdf
from ..utils.supabase_client import get_supabase
from ..utils.auth_middleware import login_required
from ..services.recording_fetch_service import process_pending_recordings
import datetime

meeting_bp = Blueprint("meetings", __name__)

@meeting_bp.route("/upload", methods=["POST"])
@login_required
def upload_meeting():

    title = request.form.get("title")
    description = request.form.get("description")
    meeting_date = request.form.get("meeting_date")

    file = request.files.get("audio")

    if not file:
        return jsonify({"error": "Audio file required"}), 400

    # Upload to Supabase Storage
    audio_url = upload_audio_to_storage(file)

    # Save meeting in DB
    supabase = get_supabase()

    data = {
        "title": title,
        "description": description,
        "meeting_date": meeting_date,
        "audio_url": audio_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "org_id": session["org_id"],
        "created_by": session["user_id"]
    }

    response = supabase.table("meetings").insert(data).execute()

    return jsonify({
        "message": "Meeting uploaded successfully",
        "meeting": response.data
    })

@meeting_bp.route("/process/<meeting_id>", methods=["POST"])
@login_required
def process_meeting(meeting_id):

    supabase = get_supabase()

    # 1️⃣ Get meeting
    meeting_res = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .single() \
        .execute()

    meeting = meeting_res.data
    audio_url = meeting["audio_url"]

    # 2️⃣ Speech → Text
    transcript = transcribe_audio(audio_url)

    # Save transcript
    supabase.table("meetings").update({
        "transcript": transcript
    }).eq("id", meeting_id).execute()

    # 3️⃣ AI Extraction
    ai_data = extract_tasks_from_transcript(transcript)

    summary = ai_data.get("summary")
    tasks = ai_data.get("tasks", [])

    # Save summary
    supabase.table("meetings").update({
        "summary": summary
    }).eq("id", meeting_id).execute()

    # 4️⃣ Save Tasks
    inserted_tasks = save_tasks(
        meeting_id,
        tasks,
        org_id=meeting["org_id"]
    )

    return jsonify({
        "summary": summary,
        "tasks": inserted_tasks
    })

@meeting_bp.route("/<meeting_id>", methods=["GET"])
@login_required
def get_meeting_details(meeting_id):

    data = get_meeting_with_tasks(meeting_id)

    return jsonify(data)

@meeting_bp.route("/retry-ai/<meeting_id>", methods=["POST"])
@login_required
def retry_ai(meeting_id):

    supabase = get_supabase()

    meeting = supabase.table("meetings") \
        .select("transcript") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .single() \
        .execute()

    transcript = meeting.data["transcript"]

    from ..services.llm_service import extract_tasks_from_transcript
    from ..services.task_service import save_tasks

    ai_data = extract_tasks_from_transcript(transcript)

    tasks = ai_data.get("tasks", [])

    inserted = save_tasks(
        meeting_id,
        tasks,
        org_id=session["org_id"]
    )

    return jsonify(inserted)

@meeting_bp.route("/<meeting_id>/transcript", methods=["PUT"])
@login_required
def update_transcript(meeting_id):

    transcript = request.json.get("transcript")

    supabase = get_supabase()

    supabase.table("meetings").update({
        "transcript": transcript
    }).eq("id", meeting_id).execute()

    return jsonify({"message": "Transcript updated"})

@meeting_bp.route("/<meeting_id>/export", methods=["GET"])
@login_required
def export_mom(meeting_id):

    data = get_meeting_with_tasks(meeting_id)

    pdf_path = generate_mom_pdf(
        data["meeting"],
        data["tasks"]
    )

    return send_file(pdf_path, as_attachment=True)

@meeting_bp.route("/add-link", methods=["POST"])
@login_required
def add_meeting_link():

    data = request.json

    if not data:
        return jsonify({"error": "Invalid request"}), 400

    title = data.get("title")
    meeting_link = data.get("meeting_link")
    meeting_date = data.get("meeting_date")

    if not meeting_link:
        return jsonify({"error": "Meeting link required"}), 400

    supabase = get_supabase()

    meeting_data = {
        "title": title,
        "meeting_link": meeting_link,
        "meeting_date": meeting_date,
        "org_id": session["org_id"],
        "created_by": session["user_id"],
        "recording_status": "pending"
    }

    res = supabase.table("meetings").insert(meeting_data).execute()

    return jsonify({
        "message": "Meeting link added",
        "meeting": res.data
    })

@meeting_bp.route("/fetch-recordings", methods=["POST"])
# @login_required
def fetch_recordings():

    process_pending_recordings()

    return jsonify({
        "message": "Recording fetch triggered"
    })
