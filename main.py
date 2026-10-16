"""BAMS application factory and lifecycle extension points."""

import atexit
import logging
import os
from typing import Any

from flask import Flask, jsonify

from .config import Settings
from .config import load_settings
from .api.admin_routes import admin_blueprint
from .api.exam_routes import exam_blueprint
from .api.ops_routes import ops_blueprint
from .api.proctor_routes import proctor_blueprint
from .hooks.audit_hook import NullAuditSink
from .hooks.auth_hook import access_control_status
from .hooks.events import EventBus
from .engine_service.process import EngineSupervisor


LOGGER = logging.getLogger("bams.app")


def create_app(settings: Settings | None = None) -> Any:
    """Create the HTTP application and register routes and lifecycle hooks."""
    resolved_settings = settings or load_settings()
    app = Flask(__name__)
    app.config.from_mapping(
        BAMS_SETTINGS=resolved_settings,
        PHASE3_ACCESS_CONTROL=resolved_settings.phase3_access_control,
        PHASE3_AUDIT_LOG=resolved_settings.phase3_audit_log,
        PHASE3_DASHBOARD=resolved_settings.phase3_dashboard,
    )

    app.register_blueprint(exam_blueprint)
    app.register_blueprint(proctor_blueprint)
    app.register_blueprint(admin_blueprint)
    app.register_blueprint(ops_blueprint)

    app.extensions["bams_features"] = {
        "PHASE3_ACCESS_CONTROL": resolved_settings.phase3_access_control,
        "PHASE3_AUDIT_LOG": resolved_settings.phase3_audit_log,
        "PHASE3_DASHBOARD": resolved_settings.phase3_dashboard,
    }
    app.extensions["bams_event_bus"] = EventBus()
    app.extensions["bams_audit_sink"] = NullAuditSink()
    app.extensions["bams_auth_status"] = access_control_status()
    supervisor = EngineSupervisor(resolved_settings)
    app.extensions["bams_engine"] = supervisor
    if os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true"):
        supervisor.start()

    if os.environ.get("WERKZEUG_RUN_MAIN") in (None, "true"):
        atexit.register(supervisor.stop)

    @app.get("/health")
    def health() -> Any:
        """Report app configuration and the separate engine worker state."""
        engine = supervisor.health()
        payload = {
            "status": "ok" if engine["status"] == "ok" else "unavailable",
            "features": app.extensions["bams_features"],
            "engine": engine,
        }
        return jsonify(payload), (200 if engine["status"] == "ok" else 503)

    LOGGER.info("BAMS application created with engine backend=%s", supervisor.backend)
    return app