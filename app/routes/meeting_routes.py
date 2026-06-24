import datetime
import io
import os

from flask import Blueprint, request, jsonify, send_file, session
from google import genai
from ..services.storage_service import upload_audio_to_storage
from ..services.speech_service import transcribe_audio, PartialTranscriptionError
from ..services.llm_service import extract_tasks_from_transcript
from ..services.task_service import save_tasks
from ..services.meeting_service import get_meeting_with_tasks, soft_delete_meeting
from ..services.pdf_service import generate_mom_pdf
from ..utils.supabase_client import get_supabase
from ..utils.auth_middleware import login_required

meeting_bp = Blueprint("meetings", __name__)

VALID_STATUSES = {
    "pending",
    "uploaded",
    "transcribing",
    "extracting_tasks",
    "completed",
    "failed"
}

def update_status(meeting_id, status, org_id):
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid meeting status: {status}")

    supabase = get_supabase()
    return supabase.table("meetings").update({
        "recording_status": status
    }).eq("id", meeting_id).eq("org_id", org_id).execute()


def _trim_processing_metadata(logs, history):
    return (logs or [])[-100:], (history or [])[-100:]

def validate_audio_file(file):
    if not file:
        return "Audio file required"
        
    # 1. Size Validation (100MB limit)
    file.seek(0, io.SEEK_END)
    size = file.tell()
    file.seek(0)  # Reset pointer
    
    if size == 0:
        return "Audio file is empty"
        
    max_size = 100 * 1024 * 1024  # 100MB
    if size > max_size:
        return f"Audio file exceeds maximum allowed limit of 100MB (uploaded: {size / (1024*1024):.2f}MB)"
        
    # 2. Magic Bytes Signature Check
    header = file.read(64)
    file.seek(0)  # Reset pointer
    content_type = (getattr(file, "content_type", None) or getattr(file, "mimetype", None) or "").lower()
    
    is_valid_format = False
    
    # WebM
    if header.startswith(b'\x1a\x45\xdf\xa3') and (
        "webm" in content_type or b"webm" in header.lower() or header[4:64].find(b"\x42\x86") != -1
    ):
        is_valid_format = True
    # MP3 (ID3v2)
    elif header.startswith(b'ID3'):
        is_valid_format = True
    # MP3 (Raw Frame Sync)
    elif len(header) >= 2 and header[0] == 0xff and (header[1] & 0xe0) == 0xe0:
        is_valid_format = True
    # WAV
    elif header.startswith(b'RIFF') and len(header) >= 12 and header[8:12] == b'WAVE':
        is_valid_format = True
        
    if not is_valid_format:
        return "Unsupported audio format. Only WebM, MP3, and WAV files are allowed."
        
    return None

@meeting_bp.route("/upload", methods=["POST"])
@login_required
def upload_meeting():
    title = request.form.get("title")
    description = request.form.get("description")
    meeting_date = request.form.get("meeting_date")

    file = request.files.get("audio")

    # Run upload validations
    val_error = validate_audio_file(file)
    if val_error:
        return jsonify({"error": val_error}), 400

    # Upload to Supabase Storage
    audio_url = upload_audio_to_storage(file)

    # Save meeting in DB
    supabase = get_supabase()

    recording_status = "uploaded"
    data = {
        "title": title,
        "description": description,
        "meeting_date": meeting_date,
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

    return jsonify({
        "message": "Meeting uploaded successfully",
        "meeting": response.data
    })

@meeting_bp.route("/process/<meeting_id>", methods=["POST"])
@login_required
def process_meeting(meeting_id):
    supabase = get_supabase()

    # Get meeting (mitigating BOLA by checking org_id)
    meeting_res = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()

    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    meeting = meeting_res.data[0]
    
    # Check if already completed
    status = meeting.get("recording_status")
    if status == "completed":
        return jsonify({"message": "Meeting already processed"}), 200

    # In DBQ architecture, we simply mark it as 'uploaded' and reset status/locks.
    # The asynchronous background polling worker will automatically fetch it and process it atomically.
    now = datetime.datetime.utcnow().isoformat()
    history = meeting.get("processing_history") or []
    history.append({
        "timestamp": now,
        "event": "processing_queued",
        "message": "Background processing task queued."
    })
    _, history = _trim_processing_metadata(None, history)
    
    supabase.table("meetings").update({
        "recording_status": "uploaded",
        "processing_step": "uploaded",
        "processing_lock": False,
        "processing_started_at": None,
        "processing_error": None,
        "processing_history": history
    }).eq("id", meeting_id).eq("org_id", session["org_id"]).execute()

    return jsonify({"message": "Processing queued successfully", "meeting_id": meeting_id}), 202

@meeting_bp.route("/<meeting_id>/status", methods=["GET"])
@login_required
def get_meeting_status(meeting_id):
    supabase = get_supabase()
    
    # Query ONLY required status fields to minimize performance/db load (No transcript/summary)
    meeting_res = supabase.table("meetings") \
        .select("recording_status, processing_step, processing_error") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()
        
    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404
        
    meeting = meeting_res.data[0]
    
    # Calculate progress percentage dynamically
    status = meeting.get("recording_status")
    step = meeting.get("processing_step")
    
    progress = 0
    if status == "completed":
        progress = 100
    elif status == "failed":
        progress = 0
    elif status == "uploaded":
        progress = 10
    elif status == "transcribing" or step == "transcribing":
        progress = 40
    elif status == "extracting_tasks" or step == "extracting_tasks":
        progress = 80
        
    return jsonify({
        "recording_status": status,
        "processing_step": step,
        "processing_error": meeting.get("processing_error"),
        "progress_percentage": progress
    })

@meeting_bp.route("/health", methods=["GET"])
def health_check():
    health = {
        "status": "healthy",
        "flask": "running",
        "supabase": "disconnected",
        "gemini": "unconfigured"
    }

    try:
        supabase = get_supabase()
        supabase.table("organizations").select("id").limit(1).execute()
        health["supabase"] = "reachable"
    except Exception as e:
        health["status"] = "unhealthy"
        health["supabase"] = f"error: {str(e)}"

    try:
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise Exception("missing_api_key")

        client = genai.Client(api_key=gemini_key)
        probe = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Reply with OK."
        )

        if not getattr(probe, "text", None):
            raise Exception("empty_gemini_response")

        health["gemini"] = "reachable"
    except Exception as e:
        health["status"] = "unhealthy"
        health["gemini"] = f"error: {str(e)}"

    status_code = 200 if health["status"] == "healthy" else 500
    return jsonify(health), status_code

@meeting_bp.route("/<meeting_id>", methods=["GET"])
@login_required
def get_meeting_details(meeting_id):
    # Verify ownership inside service layer
    data = get_meeting_with_tasks(meeting_id)
    if not data or data.get("meeting") is None:
        return jsonify({"error": "Meeting not found"}), 404

    return jsonify(data)

@meeting_bp.route("/retry-ai/<meeting_id>", methods=["POST"])
@login_required
def retry_ai(meeting_id):
    supabase = get_supabase()

    # BOLA check
    meeting_res = supabase.table("meetings") \
        .select("transcript") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()

    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    transcript = meeting_res.data[0]["transcript"]
    if not transcript:
        return jsonify({"error": "No transcript available to extract tasks from"}), 400

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

    # Verify ownership before updating (BOLA fix)
    meeting_res = supabase.table("meetings") \
        .select("id") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()
        
    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    supabase.table("meetings").update({
        "transcript": transcript
    }).eq("id", meeting_id).eq("org_id", session["org_id"]).execute()

    return jsonify({"message": "Transcript updated"})

@meeting_bp.route("/<meeting_id>/export", methods=["GET"])
@login_required
def export_mom(meeting_id):
    # Verify ownership (BOLA check)
    data = get_meeting_with_tasks(meeting_id)
    if not data or data.get("meeting") is None:
        return jsonify({"error": "Meeting not found"}), 404

    pdf_path = generate_mom_pdf(
        data["meeting"],
        data["tasks"]
    )

    return send_file(pdf_path, as_attachment=True)

@meeting_bp.route("/<meeting_id>", methods=["DELETE"])
@login_required
def delete_meeting_route(meeting_id):
    # Soft delete meeting route
    success = soft_delete_meeting(meeting_id, session["org_id"])
    if not success:
        return jsonify({"error": "Meeting not found"}), 404
        
    return jsonify({"message": "Meeting deleted successfully"})

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
        "recording_status": "pending",
        "is_deleted": False,
        "deletion_queued": False
    }

    res = supabase.table("meetings").insert(meeting_data).execute()

    return jsonify({
        "message": "Meeting link added",
        "meeting": res.data
    })

@meeting_bp.route("/fetch-recordings", methods=["POST"])
def fetch_recordings():
    return jsonify({
        "message": "Recording fetch is legacy and disabled"
    }), 400

@meeting_bp.route("/<meeting_id>/reprocess", methods=["POST"])
@login_required
def reprocess_meeting(meeting_id):
    supabase = get_supabase()

    # 1. Meeting must exist. Else 404 (with BOLA org_id check)
    meeting_res = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .eq("org_id", session["org_id"]) \
        .eq("is_deleted", False) \
        .execute()

    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    meeting = meeting_res.data[0]

    # 2. Delete tasks
    try:
        supabase.table("tasks").delete().eq("meeting_id", meeting_id).eq("org_id", session["org_id"]).execute()
        print(f"Deleted tasks for meeting {meeting_id} during reprocessing.")
    except Exception as e:
        print(f"Error deleting tasks for reprocessing: {e}")

    # 3. Append to reprocessing history audit trail
    now = datetime.datetime.utcnow().isoformat()
    history = meeting.get("processing_history") or []
    history.append({
        "timestamp": now,
        "user_id": session["user_id"],
        "event": "reprocess_triggered",
        "message": f"Reprocessing triggered by user {session['user_id']}."
    })
    _, history = _trim_processing_metadata(None, history)

    # 4. Reset columns in database to trigger recovery/reprocessing
    try:
        reset_status = "uploaded"
        supabase.table("meetings").update({
            "transcript": None,
            "summary": None,
            "processed_at": None,
            "recording_duration": None,
            "recording_size": None,
            "processing_logs": ["upload_started", "upload_completed", "reprocess_started"],
            "processing_lock": False,
            "processing_started_at": None,
            "processing_error": None,
            "processing_step": "uploaded",
            "processing_history": history
        }).eq("id", meeting_id).eq("org_id", session["org_id"]).execute()
        
        update_status(meeting_id, reset_status, session["org_id"])
    except Exception as e:
        return jsonify({"error": f"Failed to reset meeting: {e}"}), 500

    # 5. DBQ worker will pick it up automatically from the database
    return jsonify({"message": "Reprocessing started", "meeting_id": meeting_id}), 202
