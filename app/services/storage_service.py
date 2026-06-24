import uuid
from ..utils.supabase_client import get_supabase
from flask import current_app

def upload_audio_to_storage(file):

    supabase = get_supabase()

    bucket = current_app.config["STORAGE_BUCKET"]

    file_ext = file.filename.split(".")[-1]
    file_name = f"{uuid.uuid4()}.{file_ext}"

    path = f"meetings/{file_name}"

    supabase.storage.from_(bucket).upload(
        path,
        file.read(),
        {"content-type": file.content_type}
    )

    public_url = supabase.storage.from_(bucket).get_public_url(path)

    return public_url


def upload_local_file_to_storage(file_path, content_type):
    import os
    supabase = get_supabase()
    bucket = current_app.config["STORAGE_BUCKET"]
    
    file_ext = file_path.split(".")[-1]
    file_name = f"{uuid.uuid4()}.{file_ext}"
    path = f"meetings/{file_name}"
    
    with open(file_path, "rb") as f:
        supabase.storage.from_(bucket).upload(
            path,
            f,
            {"content-type": content_type}
        )
        
    public_url = supabase.storage.from_(bucket).get_public_url(path)
    return public_url


def delete_audio_from_storage(audio_url):
    if not audio_url:
        return
        
    try:
        supabase = get_supabase()
        try:
            bucket = current_app.config["STORAGE_BUCKET"]
        except Exception:
            bucket = "meetings-audio"
            
        filename = audio_url.split("/")[-1]
        path = f"meetings/{filename}"
        
        supabase.storage.from_(bucket).remove([path])
        print(f"[Storage Service] Deleted remote storage audio file: {path}")
    except Exception as e:
        print(f"[Storage Service] Error deleting file from storage: {e}")