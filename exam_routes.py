"""Student-facing exam routes; one exam per student per engine.

Responses never expose risk scores or anomaly flags.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Mapping
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from app.engine_service.process import EngineUnavailable
from app.hooks.auth_hook import requires_role, student_owns_resource


exam_blueprint = Blueprint("exam", __name__)


@dataclass
class ExamSession:
    session_id: str
    student_id: int
    exam_id: str
    started_at: float
    timeout_seconds: float
    timed_out: bool = False
    submitted: bool = False

    def remaining_seconds(self) -> int:
        remaining = self.timeout_seconds - (time.time() - self.started_at)
        return max(0, math.ceil(remaining))

    def is_expired(self) -> bool:
        return self.remaining_seconds() == 0


def _error(message: str, status: int) -> tuple[Any, int]:
    return jsonify({"error": message}), status


def _session(session_id: str) -> ExamSession | None:
    sessions = current_app.extensions["bams_exam_sessions"]
    session = sessions.get(session_id)
    if session is not None:
        return session
    restored = current_app.extensions["bams_session_persistence"].read_exam_session(
        session_id
    )
    if restored is None:
        return None
    session = ExamSession(
        session_id=restored["session_id"],
        student_id=restored["student_id"],
        exam_id=restored["exam_id"],
        started_at=restored["started_at"],
        timeout_seconds=restored["timeout_seconds"],
        timed_out=restored["timed_out"],
        submitted=restored["submitted"],
    )
    sessions[session_id] = session
    return session


def _public_session(session: ExamSession) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "student_id": session.student_id,
        "exam_id": session.exam_id,
        "status": (
            "timed_out" if session.timed_out
            else "submitted" if session.submitted
            else "active"
        ),
        "remaining_seconds": session.remaining_seconds(),
    }


def _finalize_timeout(session: ExamSession) -> None:
    if session.is_expired() and not session.timed_out and not session.submitted:
        current_app.extensions["bams_scoring"].finalize_session(session.student_id)
        session.timed_out = True
        current_app.extensions["bams_session_persistence"].update_exam_session(
            session.session_id,
            session.student_id,
            session.submitted,
            session.timed_out,
        )


def _request_object() -> Mapping[str, Any] | None:
    value = request.get_json(silent=True)
    return value if isinstance(value, Mapping) else None


@exam_blueprint.post("/api/session/start")
@requires_role("student")
def start_session() -> Any:
    payload = _request_object()
    if payload is None:
        return _error("JSON object required", 400)
    if "timeout_seconds" in payload:
        return _error("timeout_seconds is server-configured", 400)
    student_id = payload.get("student_id")
    exam_id = payload.get("exam_id", "exam")
    if isinstance(student_id, bool) or not isinstance(student_id, int) or student_id <= 0:
        return _error("student_id must be a positive integer", 400)
    if not student_owns_resource(student_id):
        return _error("student does not own this identity", 403)
    if not isinstance(exam_id, str) or not exam_id or len(exam_id) > 40:
        return _error("exam_id must be a non-empty string of at most 40 characters", 400)
    try:
        if current_app.extensions["bams_finalize_storage"].read_record(student_id) is not None:
            return _error("student already finalized an exam on this engine", 409)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    try:
        current_app.extensions["bams_scoring"].anomaly_detector.baselines.load(
            student_id
        )
    except KeyError:
        return _error("no baseline for this student; create one first", 409)
    except EngineUnavailable:
        return _error("engine unavailable", 503)

    started_at = time.time()
    session = ExamSession(
        uuid4().hex[:16],
        student_id,
        exam_id,
        started_at,
        float(current_app.config["BAMS_SESSION_TIMEOUT_SECONDS"]),
    )
    try:
        current_app.extensions["bams_session_persistence"].create_exam_session(
            session.session_id,
            session.student_id,
            session.exam_id,
            session.started_at,
            session.timeout_seconds,
        )
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    current_app.extensions["bams_exam_sessions"][session.session_id] = session
    return jsonify(_public_session(session)), 201


@exam_blueprint.post("/api/events")
@requires_role("student")
def post_event() -> Any:
    payload = _request_object()
    if payload is None:
        return _error("JSON object required", 400)
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return _error("session_id is required", 400)
    try:
        session = _session(session_id)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    if session is None:
        return _error("session not found", 404)
    if not student_owns_resource(session.student_id):
        return _error("student does not own this session", 403)
    try:
        _finalize_timeout(session)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    if session.timed_out or session.submitted:
        return _error("session is closed", 409)
    student_id = payload.get("student_id", session.student_id)
    if type(student_id) is not int or student_id != session.student_id:
        return _error("student does not own this session", 403)
    signal = payload.get("signal")
    value = payload.get("value")
    if not isinstance(signal, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return _error("signal and numeric value are required", 400)
    question = payload.get("question")
    if question is not None and (
        type(question) is not int or question < 1
    ):
        return _error("question must be a positive integer", 400)
    metadata = {"q": str(question)} if question is not None else None
    try:
        result = current_app.extensions["bams_ingestion"].ingest(
            session.student_id,
            signal,
            float(value),
            metadata=metadata,
        )
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    except (TypeError, ValueError):
        return _error("invalid event", 400)
    return jsonify({
        "event_id": result.event_id,
        "server_timestamp": result.server_timestamp,
        "status": "accepted",
    }), 202


@exam_blueprint.get("/api/session/<session_id>")
@requires_role("student")
def get_session(session_id: str) -> Any:
    try:
        session = _session(session_id)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    if session is None:
        return _error("session not found", 404)
    if not student_owns_resource(session.student_id):
        return _error("student does not own this session", 403)
    try:
        _finalize_timeout(session)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    return jsonify(_public_session(session))


@exam_blueprint.post("/api/session/submit")
@requires_role("student")
def submit_session() -> Any:
    payload = _request_object()
    if payload is None:
        return _error("JSON object required", 400)
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return _error("session_id is required", 400)
    try:
        session = _session(session_id)
    except EngineUnavailable:
        return _error("engine unavailable", 503)
    if session is None:
        return _error("session not found", 404)
    if not student_owns_resource(session.student_id):
        return _error("student does not own this session", 403)
    session.submitted = True
    try:
        current_app.extensions["bams_scoring"].finalize_session(session.student_id)
    except EngineUnavailable:
        session.submitted = False
        return _error("engine unavailable", 503)
    try:
        current_app.extensions["bams_session_persistence"].update_exam_session(
            session.session_id,
            session.student_id,
            session.submitted,
            session.timed_out,
        )
    except EngineUnavailable:
        session.submitted = False
        return _error("engine unavailable", 503)
    return jsonify({"session_id": session.session_id, "status": "submitted"})