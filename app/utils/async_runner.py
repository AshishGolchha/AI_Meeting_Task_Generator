import threading
import datetime
import traceback
from flask import current_app
from ..utils.supabase_client import get_supabase
from ..services.speech_service import transcribe_audio, PartialTranscriptionError
from ..services.llm_service import extract_tasks_from_transcript
from ..services.task_service import save_tasks

# Background thread pool executor for running async tasks
_executor_lock = threading.Lock()
_worker_thread = None
_stop_event = threading.Event()

def start_background_worker(app):
    """Starts the background processing worker daemon thread."""
    global _worker_thread
    with _executor_lock:
        if _worker_thread is None or not _worker_thread.is_alive():
            _stop_event.clear()
            # We pass the app context or app object to access config
            _worker_thread = threading.Thread(
                target=_worker_loop,
                args=(app,),
                name="AI-Meeting-Task-Worker",
                daemon=True
            )
            _worker_thread.start()
            print("[Async Runner] Background worker started successfully.")

def trigger_processing(meeting_id):
    print(f"[Async Runner] Processing signal received for {meeting_id}")


def _trim_processing_metadata(logs, history):
    return (logs or [])[-100:], (history or [])[-100:]

def _worker_loop(app):
    """Main loop for polling database for pending/uploaded meetings."""
    import time
    while not _stop_event.is_set():
        try:
            with app.app_context():
                _poll_and_process(app)
        except Exception as e:
            print(f"[Async Runner] Error in worker loop: {e}")
            traceback.print_exc()
        
        # Poll database every 5 seconds for new uploads
        poll_interval = app.config.get("WORKER_POLL_INTERVAL_SEC", 5)
        time.sleep(poll_interval)

def recover_stale_locks(supabase):
    """Automatically clears locks that have been held for more than 30 minutes, resetting status for retry."""
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now - datetime.timedelta(minutes=30)
    
    stale_jobs = supabase.table("meetings") \
        .select("id, processing_history, processing_logs") \
        .eq("processing_lock", True) \
        .eq("is_deleted", False) \
        .lt("processing_started_at", threshold.isoformat()) \
        .execute()
        
    for job in stale_jobs.data:
        meeting_id = job["id"]
        logs = job.get("processing_logs") or []
        history = job.get("processing_history") or []
        
        logs.append("stale_lock_recovered")
        history.append({
            "timestamp": now.isoformat(),
            "event": "stale_lock_recovered",
            "message": "Stale lock detected (>30 min). Clear lock and allow processing to continue."
        })
        logs, history = _trim_processing_metadata(logs, history)
        
        supabase.table("meetings").update({
            "recording_status": "uploaded",
            "processing_step": "uploaded",
            "processing_lock": False,
            "processing_started_at": None,
            "processing_logs": logs,
            "processing_history": history
        }).eq("id", meeting_id).execute()
        print(f"[Async Runner] Stale lock recovered for meeting {meeting_id}")

def _poll_and_process(app):
    supabase = get_supabase()
    
    # 0. Recover any stale locks before starting
    try:
        recover_stale_locks(supabase)
    except Exception as e:
        print(f"[Async Runner] Error running stale lock recovery: {e}")
    
    # Query for meetings with 'uploaded' status, order by oldest first, limit 1
    res = supabase.table("meetings") \
        .select("id, org_id, created_by, title") \
        .eq("recording_status", "uploaded") \
        .eq("is_deleted", False) \
        .eq("processing_lock", False) \
        .order("created_at") \
        .limit(1) \
        .execute()
        
    if not res.data:
        # Check if there are any meetings stuck in progress for over 30 minutes to time them out
        _check_timeouts(supabase)
        return
        
    for job in res.data:
        meeting_id = job["id"]
        org_id = job["org_id"]
        created_by = job["created_by"]
        
        # 1. Atomic Lock Acquisition
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Verify and fetch current logs/history
        meeting_data = supabase.table("meetings") \
            .select("processing_logs, processing_history, org_id") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .single() \
            .execute()
            
        logs = meeting_data.data.get("processing_logs") or []
        history = meeting_data.data.get("processing_history") or []
        
        logs.append("processing_started_async")
        history.append({
            "timestamp": now.isoformat(),
            "event": "lock_acquired_async",
            "message": "Background processing started atomically."
        })
        logs, history = _trim_processing_metadata(logs, history)
        
        # Attempt atomic update
        lock_res = supabase.table("meetings").update({
            "processing_lock": True,
            "processing_started_at": now.isoformat(),
            "recording_status": "transcribing",
            "processing_step": "transcribing",
            "processing_logs": logs,
            "processing_history": history
        }).eq("id", meeting_id).eq("org_id", org_id).eq("processing_lock", False).eq("recording_status", "uploaded").execute()
        
        if not lock_res.data:
            print(f"[Async Runner] Race condition avoided. Meeting {meeting_id} already locked.")
            continue
            
        print(f"[Async Runner] Atomic lock acquired for meeting {meeting_id}. Processing...")
        
        # Run processing logic
        execute_job(meeting_id, org_id, created_by, app)

def execute_job(meeting_id, org_id, created_by, app):
    supabase = get_supabase()
    
    def status_callback(chunk_num, total_chunks, chunk_transcript):
        try:
            m_data = supabase.table("meetings") \
                .select("partial_transcript, processing_logs, org_id") \
                .eq("id", meeting_id) \
                .eq("org_id", org_id) \
                .single() \
                .execute()
            current_partial = m_data.data.get("partial_transcript") or ""
            new_partial = (current_partial + " " + chunk_transcript).strip()
            
            logs = m_data.data.get("processing_logs") or []
            logs.append(f"chunk_{chunk_num}_completed")
            logs = logs[-100:]
            
            supabase.table("meetings").update({
                "partial_transcript": new_partial,
                "processing_logs": logs
            }).eq("id", meeting_id).eq("org_id", org_id).execute()
            print(f"[Async Runner] Chunk {chunk_num}/{total_chunks} transcription persisted for meeting {meeting_id}.")
        except Exception as e:
            print(f"[Async Runner] Error in chunk status_callback: {e}")
            
    try:
        # Fetch the meeting to get audio_url
        meeting_res = supabase.table("meetings") \
            .select("audio_url, org_id") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .single() \
            .execute()
        audio_url = meeting_res.data.get("audio_url")
        if not audio_url:
            raise Exception("Audio URL not found on meeting record")

        # 3. Speech → Text
        # Note: we pass the public URL. Speech service handles download, chunking and transcription.
        transcript_text, duration, size = transcribe_audio(audio_url, status_callback=status_callback)
        
        # Update checkpoint to extracting_tasks
        now = datetime.datetime.now(datetime.timezone.utc)
        m_res = supabase.table("meetings") \
            .select("processing_logs, processing_history, org_id") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .single() \
            .execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_history = m_res.data.get("processing_history") or []
        
        current_logs.append("transcription_completed")
        current_logs.append("task_extraction_started")
        current_history.append({
            "timestamp": now.isoformat(),
            "event": "transcription_finished",
            "message": f"Transcription completed. Duration: {duration}s, size: {size} bytes"
        })
        current_logs, current_history = _trim_processing_metadata(current_logs, current_history)
        
        supabase.table("meetings").update({
            "transcript": transcript_text,
            "partial_transcript": None,
            "recording_duration": duration,
            "recording_size": size,
            "recording_status": "extracting_tasks",
            "processing_step": "extracting_tasks",
            "processing_logs": current_logs,
            "processing_history": current_history
        }).eq("id", meeting_id).eq("org_id", org_id).execute()
        
        # 4. LLM Task Extraction
        ai_data = extract_tasks_from_transcript(transcript_text)
        summary_text = ai_data.get("summary")
        tasks = ai_data.get("tasks", [])
        
        # Save summary
        supabase.table("meetings").update({
            "summary": summary_text
        }).eq("id", meeting_id).execute()
        
        # 5. Save Tasks using snapshot org_id (Never depend on session!)
        inserted_tasks = save_tasks(
            meeting_id,
            tasks,
            org_id=org_id
        )
        
        # Complete meeting
        now = datetime.datetime.now(datetime.timezone.utc)
        m_res = supabase.table("meetings") \
            .select("processing_logs, processing_history, org_id") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .single() \
            .execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_history = m_res.data.get("processing_history") or []
        
        current_logs.append("task_extraction_completed")
        current_logs.append("processing_completed")
        current_history.append({
            "timestamp": now.isoformat(),
            "event": "processing_completed",
            "message": f"Successfully completed. Extracted {len(inserted_tasks)} tasks."
        })
        current_logs, current_history = _trim_processing_metadata(current_logs, current_history)
        
        supabase.table("meetings").update({
            "recording_status": "completed",
            "processing_step": "completed",
            "processing_lock": False,
            "processing_logs": current_logs,
            "processing_history": current_history,
            "processed_at": now.isoformat(),
            "processing_error": None,
            "partial_transcript": None
        }).eq("id", meeting_id).eq("org_id", org_id).execute()
        
        print(f"[Async Runner] Meeting {meeting_id} processed successfully.")

    except PartialTranscriptionError as pte:
        print(f"[Async Runner] Partial transcription error on meeting {meeting_id}: {pte}")
        _mark_job_failed(meeting_id, org_id, str(pte), partial_transcript=pte.partial_transcript)
        
    except Exception as exc:
        print(f"[Async Runner] General processing failure on meeting {meeting_id}: {exc}")
        traceback.print_exc()
        _mark_job_failed(meeting_id, org_id, str(exc))

def _mark_job_failed(meeting_id, org_id, error_msg, partial_transcript=None):
    try:
        supabase = get_supabase()
        now = datetime.datetime.now(datetime.timezone.utc)
        
        m_res = supabase.table("meetings") \
            .select("processing_logs, processing_history, org_id") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .single() \
            .execute()
        current_logs = m_res.data.get("processing_logs") or []
        current_history = m_res.data.get("processing_history") or []
        
        current_logs.append("processing_failed")
        current_history.append({
            "timestamp": now.isoformat(),
            "event": "processing_failed",
            "message": f"Failed with error: {error_msg}"
        })
        current_logs, current_history = _trim_processing_metadata(current_logs, current_history)
        
        update_data = {
            "recording_status": "failed",
            "processing_step": "failed",
            "processing_lock": False,
            "processing_logs": current_logs,
            "processing_history": current_history,
            "processing_error": error_msg
        }
        if partial_transcript is not None:
            update_data["partial_transcript"] = partial_transcript
            
        supabase.table("meetings").update(update_data).eq("id", meeting_id).eq("org_id", org_id).execute()
    except Exception as e:
        print(f"[Async Runner] Critical error marking meeting {meeting_id} as failed: {e}")

def _check_timeouts(supabase):
    """Checks for active jobs running > 30 minutes and marks them timed out."""
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now - datetime.timedelta(minutes=30)
    
    stale_jobs = supabase.table("meetings") \
        .select("id, processing_history, processing_logs") \
        .eq("processing_lock", True) \
        .eq("is_deleted", False) \
        .lt("processing_started_at", threshold.isoformat()) \
        .execute()
        
    for job in stale_jobs.data:
        meeting_id = job["id"]
        logs = job.get("processing_logs") or []
        history = job.get("processing_history") or []
        
        logs.append("processing_timeout")
        history.append({
            "timestamp": now.isoformat(),
            "event": "processing_timeout",
            "message": "Job aborted because total execution exceeded 30 minutes."
        })
        logs, history = _trim_processing_metadata(logs, history)
        
        supabase.table("meetings").update({
            "recording_status": "failed",
            "processing_step": "failed",
            "processing_lock": False,
            "processing_logs": logs,
            "processing_history": history,
            "processing_error": "Processing timed out (exceeded 30 minutes limit)"
        }).eq("id", meeting_id).execute()
        
        print(f"[Async Runner] Stale locked job {meeting_id} timed out.")

def recover_crashed_jobs(app):
    """To be called on Flask app boot to release any locked jobs interrupted by a crash/restart."""
    try:
        supabase = get_supabase()
        now = datetime.datetime.now(datetime.timezone.utc)
        threshold = now - datetime.timedelta(minutes=15)
        
        stale_jobs = supabase.table("meetings") \
            .select("id, processing_history, processing_logs") \
            .eq("processing_lock", True) \
            .eq("is_deleted", False) \
            .lt("processing_started_at", threshold.isoformat()) \
            .execute()
            
        for job in stale_jobs.data:
            meeting_id = job["id"]
            logs = job.get("processing_logs") or []
            history = job.get("processing_history") or []
            
            logs.append("server_restart_recovery")
            history.append({
                "timestamp": now.isoformat(),
                "event": "server_restart_recovery",
                "message": "Job lock cleared and marked failed because process died mid-processing."
            })
            logs, history = _trim_processing_metadata(logs, history)
            
            supabase.table("meetings").update({
                "recording_status": "failed",
                "processing_step": "failed",
                "processing_lock": False,
                "processing_logs": logs,
                "processing_history": history,
                "processing_error": "Processing was interrupted by a server restart"
            }).eq("id", meeting_id).execute()
            print(f"[Async Runner] Recovered crashed meeting lock: {meeting_id}")
            
    except Exception as e:
        print(f"[Async Runner] Error in recovery routine: {e}")
