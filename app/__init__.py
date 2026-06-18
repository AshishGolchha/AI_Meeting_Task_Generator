from flask import Flask, session
from .config import Config

def create_app():
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

    return app
