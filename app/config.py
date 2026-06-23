import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = "enterprise-secret-key"

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

    STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

    TRANSCRIBE_CHUNK_THRESHOLD_SEC = 600
    TRANSCRIBE_CHUNK_SIZE_SEC = 300
    MAX_RECORDING_HOURS = 4