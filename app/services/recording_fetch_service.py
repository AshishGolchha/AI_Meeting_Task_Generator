# =====================================================================
# ⚠️ LEGACY / OBSOLETE: This service is no longer used and is replaced by browser-based tab audio recording.
# =====================================================================

# THIS FILE IS OBSOLETE.
# Browser Audio Capture is now the active recording flow.

LEGACY_MODE = True

import requests
import datetime
from ..utils.supabase_client import get_supabase
from .google_drive_service import find_meeting_recording, download_and_convert_recording
from .speech_service import transcribe_audio
from .llm_service import extract_tasks_from_transcript
from .task_service import save_tasks

def detect_platform(link: str):
    """
    Detect meeting platform
    """
    if not link:
        return "unknown"
    
    link = link.lower()

    if "zoom.us" in link:
        return "zoom"

    elif "meet.google.com" in link:
        return "google_meet"

    return "unknown"


def fetch_zoom_recording(link: str):
    """
    Placeholder for Zoom recording fetch
    (Will implement OAuth later)
    """
    print("🔎 Checking Zoom recording...")
    # TODO — Zoom API integration
    return None


def fetch_google_meet_recording(link: str, user_id: str, title: str, meeting_date: str):
    """
    Fetch Google Meet recording from Google Drive and return (recording_url, audio_url)
    """
    print("🔎 Checking Google Meet recording...")
    
    file_id = find_meeting_recording(user_id, link, title, meeting_date)
    if not file_id:
        print("⏳ Recording not found in Google Drive yet")
        return None, None
        
    print(f"✅ Found recording file {file_id}. Commencing download & conversion...")
    recording_url, audio_url = download_and_convert_recording(user_id, file_id)
    return recording_url, audio_url


def process_pending_recordings():
    """
    Scan DB and try fetching and processing recordings.
    Runs inside background tasks triggered by cron/admin endpoint.
    """
    supabase = get_supabase()

    res = supabase.table("meetings") \
        .select("*") \
        .eq("recording_status", "pending") \
        .execute()

    meetings = res.data

    print(f"\n📡 Pending recordings: {len(meetings)}")

    for meeting in meetings:
        meeting_id = meeting["id"]
        link = meeting.get("meeting_link")
        created_by = meeting.get("created_by")
        title = meeting.get("title")
        meeting_date = meeting.get("meeting_date")
        org_id = meeting.get("org_id")
        retry_count = meeting.get("retry_count") or 0
        transcript = meeting.get("transcript")
        recording_status = meeting.get("recording_status")

        # Idempotency Protection: skip if completed or already has transcript
        if recording_status == "completed" or transcript:
            print(f"⏭️ Skipping completed meeting {meeting_id}")
            continue

        # Skip if retry limit exceeded
        if retry_count >= 10:
            print(f"⏭️ Skipping failed meeting {meeting_id} (retry limit reached)")
            continue

        if not link:
            print(f"❌ No meeting link found for meeting {meeting_id}")
            continue

        platform = detect_platform(link)

        print(f"\nProcessing meeting: {meeting_id}")
        print("Platform:", platform)
        print("Meeting Link:", link)

        # Update platform in DB if not set
        if meeting.get("platform") != platform:
            supabase.table("meetings").update({"platform": platform}).eq("id", meeting_id).execute()

        if platform == "zoom":
            print("⏳ Zoom recordings are currently Zoom-ready placeholder.")
            continue

        elif platform == "google_meet":
            try:
                # 1. Discover, download, convert and upload recording
                recording_url, audio_url = fetch_google_meet_recording(link, created_by, title, meeting_date)

                if not audio_url:
                    # Increment retry count
                    new_retry = retry_count + 1
                    update_data = {"retry_count": new_retry}
                    if new_retry >= 10:
                        update_data["recording_status"] = "failed"
                        update_data["processing_error"] = "Google Meet recording not found after 10 attempts"
                    
                    supabase.table("meetings").update(update_data).eq("id", meeting_id).execute()
                    print(f"⏳ Recording not ready. Retry count: {new_retry}")
                    continue

                # Save urls first
                supabase.table("meetings").update({
                    "recording_url": recording_url,
                    "audio_url": audio_url
                }).eq("id", meeting_id).execute()

                # 2. Transcribe audio
                print(f"🎙️ Transcribing audio from {audio_url}...")
                transcript_text = transcribe_audio(audio_url)

                # 3. Save transcript
                supabase.table("meetings").update({
                    "transcript": transcript_text
                }).eq("id", meeting_id).execute()

                # 4. Extract tasks and summary
                print("🤖 Extracting summary and tasks...")
                ai_data = extract_tasks_from_transcript(transcript_text)
                summary_text = ai_data.get("summary", "")
                tasks_list = ai_data.get("tasks", [])

                # 5. Save summary
                supabase.table("meetings").update({
                    "summary": summary_text
                }).eq("id", meeting_id).execute()

                # 6. Map and Save Tasks
                print(f"💾 Saving {len(tasks_list)} tasks...")
                save_tasks(meeting_id, tasks_list, org_id)

                # 7. Update recording status to completed
                supabase.table("meetings").update({
                    "recording_status": "completed",
                    "processed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "processing_error": None
                }).eq("id", meeting_id).execute()

                print("✅ Meeting processed successfully.")

            except Exception as e:
                error_msg = str(e)
                print(f"❌ Error processing Google Meet recording: {error_msg}")
                new_retry = retry_count + 1
                update_data = {
                    "retry_count": new_retry,
                    "processing_error": error_msg
                }
                if new_retry >= 10:
                    update_data["recording_status"] = "failed"
                    
                supabase.table("meetings").update(update_data).eq("id", meeting_id).execute()
        else:
            print("❌ Unknown platform")
            # Set to failed or update retry
            new_retry = retry_count + 1
            update_data = {
                "retry_count": new_retry,
                "processing_error": f"Unsupported meeting platform: {platform}"
            }
            if new_retry >= 10:
                update_data["recording_status"] = "failed"
            supabase.table("meetings").update(update_data).eq("id", meeting_id).execute()

