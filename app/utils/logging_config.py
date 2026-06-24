import logging
import json
import datetime
from flask import has_request_context, session

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "line": record.lineno
        }
        
        # Add exception details if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        # Add context details if in request context
        if has_request_context():
            try:
                log_data["user_id"] = session.get("user_id")
                log_data["org_id"] = session.get("org_id")
            except Exception:
                pass
                
        return json.dumps(log_data)

def setup_logging():
    """Configures structured JSON logging for the application."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    
    root_logger = logging.getLogger()
    # Remove default handlers to avoid duplicate logs
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
        
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    # Optional: reduce verbosity of internal libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    
    print("[Logging Config] Structured JSON logging initialized.")
