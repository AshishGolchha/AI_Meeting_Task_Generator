from flask import Blueprint, request, jsonify, send_file, session
from ..services.storage_service import upload_audio_to_storage
from ..services.speech_service import transcribe_audio, PartialTranscriptionError
from ..services.llm_service import extract_tasks_from_transcript
from ..services.task_service import save_tasks
from ..services.meeting_service import get_meeting_with_tasks
from ..services.pdf_service import generate_mom_pdf
from ..utils.supabase_client import get_supabase
from ..utils.auth_middleware import login_required
import datetime

meeting_bp = Blueprint("meetings", __name__)

VALID_STATUSES = {
    "pending",
    "uploaded",
    "transcribing",
    "extracting_tasks",
    "completed",
    "failed"
}


def update_status(meeting_id, status):
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid meeting status: {status}")

    supabase = get_supabase()
    return supabase.table("meetings").update({
        "recording_status": status
    }).eq("id", meeting_id).execute()

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

    recording_status = "uploaded"
    if recording_status not in VALID_STATUSES:
        return jsonify({"error": f"Invalid meeting status: {recording_status}"}), 500

    data = {
        "title": title,
        "description": description,
        "meeting_date": meeting_date,
        "audio_url": audio_url,
        "created_at": datetime.datetime.utcnow().isoformat(),
        "org_id": session["org_id"],
        "created_by": session["user_id"],
        "recording_status": recording_status,
        "processing_logs": ["upload_started", "upload_completed"]
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

    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    meeting = meeting_res.data
    audio_url = meeting.get("audio_url")
    
    if not audio_url:
        return jsonify({"error": "Audio URL not found on meeting"}), 400

    # Check lock protection
    is_locked = meeting.get("processing_lock")
    started_at_str = meeting.get("processing_started_at")
    now = datetime.datetime.now(datetime.timezone.utc)
    
    logs = meeting.get("processing_logs") or []
    if not isinstance(logs, list):
        logs = []

    if is_locked:
        is_recent = False
        if started_at_str:
            try:
                clean_started = started_at_str.split(".")[0].replace("Z", "").split("+")[0]
                started_dt = datetime.datetime.fromisoformat(clean_started).replace(tzinfo=datetime.timezone.utc)
                age_minutes = (now - started_dt).total_seconds() / 60.0
                if age_minutes < 30:
                    is_recent = True
            except Exception as parse_err:
                print("Error parsing lock start time:", parse_err)
        
        if is_recent:
            print(f"Skipping processing for meeting {meeting_id} - lock is active and less than 30 mins old.")
            return jsonify({"message": "Meeting is currently being processed by another worker"}), 409
        else:
            print(f"Lock expired for meeting {meeting_id}. Recovering lock...")
            logs.append("lock_recovered")

    # Check if already processed
    status = meeting.get("recording_status")
    
    if status == "completed":
        print(f"Meeting {meeting_id} is already completed. Skipping.")
        return jsonify({"message": "Meeting already processed"}), 200

    # Lock meeting and set status = transcribing
    logs.append("transcription_started")
    try:
        supabase.table("meetings").update({
            "processing_lock": True,
            "processing_started_at": now.isoformat(),
            "processing_logs": logs
        }).eq("id", meeting_id).execute()
        update_status(meeting_id, "transcribing")
    except Exception as lock_err:
        try:
            supabase.table("meetings").update({
                "processing_lock": False
            }).eq("id", meeting_id).execute()
        except Exception as release_err:
            print(f"Warning: Failed to release processing lock for meeting {meeting_id}: {release_err}")
        return jsonify({"error": f"Failed to acquire processing lock: {lock_err}"}), 500

    try:
        # 2️⃣ Speech → Text
        transcript_text, duration, size = transcribe_audio(audio_url)

        # Update meeting with transcript, size, duration, and status = extracting_tasks
        m_res = supabase.table("meetings").select("processing_logs").eq("id", meeting_id).single().execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_logs.append("transcription_completed")
        current_logs.append("task_extraction_started")

        supabase.table("meetings").update({
            "transcript": transcript_text,
            "recording_duration": duration,
            "recording_size": size,
            "processing_logs": current_logs
        }).eq("id", meeting_id).execute()
        update_status(meeting_id, "extracting_tasks")

        # 3️⃣ AI Extraction
        ai_data = extract_tasks_from_transcript(transcript_text)
        summary_text = ai_data.get("summary")
        tasks = ai_data.get("tasks", [])

        # Save summary
        supabase.table("meetings").update({
            "summary": summary_text
        }).eq("id", meeting_id).execute()

        # 4️⃣ Save Tasks
        inserted_tasks = save_tasks(
            meeting_id,
            tasks,
            org_id=meeting["org_id"]
        )

        # Clear lock and set completed status
        m_res = supabase.table("meetings").select("processing_logs").eq("id", meeting_id).single().execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_logs.append("task_extraction_completed")

        supabase.table("meetings").update({
            "processing_logs": current_logs,
            "processed_at": datetime.datetime.utcnow().isoformat(),
            "processing_error": None
        }).eq("id", meeting_id).execute()
        try:
            update_status(meeting_id, "completed")
        except Exception as status_err:
            print(f"Warning: Failed to update status for meeting {meeting_id}: {status_err}")

        return jsonify({
            "summary": summary_text,
            "tasks": inserted_tasks
        })

    except PartialTranscriptionError as pte:
        print(f"Partial transcription error on meeting {meeting_id}: {pte}")
        m_res = supabase.table("meetings").select("processing_logs").eq("id", meeting_id).single().execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_logs.append("processing_failed")

        supabase.table("meetings").update({
            "transcript": pte.partial_transcript,
            "processing_logs": current_logs,
            "processing_error": str(pte)
        }).eq("id", meeting_id).execute()
        try:
            update_status(meeting_id, "failed")
        except Exception as status_err:
            print(f"Warning: Failed to update status for meeting {meeting_id}: {status_err}")

        return jsonify({"error": "Partial transcription failure", "details": str(pte)}), 500

    except Exception as exc:
        print(f"General processing failure on meeting {meeting_id}: {exc}")
        m_res = supabase.table("meetings").select("processing_logs").eq("id", meeting_id).single().execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_logs.append("processing_failed")

        supabase.table("meetings").update({
            "processing_logs": current_logs,
            "processing_error": str(exc)
        }).eq("id", meeting_id).execute()
        try:
            update_status(meeting_id, "failed")
        except Exception as status_err:
            print(f"Warning: Failed to update status for meeting {meeting_id}: {status_err}")

        return jsonify({"error": "Processing failure", "details": str(exc)}), 500

    finally:
        try:
            supabase.table("meetings").update({
                "processing_lock": False
            }).eq("id", meeting_id).execute()
        except Exception as release_err:
            print(f"Warning: Failed to release processing lock for meeting {meeting_id}: {release_err}")

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

    if meeting_data["recording_status"] not in VALID_STATUSES:
        return jsonify({"error": f"Invalid meeting status: {meeting_data['recording_status']}"}), 500

    res = supabase.table("meetings").insert(meeting_data).execute()

    return jsonify({
        "message": "Meeting link added",
        "meeting": res.data
    })

@meeting_bp.route("/fetch-recordings", methods=["POST"])
# @login_required
def fetch_recordings():
    return jsonify({
        "message": "Recording fetch is legacy and disabled"
    }), 400

@meeting_bp.route("/<meeting_id>/reprocess", methods=["POST"])
@login_required
def reprocess_meeting(meeting_id):
    supabase = get_supabase()

    # 1. Meeting must exist. Else 404
    meeting_res = supabase.table("meetings") \
        .select("*") \
        .eq("id", meeting_id) \
        .execute()

    if not meeting_res.data:
        return jsonify({"error": "Meeting not found"}), 404

    meeting = meeting_res.data[0]

    # 2. Validate: meeting.org_id == session["org_id"]. Else 403
    if meeting.get("org_id") != session.get("org_id"):
        return jsonify({"error": "Forbidden"}), 403

    # 3. Delete tasks
    try:
        supabase.table("tasks").delete().eq("meeting_id", meeting_id).execute()
        print(f"Deleted tasks for meeting {meeting_id} during reprocessing.")
    except Exception as e:
        print(f"Error deleting tasks for reprocessing: {e}")

    # 4-8. Reset columns in database
    try:
        reset_status = "uploaded"
        if reset_status not in VALID_STATUSES:
            return jsonify({"error": f"Invalid meeting status: {reset_status}"}), 500

        supabase.table("meetings").update({
            "transcript": None,
            "summary": None,
            "processing_logs": ["upload_started", "upload_completed"],
            "processing_lock": False,
            "processing_started_at": None,
            "processing_error": None
        }).eq("id", meeting_id).execute()
        update_status(meeting_id, reset_status)
    except Exception as e:
        return jsonify({"error": f"Failed to reset meeting: {e}"}), 500

    # 9. Run processing synchronously
    return process_meeting(meeting_id)
