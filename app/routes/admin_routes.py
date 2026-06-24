import datetime

from flask import Blueprint, request, jsonify, current_app
from ..services.cleanup_service import run_soft_delete_sweeper, run_differential_storage_sweeper, run_local_tmp_sweeper

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/cleanup", methods=["POST"])
def admin_cleanup():
    # Protected Cleanup Endpoint
    cron_secret = current_app.config.get("CRON_SECRET")
    inbound_secret = request.headers.get("X-Cron-Secret")
    
    if not inbound_secret or inbound_secret != cron_secret:
        source_ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
        current_app.logger.warning(
            "Forbidden cleanup attempt at %s from %s",
            datetime.datetime.utcnow().isoformat(),
            source_ip,
        )
        return jsonify({"error": "Forbidden"}), 403
        
    try:
        run_soft_delete_sweeper()
        run_differential_storage_sweeper()
        run_local_tmp_sweeper()
        return jsonify({"status": "cleanup_completed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
