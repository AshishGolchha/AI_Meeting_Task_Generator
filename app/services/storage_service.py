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