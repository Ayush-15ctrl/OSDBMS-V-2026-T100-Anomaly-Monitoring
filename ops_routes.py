"""Explicitly gated operational routes for the engine worker."""

import time
from typing import Any, Mapping
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from app.engine_service.process import EngineUnavailable
from app.hooks.auth_hook import access_control_label, requires_role
from app.services.engine_adapters import EngineBaselineStorage
from python.core.native import NativeDeadlockDetector
from python.ml.baseline_engine import BaselineEngine, SIGNALS
from python.synthetic.data_generator import SyntheticDataGenerator


ops_blueprint = Blueprint("ops", __name__)


def _response(payload: dict[str, Any], status: int = 200) -> tuple[Any, int]:
    return jsonify({**payload, "access_control": access_control_label()}), status


def _enabled() -> bool:
    return bool(current_app.config["BAMS_OPS_ENABLED"])


def _disabled_response() -> tuple[Any, int]:
    return _response({"error": "ops routes are disabled"}, 403)


@ops_blueprint.post("/ops/crash")
@requires_role("admin")
def crash_engine() -> Any:
    if not _enabled():
        return _disabled_response()
    supervisor = current_app.extensions["bams_engine"]
    process = supervisor.process
    if process is None or not process.is_alive() or process.pid is None:
        return _response({"error": "engine worker is unavailable"}, 503)
    old_pid = process.pid
    process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)
    return _response({"worker_pid": old_pid})


@ops_blueprint.post("/ops/restart-engine")
@requires_role("admin")
def restart_engine() -> Any:
    if not _enabled():
        return _disabled_response()
    supervisor = current_app.extensions["bams_engine"]
    process = supervisor.process
    old_pid = process.pid if process is not None else None
    try:
        supervisor.stop()
        supervisor.start()
        new_pid = supervisor.process.pid if supervisor.process is not None else None
        if new_pid is None:
            return _response({"error": "engine worker failed to restart"}, 503)
        engine_stats = supervisor.client.stats()
    except EngineUnavailable as error:
        return _response({"error": str(error)}, 503)
    return _response({
        "old_worker_pid": old_pid,
        "new_worker_pid": new_pid,
        "records_recovered": int(engine_stats["records"]),
        "engine_stats": engine_stats,
        "wal_replay": {"records_recovered": int(engine_stats["records"])},
    })


@ops_blueprint.post("/ops/load-test")
@requires_role("admin")
def load_test() -> Any:
    if not _enabled():
        return _disabled_response()
    payload = request.get_json(silent=True)
    if not isinstance(payload, Mapping):
        return _response({"error": "JSON object required"}, 400)
    students = payload.get("students")
    events_per_student = payload.get("events_per_student")
    if (
        isinstance(students, bool)
        or not isinstance(students, int)
        or not 1 <= students <= 200
    ):
        return _response({"error": "students must be between 1 and 200"}, 400)
    if (
        isinstance(events_per_student, bool)
        or not isinstance(events_per_student, int)
        or not 1 <= events_per_student <= 1000
    ):
        return _response(
            {"error": "events_per_student must be between 1 and 1000"}, 400
        )

    supervisor = current_app.extensions["bams_engine"]
    engine = supervisor.client
    persistence = current_app.extensions["bams_session_persistence"]
    ingestion = current_app.extensions["bams_ingestion"]
    scoring = current_app.extensions["bams_scoring"]
    existing_sessions = persistence.read_exam_sessions()
    reserved_ids = {
        int(session["student_id"]) for session in existing_sessions.values()
    }
    student_ids: list[int] = []
    candidate = 9000
    try:
        while len(student_ids) < students:
            if candidate not in reserved_ids and not engine.read_records(
                candidate, 0, 1
            ):
                student_ids.append(candidate)
                reserved_ids.add(candidate)
            candidate += 1
        started_at = time.time()
        started_clock = time.perf_counter()
        accepted_events = 0
        errors: list[dict[str, Any]] = []
        for student_id in student_ids:
            session_id = uuid4().hex[:16]
            stage = "baseline"
            try:
                generator = SyntheticDataGenerator(seed=9401)
                practice = generator.practice_history(student_id, 5)
                baseline_rows: list[dict[str, float]] = []
                current: dict[str, float] = {}
                for practice_session in practice:
                    for event in practice_session.events:
                        signal = str(event["signal"])
                        if signal in SIGNALS:
                            current[signal] = float(event["value"])
                        if len(current) == len(SIGNALS):
                            baseline_rows.append(current)
                            current = {}
                BaselineEngine(
                    EngineBaselineStorage(engine, source="synthetic")
                ).build(student_id, baseline_rows)
                stage = "student"
                engine.write_event({
                    "record_type": "student",
                    "schema_version": 1,
                    "student_id": student_id,
                    "source": "synthetic",
                })
                stage = "session"
                persistence.create_exam_session(
                    session_id,
                    student_id,
                    "ops-load-test",
                    started_at,
                    float(current_app.config["BAMS_SESSION_TIMEOUT_SECONDS"]),
                    source="synthetic",
                )
                paste_events = generator.exam_session(
                    student_id, "paste"
                ).events
                stage = "ingestion"
                for event_index in range(events_per_student):
                    event = paste_events[event_index % len(paste_events)]
                    ingestion.ingest(
                        student_id,
                        str(event["signal"]),
                        float(event["value"]),
                        metadata={"source": "synthetic"},
                    )
                    accepted_events += 1
                stage = "finalize"
                scoring.finalize_session(student_id, source="synthetic")
            except (EngineUnavailable, RuntimeError, ValueError) as error:
                errors.append({
                    "student_id": student_id,
                    "stage": stage,
                    "error": str(error),
                })
        elapsed = time.perf_counter() - started_clock
    except EngineUnavailable as error:
        return _response({"error": str(error)}, 503)
    return _response({
        "students": student_ids,
        "events_requested": students * events_per_student,
        "events_ingested": accepted_events,
        "events_per_second": accepted_events / elapsed,
        "elapsed_seconds": elapsed,
        "error_count": len(errors),
        "errors": errors,
    })


@ops_blueprint.post("/ops/deadlock-demo")
@requires_role("admin")
def deadlock_demo() -> Any:
    if not _enabled():
        return _disabled_response()
    detector_commands = [
        "acquire 1 100",
        "acquire 2 200",
        "wait 1 200",
        "wait 2 100",
    ]
    try:
        detector = NativeDeadlockDetector()
    except FileNotFoundError:
        return _response({
            "error": (
                "not implemented: run cpp_core/build/deadlock_demo.exe"
            )
        }, 501)

    detected = detector.detect_cycle(detector_commands)
    recovery = detector.detect_cycle(
        detector_commands
        + [
            "wait_done 2 100",
            "release 2 200",
            "wait_done 1 200",
            "acquire 1 200",
            "release 1 200",
            "release 1 100",
        ]
    )
    return _response({
        "cycle": detected["cycle"],
        "victim": detected["victim"],
        "survivor_finished": (
            detected["victim"] == 2 and recovery["cycle"] == []
        ),
    })


@ops_blueprint.get("/ops/stats")
@requires_role("admin")
def get_stats() -> Any:
    if not _enabled():
        return _disabled_response()
    supervisor = current_app.extensions["bams_engine"]
    persistence = current_app.extensions["bams_session_persistence"]
    engine = supervisor.client
    try:
        engine_stats = engine.stats()
        sessions = persistence.read_exam_sessions()
        student_ids = {
            int(session["student_id"]) for session in sessions.values()
        }
        records = [
            record
            for student_id in sorted(student_ids)
            for record in engine.read_records(student_id, 0, 100000)
        ]
    except EngineUnavailable as error:
        return _response({"error": str(error)}, 503)
    finalize_records = [
        record for record in records
        if record.get("record_type") == "finalize"
    ]
    return _response({
        "engine": engine_stats,
        "students": len(student_ids),
        "sessions": len(sessions),
        "finalize_records": len(finalize_records),
        "flags": sum(1 for record in finalize_records if record.get("flagged")),
    })