# =====================================================================
# ⚠️ LEGACY / OBSOLETE: This service is no longer used and is replaced by browser-based tab audio recording.
# =====================================================================

# THIS FILE IS OBSOLETE.
# Browser Audio Capture is now the active recording flow.

LEGACY_MODE = True

import re
import os
import datetime
import tempfile
import requests
from flask import current_app
from pydub import AudioSegment
from ..utils.supabase_client import get_supabase
from ..config import Config
from .storage_service import upload_local_file_to_storage

def get_authenticated_headers(user_id):
    """
    Ensure OAuth access token is valid. Refreshes if expired, clears if revoked/invalid.
    """
    supabase = get_supabase()
    
    # Retrieve user tokens
    res = supabase.table("users") \
        .select("google_access_token, google_refresh_token, google_token_expiry, google_connected") \
        .eq("id", user_id) \
        .single() \
        .execute()
        
    user = res.data
    if not user or not user.get("google_connected"):
        return None
        
    access_token = user.get("google_access_token")
    refresh_token = user.get("google_refresh_token")
    expiry_str = user.get("google_token_expiry")
    
    if not access_token:
        return None
        
    # Check if expired (or within 60s of expiring)
    is_expired = False
    if expiry_str:
        try:
            # Handle standard ISO timestamp formats safely
            clean_expiry = expiry_str.split(".")[0].replace("Z", "").split("+")[0]
            expiry_dt = datetime.datetime.fromisoformat(clean_expiry).replace(tzinfo=datetime.timezone.utc)
            now = datetime.datetime.now(datetime.timezone.utc)
            if (expiry_dt - now).total_seconds() < 60:
                is_expired = True
        except Exception as e:
            print(f"Error parsing token expiry '{expiry_str}': {e}")
            is_expired = True
    else:
        is_expired = True
        
    if is_expired and refresh_token:
        print(f"🔄 Token expired for user {user_id}. Refreshing...")
        client_id = current_app.config.get("GOOGLE_CLIENT_ID") or Config.GOOGLE_CLIENT_ID
        client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET") or Config.GOOGLE_CLIENT_SECRET
        
        try:
            token_res = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token"
                },
                timeout=15
            )
            
            if token_res.status_code == 200:
                token_data = token_res.json()
                new_access = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 3600)
                new_expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)).isoformat()
                
                # Update DB
                supabase.table("users").update({
                    "google_access_token": new_access,
                    "google_token_expiry": new_expiry
                }).eq("id", user_id).execute()
                
                access_token = new_access
                print("✅ Token refreshed successfully.")
            else:
                print(f"❌ Failed to refresh Google OAuth token: {token_res.text}")
                # Clear tokens if refresh token is invalid / revoked
                supabase.table("users").update({
                    "google_access_token": None,
                    "google_refresh_token": None,
                    "google_token_expiry": None,
                    "google_connected": False
                }).eq("id", user_id).execute()
                return None
        except Exception as e:
            print(f"Exception during token refresh: {e}")
            return None
            
    return {
        "Authorization": f"Bearer {access_token}"
    }

def parse_date(date_str):
    if not date_str:
        return None
    try:
        # e.g., '2026-02-14T11:10:13.310872' or '2026-02-14'
        if 'T' in date_str:
            dt_part = date_str.split('.')[0].replace("Z", "").split("+")[0]
            return datetime.datetime.fromisoformat(dt_part).replace(tzinfo=datetime.timezone.utc)
        else:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}")
        return None

def find_meeting_recording(user_id, meeting_link, title, meeting_date):
    """
    Search Google Drive for the meeting recording.
    Returns the file ID of the best match.
    """
    headers = get_authenticated_headers(user_id)
    if not headers:
        print("❌ No valid authentication headers found.")
        return None
        
    # Extract meet code from URL (e.g. abc-defg-hij)
    match = re.search(r"meet\.google\.com/([a-z0-9\-]+)", meeting_link)
    meet_code = match.group(1).lower() if match else None
    
    # Optional parent folder name ranking signal
    folder_ids = []
    try:
        folder_res = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={
                "q": "mimeType = 'application/vnd.google-apps.folder' and name = 'Meet Recordings' and trashed = false",
                "fields": "files(id)"
            },
            timeout=10
        )
        if folder_res.status_code == 200:
            folder_ids = [f["id"] for f in folder_res.json().get("files", [])]
    except Exception as e:
        print(f"Error checking 'Meet Recordings' folder: {e}")
        
    # Try querying files with date range first (within 3 days)
    dt = parse_date(meeting_date)
    q_parts = ["mimeType contains 'video/'", "trashed = false"]
    
    if dt:
        start_dt = dt - datetime.timedelta(days=3)
        end_dt = dt + datetime.timedelta(days=3)
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        q_parts.append(f"createdTime >= '{start_str}'")
        q_parts.append(f"createdTime <= '{end_str}'")
        
    q_str = " and ".join(q_parts)
    
    files = []
    try:
        files_res = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={
                "q": q_str,
                "fields": "files(id, name, mimeType, createdTime, parents)",
                "pageSize": 100
            },
            timeout=10
        )
        if files_res.status_code == 200:
            files = files_res.json().get("files", [])
    except Exception as e:
        print(f"Error querying Google Drive: {e}")
        
    # If no files found with date filter, fallback to searching globally by name/code
    if not files and meet_code:
        print("⚠️ No recordings found in date range. Running fallback global search...")
        fallback_q = f"mimeType contains 'video/' and name contains '{meet_code}' and trashed = false"
        try:
            files_res = requests.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params={
                    "q": fallback_q,
                    "fields": "files(id, name, mimeType, createdTime, parents)",
                    "pageSize": 50
                },
                timeout=10
            )
            if files_res.status_code == 200:
                files = files_res.json().get("files", [])
        except Exception as e:
            print(f"Error running global fallback search: {e}")
            
    if not files:
        print("❌ No matching recordings found.")
        return None
        
    # Rank candidates
    best_file = None
    best_score = -1
    
    for f in files:
        name = f.get("name", "").lower()
        score = 0
        
        # 1. Check meet code in name
        if meet_code and meet_code in name:
            score += 100
            
        # 2. Check title words in name
        if title:
            words = [w.lower() for w in re.findall(r"\w+", title) if len(w) > 2]
            match_count = sum(1 for w in words if w in name)
            score += match_count * 10
            
        # 3. Check parent folder
        parents = f.get("parents", [])
        if any(p_id in folder_ids for p_id in parents):
            score += 30
            
        # 4. Check time proximity
        file_created = f.get("createdTime")
        file_dt = parse_date(file_created)
        if file_dt and dt:
            diff_sec = abs((file_dt - dt).total_seconds())
            if diff_sec <= 3600:
                score += 50
            elif diff_sec <= 14400:
                score += 30
            elif diff_sec <= 43200:
                score += 10
                
        if score > best_score:
            best_score = score
            best_file = f
            
    if best_file and best_score >= 0:
        print(f"🎯 Best match found: '{best_file.get('name')}' (ID: {best_file.get('id')}) with score {best_score}")
        return best_file.get("id")
        
    return None

def download_and_convert_recording(user_id, file_id):
    """
    Downloads MP4 recording from Google Drive, uploads to storage, converts to audio, uploads audio.
    Returns (recording_url, audio_url)
    """
    headers = get_authenticated_headers(user_id)
    if not headers:
        raise Exception("Google account not connected or authorization failed")
        
    # Download file in chunks
    print(f"📥 Downloading Google Drive file {file_id}...")
    download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    
    res = requests.get(download_url, headers=headers, stream=True, timeout=60)
    if res.status_code != 200:
        raise Exception(f"Failed to download file from Google Drive: {res.text}")
        
    # Create temp file for MP4
    temp_mp4 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    mp4_path = temp_mp4.name
    
    try:
        for chunk in res.iter_content(chunk_size=1024*1024):
            if chunk:
                temp_mp4.write(chunk)
        temp_mp4.close()
        print(f"💾 File downloaded to temporary location: {mp4_path}")
        
        # 1. Upload original MP4 to Supabase Storage
        print("📤 Uploading MP4 video to Supabase Storage...")
        recording_url = upload_local_file_to_storage(mp4_path, "video/mp4")
        print(f"✅ Video uploaded: {recording_url}")
        
        # 2. Extract audio from MP4 using pydub
        print("🎵 Extracting audio from MP4...")
        audio = AudioSegment.from_file(mp4_path)
        
        # Create temp file for MP3
        temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        mp3_path = temp_mp3.name
        temp_mp3.close()
        
        audio.export(mp3_path, format="mp3")
        print(f"💾 Audio extracted to: {mp3_path}")
        
        # 3. Upload MP3 to Supabase Storage
        print("📤 Uploading audio to Supabase Storage...")
        audio_url = upload_local_file_to_storage(mp3_path, "audio/mpeg")
        print(f"✅ Audio uploaded: {audio_url}")
        
        # Cleanup
        try:
            os.remove(mp4_path)
            os.remove(mp3_path)
        except Exception as e:
            print(f"Warning: failed to delete temp files: {e}")
            
        return recording_url, audio_url
        
    except Exception as e:
        # Ensure cleanup in case of failure
        temp_mp4.close()
        if os.path.exists(mp4_path):
            try:
                os.remove(mp4_path)
            except:
                pass
        raise e
