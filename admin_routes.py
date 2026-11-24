"""Student and baseline management routes with Phase 3 role hooks."""

import math
import time
from typing import Any, Mapping

from flask import Blueprint, current_app, jsonify, request

from app.engine_service.process import EngineUnavailable
from app.hooks.auth_hook import access_control_label, requires_role
from app.services.baseline_service import BaselineService
from app.services.engine_adapters import EngineBaselineStorage
from python.ml.baseline_engine import BaselineEngine, SIGNALS
from python.synthetic.data_generator import SyntheticDataGenerator


admin_blueprint = Blueprint("admin", __name__)


def _response(payload: dict[str, Any], status: int = 200) -> tuple[Any, int]:
    return jsonify({**payload, "access_control": access_control_label()}), status


def _history_rows(student_id: int, session_count: int) -> list[dict[str, float]]:
    generator = SyntheticDataGenerator(seed=6101)
    rows: list[dict[str, float]] = []
    current: dict[str, float] = {}
    for session in generator.practice_history(student_id, session_count):
        for event in session.events:
            signal = str(event["signal"])
            if signal in SIGNALS:
                current[signal] = float(event["value"])
            if len(current) == len(SIGNALS):
                rows.append(current)
                current = {}
    return rows


def _baseline_service() -> BaselineService:
    engine = current_app.extensions["bams_engine"].client
    storage = EngineBaselineStorage(engine, source="synthetic")
    return BaselineService(BaselineEngine(storage), None)


@admin_blueprint.post("/admin/students")
@requires_role("admin")
def add_student() -> Any:
    payload = request.get_json(silent=True)
    if not isinstance(payload, Mapping):
        return _response({"error": "JSON object required"}, 400)
    student_id = payload.get("student_id")
    if (
        isinstance(student_id, bool)
        or not isinstance(student_id, int)
        or student_id <= 0
    ):
        return _response({"error": "student_id must be a positive integer"}, 400)

    engine = current_app.extensions["bams_engine"].client
    try:
        records = engine.read_records(student_id, 0, 100000)
        if records:
            return _response({"error": "student already exists"}, 409)
        engine.write_event({
            "record_type": "student",
            "schema_version": 1,
            "student_id": student_id,
            "source": "admin",
        })
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)
    except RuntimeError as error:
        return _response({"error": f"engine error: {error}"}, 500)
    return _response({"student_id": student_id, "status": "created"}, 201)


@admin_blueprint.post("/admin/students/<int:student_id>/baseline")
@requires_role("admin")
def rebuild_baseline(student_id: int) -> Any:
    payload = request.get_json(silent=True)
    if payload is not None and not isinstance(payload, Mapping):
        return _response({"error": "JSON object required"}, 400)
    payload = payload or {}

    if "history" in payload:
        raw_history = payload["history"]
        source = "synthetic"
        if not isinstance(raw_history, list) or not raw_history:
            return _response({"error": "history must be a non-empty list"}, 400)
        history: list[dict[str, float]] = []
        for row in raw_history:
            if not isinstance(row, Mapping):
                return _response({"error": "each history row must be an object"}, 400)
            values: dict[str, float] = {}
            for signal in SIGNALS:
                value = row.get(signal)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    return _response(
                        {"error": f"history rows require finite {signal} values"},
                        400,
                    )
                values[signal] = float(value)
            history.append(values)
        session_count = len(history)
    else:
        session_count = payload.get("session_count", 5)
        if (
            isinstance(session_count, bool)
            or not isinstance(session_count, int)
            or not 1 <= session_count <= 100
        ):
            return _response(
                {"error": "session_count must be between 1 and 100"}, 400
            )
        history = _history_rows(student_id, session_count)
        source = "synthetic"

    engine = current_app.extensions["bams_engine"].client
    try:
        records = engine.read_records(student_id, 0, 100000)
        if not any(record.get("record_type") == "student" for record in records):
            return _response({"error": "student not found"}, 404)
        service = _baseline_service()
        baseline = service.build(student_id, history)
        engine.write_event({
            "record_type": "baseline_metadata",
            "schema_version": 1,
            "student_id": student_id,
            "session_count": session_count,
            "source": source,
            "timestamp": time.time(),
        })
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)
    except ValueError as error:
        return _response({"error": str(error)}, 400)
    except RuntimeError as error:
        return _response({"error": f"engine error: {error}"}, 500)

    return _response({
        "student_id": student_id,
        "session_count": session_count,
        "source": source,
        "status": "rebuilt",
        "signals": {
            signal: {
                "mean": round(getattr(baseline, signal).mean, 6),
                "std": round(getattr(baseline, signal).std, 6),
            }
            for signal in SIGNALS
        },
    }, 201)


@admin_blueprint.get("/admin/students/<int:student_id>/baseline")
@requires_role("admin")
def get_baseline(student_id: int) -> Any:
    engine = current_app.extensions["bams_engine"].client
    try:
        records = engine.read_records(student_id, 0, 100000)
        if not any(record.get("record_type") == "student" for record in records):
            return _response({"error": "student not found"}, 404)
        baseline = _baseline_service().get(student_id)
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)
    except KeyError:
        return _response({"error": "baseline not found"}, 404)

    metadata = [
        record for record in records
        if record.get("record_type") == "baseline_metadata"
    ]
    latest_metadata = max(
        metadata,
        key=lambda record: int(record["sequence"]),
        default=None,
    )
    session_count = (
        int(latest_metadata["session_count"])
        if latest_metadata is not None else 0
    )
    cold_start = session_count < 3
    return _response({
        "student_id": student_id,
        "session_count": session_count,
        "cold_start": cold_start,
        "provisional": cold_start,
        "source": latest_metadata.get("source") if latest_metadata else None,
        "signals": {
            signal: {
                "mean": getattr(baseline, signal).mean,
                "std": getattr(baseline, signal).std,
            }
            for signal in SIGNALS
        },
    })
