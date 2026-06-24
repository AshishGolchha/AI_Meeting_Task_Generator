from flask import Flask, session
from .config import Config
from .utils.logging_config import setup_logging
from .utils.async_runner import start_background_worker, recover_crashed_jobs

def create_app():
    # 1. Initialize structured logging
    setup_logging()

    app = Flask(__name__)
    app.config.from_object(Config)

    @app.context_processor
    def inject_user():
        return dict(
            current_user=session.get("user_id"),
            current_org=session.get("org_id"),
            current_role=session.get("role")
        )

    # Register routes
    from .routes.meeting_routes import meeting_bp
    from .routes.task_routes import task_bp
    from .routes.analytics_routes import analytics_bp
    from .routes.dashboard_routes import dashboard_bp
    from .routes.auth_routes import auth_bp
    from .routes.org_routes import org_bp

    app.register_blueprint(meeting_bp, url_prefix="/api/meetings")
    app.register_blueprint(task_bp, url_prefix="/api/tasks")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(org_bp)

    # 2. Run Startup Recovery Routine to release crashed jobs
    with app.app_context():
        recover_crashed_jobs(app)

    # 3. Start DB-Queue asynchronous processing daemon
    start_background_worker(app)

    return app
