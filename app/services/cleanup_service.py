import os
import datetime
import traceback
import time
from ..utils.supabase_client import get_supabase
from .storage_service import delete_audio_from_storage

def perform_meeting_cleanup(meeting_id, org_id):
    """Physically removes all files and records of a soft-deleted meeting."""
    _perform_cleanup_internal(meeting_id, org_id)

def _perform_cleanup_internal(meeting_id, org_id):
    print(f"[Cleanup Service] Starting physical cleanup for meeting {meeting_id} (Org {org_id})...")
    try:
        supabase = get_supabase()
        
        # 1. Fetch meeting info (specifically audio_url)
        meeting_res = supabase.table("meetings") \
            .select("audio_url") \
            .eq("id", meeting_id) \
            .eq("org_id", org_id) \
            .execute()
            
        if not meeting_res.data:
            print(f"[Cleanup Service] Meeting {meeting_id} not found in DB. Aborting.")
            return
            
        audio_url = meeting_res.data[0].get("audio_url")
        
        # 2. Delete tasks from tasks table
        supabase.table("tasks").delete().eq("meeting_id", meeting_id).eq("org_id", org_id).execute()
        print(f"[Cleanup Service] Deleted tasks associated with meeting {meeting_id}.")
        
        # 3. Delete remote audio file from Supabase storage
        if audio_url:
            delete_audio_from_storage(audio_url)
                
        # 4. Delete the meeting record permanently from the database
        supabase.table("meetings").delete().eq("id", meeting_id).eq("org_id", org_id).execute()
        print(f"[Cleanup Service] Permanently deleted meeting record {meeting_id} from database.")
        
    except Exception as e:
        print(f"[Cleanup Service] Error during physical cleanup of meeting {meeting_id}: {e}")
        traceback.print_exc()

def run_differential_storage_sweeper():
    """Compares Supabase Storage files against active meetings and deletes orphaned audio files."""
    print("[Cleanup Service] Starting differential storage sweeper...")
    try:
        supabase = get_supabase()
        bucket = "meetings-audio"
        try:
            from flask import current_app
            bucket = current_app.config.get("STORAGE_BUCKET", bucket)
        except Exception:
            pass
            
        # 1. List files in 'meetings/' folder
        storage_files = supabase.storage.from_(bucket).list("meetings")
        if not storage_files:
            print("[Cleanup Service] No files found in remote storage meetings folder.")
            return
            
        # Extract filename UUIDs from storage files list
        remote_filenames = [f["name"] for f in storage_files if f.get("name")]
        print(f"[Cleanup Service] Found {len(remote_filenames)} files in remote storage.")
        
        if not remote_filenames:
            return
            
        # 2. Fetch all audio_urls from active meetings (not deleted)
        meeting_res = supabase.table("meetings") \
            .select("audio_url") \
            .eq("is_deleted", False) \
            .execute()
            
        active_filenames = set()
        for meeting in meeting_res.data:
            url = meeting.get("audio_url")
            if url:
                active_filenames.add(url.split("/")[-1])
                
        # 3. Identify and delete orphaned storage files
        orphans = []
        for r_file in remote_filenames:
            if r_file not in active_filenames:
                orphans.append(f"meetings/{r_file}")
                
        if orphans:
            print(f"[Cleanup Service] Found {len(orphans)} orphaned files. Deleting: {orphans}")
            supabase.storage.from_(bucket).remove(orphans)
            print("[Cleanup Service] Orphaned files deleted.")
        else:
            print("[Cleanup Service] No orphaned storage files found.")
            
    except Exception as e:
        print(f"[Cleanup Service] Error running differential sweeper: {e}")

def run_soft_delete_sweeper():
    """Finds all soft-deleted meetings queued for physical cleanup and runs them."""
    print("[Cleanup Service] Starting soft-delete sweeper...")
    try:
        supabase = get_supabase()
        res = supabase.table("meetings") \
            .select("id, org_id") \
            .eq("is_deleted", True) \
            .eq("deletion_queued", True) \
            .execute()
            
        for job in res.data:
            perform_meeting_cleanup(job["id"], job["org_id"])
            
    except Exception as e:
        print(f"[Cleanup Service] Error in soft-delete sweeper: {e}")

def run_local_tmp_sweeper():
    """Prunes local temporary audio chunk downloads older than 2 hours."""
    import tempfile
    temp_dir = tempfile.gettempdir()
    print(f"[Cleanup Service] Cleaning local temp directory: {temp_dir}")
    now = time.time()
    count = 0
    try:
        for f in os.listdir(temp_dir):
            if f.endswith(".mp3") or f.endswith(".webm") or f.startswith("tmp"):
                fp = os.path.join(temp_dir, f)
                try:
                    if os.stat(fp).st_mtime < now - 7200: # 2 hours
                        os.remove(fp)
                        count += 1
                except Exception:
                    pass
        print(f"[Cleanup Service] Deleted {count} temporary local files.")
    except Exception as e:
        print(f"[Cleanup Service] Error cleaning local temp files: {e}")
