import requests
from ..utils.supabase_client import get_supabase


def detect_platform(link: str):
    """
    Detect meeting platform
    """
    if not link:
        return "unknown"
    
    link=link.lower()

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


def fetch_google_meet_recording(link: str):
    """
    Placeholder for Google Drive recording fetch
    """

    print("🔎 Checking Google Meet recording...")

    # TODO — Google Drive API integration
    return None


def process_pending_recordings():
    """
    Scan DB and try fetching recordings
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

        if not link:
            print(f"❌ No meeting link found")
            continue

        platform = detect_platform(link)

        print(f"\nProcessing meeting: {meeting_id}")
        print("Platform:", platform)
        print("Meeting Link:", link)

        recording_url = None

        if platform == "zoom":
            recording_url = fetch_zoom_recording(link)

        elif platform == "google_meet":
            recording_url = fetch_google_meet_recording(link)

        else:
            print("❌ Unknown platform")

        # If recording found → save
        if recording_url:

            supabase.table("meetings").update({
                "recording_url": recording_url,
                "recording_status": "completed"
            }).eq("id", meeting_id).execute()

            print("✅ Recording URL stored:", recording_url)

        else:
            print("⏳ Recording not ready yet")

            supabase.table("meetings").update({
                "recording_status": "pending"
            }).eq("id", meeting_id).execute()
