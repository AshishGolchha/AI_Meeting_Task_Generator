import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

    STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Queue chunking & rate limit parameters
    TRANSCRIBE_CHUNK_THRESHOLD_SEC = int(os.getenv("TRANSCRIBE_CHUNK_THRESHOLD_SEC", 600))
    TRANSCRIBE_CHUNK_SIZE_SEC = int(os.getenv("TRANSCRIBE_CHUNK_SIZE_SEC", 300))
    MAX_RECORDING_HOURS = int(os.getenv("MAX_RECORDING_HOURS", 4))
    MAX_CHUNK_COUNT = int(os.getenv("MAX_CHUNK_COUNT", 48))  # 4 hours at 5-min chunks
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB limit
    LOCK_TIMEOUT_MINUTES = 30
    MAX_PROCESSING_TIMEOUT_MINUTES = 30
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")

    # Cron / Webhook secrets for execution protection
    QUEUE_PROCESSING_SECRET = os.getenv("QUEUE_PROCESSING_SECRET")
    CRON_SECRET = os.getenv("CRON_SECRET")
    WORKER_POLL_INTERVAL_SEC = int(os.getenv("WORKER_POLL_INTERVAL_SEC", 5))


def validate_required_secrets():
    missing = []
    if not Config.SECRET_KEY:
        missing.append("SECRET_KEY")
    if os.getenv("FLASK_ENV") == "production" and not Config.QUEUE_PROCESSING_SECRET:
        missing.append("QUEUE_PROCESSING_SECRET")
    if os.getenv("FLASK_ENV") == "production" and not Config.CRON_SECRET:
        missing.append("CRON_SECRET")

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
