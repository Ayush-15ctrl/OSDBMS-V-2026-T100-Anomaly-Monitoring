"""Proctor views backed by persisted scoring and session records."""

from dataclasses import asdict
import json
import time
from typing import Any, Iterator

from flask import Blueprint, Response, current_app, jsonify, stream_with_context

from app.engine_service.process import EngineUnavailable
from app.hooks.auth_hook import access_control_label, requires_role
from app.services.feature_vector import build_session_feature_vector, complete_question_count
from python.ml.baseline_engine import BaselineProfile, SIGNALS, SignalBaseline


proctor_blueprint = Blueprint("proctor", __name__)
_PROCTOR_ROLES = ("proctor", "admin")


def _response(payload: dict[str, Any], status: int = 200) -> tuple[Any, int]:
    return jsonify({**payload, "access_control": access_control_label()}), status


def _decision(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "student_id": int(record["student_id"]),
        "risk_score": record["risk_score"],
        "flagged": bool(record["flagged"]),
        "timestamp": float(record["timestamp"]),
        "source": record["source"],
    }


@proctor_blueprint.get("/proctor/flags")
@requires_role(_PROCTOR_ROLES)
def get_flags() -> Any:
    persistence = current_app.extensions["bams_session_persistence"]
    engine = current_app.extensions["bams_engine"].client
    try:
        sessions = persistence.read_exam_sessions()
        known_students = {int(session["student_id"]) for session in sessions.values()}
        flags = [
            _decision(record)
            for student_id in sorted(known_students)
            for record in engine.read_records(student_id, 0, 100000)
            if record.get("record_type") == "finalize" and record.get("flagged")
        ]
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)
    flags.sort(key=lambda item: (item["timestamp"], item["student_id"]))
    return _response({"flags": flags})


@proctor_blueprint.get("/proctor/student/<int:student_id>")
@requires_role(_PROCTOR_ROLES)
def get_student(student_id: int) -> Any:
    scoring = current_app.extensions["bams_scoring"]
    finalization_storage = current_app.extensions["bams_finalize_storage"]
    try:
        stored = finalization_storage.read_record(student_id)
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)

    latest = scoring.latest_result(student_id)
    current_risk = None
    explanation = None
    explanation_reason = (
        "Per-signal explanation is not persisted and is unavailable after restart."
    )
    if latest is not None:
        current_risk = {
            "risk_score": latest.risk_score,
            "multivariate_score": latest.multivariate_score,
            "timestamp": latest.timestamp,
            "status": latest.status,
        }
        if latest.signal_results:
            explanation = [asdict(result) for result in latest.signal_results]
            explanation_reason = None
    elif stored is not None:
        current_risk = {
            "risk_score": stored["risk_score"],
            "multivariate_score": None,
            "timestamp": stored["timestamp"],
            "status": "finalized",
        }

    return _response({
        "student_id": student_id,
        "current_risk": current_risk,
        "finalize": _decision(stored) if stored is not None else None,
        "explanation": explanation,
        "explanation_reason": explanation_reason,
    })


@proctor_blueprint.get("/proctor/student/<int:student_id>/series")
@requires_role(_PROCTOR_ROLES)
def get_student_series(student_id: int) -> Any:
    engine = current_app.extensions["bams_engine"].client
    try:
        records = engine.read_records(student_id, 0, 100000)
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)

    if not any(record.get("record_type") == "student" for record in records):
        return _response({"error": "student not found"}, 404)

    baseline_values = _latest_baseline(records)
    signal_data: dict[str, dict[str, Any]] = {}
    question_events: dict[int, list[dict[str, Any]]] = {}
    points_by_signal: dict[str, dict[int, dict[str, Any]]] = {
        signal: {} for signal in SIGNALS
    }
    legacy_question_by_signal = {signal: 0 for signal in SIGNALS}

    for record in sorted(records, key=lambda item: int(item.get("sequence", 0))):
        if record.get("record_type") != "event":
            continue
        metadata = record.get("metadata")
        question_value = metadata.get("q") if isinstance(metadata, dict) else None
        signal = record.get("signal")
        if signal not in points_by_signal:
            continue
        if isinstance(question_value, str) and question_value.isdigit():
            question = int(question_value)
        else:
            legacy_question_by_signal[signal] += 1
            question = legacy_question_by_signal[signal]
        value = float(record["value"])
        timestamp = float(record.get("timestamp", 0.0))
        question_events.setdefault(question, []).append({
            "signal": signal,
            "value": value,
            "timestamp": timestamp,
            "sequence": int(record["sequence"]),
        })
        points_by_signal[signal][question] = {
            "question": question,
            "value": round(value, 4),
        }

    for signal in SIGNALS:
        baseline = baseline_values.get(signal)
        baseline_mean = baseline["mean"] if baseline is not None else None
        baseline_std = baseline["std"] if baseline is not None else None
        response_mean = (
            round(baseline_mean, 4) if baseline_mean is not None else None
        )
        response_std = (
            round(baseline_std, 4) if baseline_std is not None else None
        )
        points = []
        for question, point in sorted(points_by_signal[signal].items())[-200:]:
            z = (
                round((point["value"] - response_mean) / response_std, 4)
                if response_mean is not None
                and response_std not in (None, 0)
                else None
            )
            points.append({**point, "z": z})
        z_values = [
            point["z"] for point in points
            if isinstance(point["z"], (int, float))
        ]
        signal_data[signal] = {
            "baseline_mean": response_mean,
            "baseline_std": response_std,
            "points": points,
            "mean_z": (
                round(sum(z_values) / len(z_values), 4)
                if z_values else None
            ),
            "min_z": round(min(z_values), 4) if z_values else None,
            "max_z": round(max(z_values), 4) if z_values else None,
        }

    risk_points: list[dict[str, float]] = []
    cumulative: list[dict[str, Any]] = []
    by_signal: dict[str, list[float]] = {signal: [] for signal in SIGNALS}
    complete_questions = 0
    scoring = current_app.extensions["bams_scoring"]
    for question in sorted(question_events):
        events = sorted(
            question_events[question], key=lambda event: event["sequence"]
        )
        for event in events:
            by_signal[event["signal"]].append(event["value"])
        complete_questions = complete_question_count(by_signal)
    by_signal = {signal: [] for signal in SIGNALS}
    if len(baseline_values) == len(SIGNALS) and all(
        values["std"] != 0 for values in baseline_values.values()
    ):
        baseline = BaselineProfile(
            student_id=student_id,
            **{
                signal: SignalBaseline(
                    baseline_values[signal]["mean"],
                    baseline_values[signal]["std"],
                )
                for signal in SIGNALS
            },
        )
        for question in sorted(question_events):
            events = sorted(
                question_events[question], key=lambda event: event["sequence"]
            )
            cumulative.extend(events)
            for event in events:
                by_signal[event["signal"]].append(event["value"])
            complete_questions = complete_question_count(by_signal)
            if complete_questions < scoring.minimum_questions:
                continue
            vector = build_session_feature_vector(cumulative, baseline)
            prediction = scoring.risk_scorer.predict_risk(vector)
            risk_points.append({
                "t": round(max(event["timestamp"] for event in events), 3),
                "score": round(float(prediction.probability), 4),
            })

    finalization_records = [
        record for record in records
        if record.get("record_type") == "finalize"
    ]
    finalization = (
        max(finalization_records, key=lambda record: int(record["sequence"]))
        if finalization_records else None
    )
    final_payload = (
        {
            "risk_score": finalization.get("risk_score"),
            "flagged": bool(finalization.get("flagged")),
        }
        if finalization is not None else None
    )
    latest = current_app.extensions["bams_scoring"].latest_result(student_id)
    current_payload = (
        {
            "risk_score": latest.risk_score,
            "status": latest.status,
        }
        if latest is not None else None
    )

    return _response({
        "student_id": student_id,
        "risk_threshold": scoring.risk_threshold,
        "minimum_questions": scoring.minimum_questions,
        "scored_questions": complete_questions,
        "risk": risk_points[-200:],
        "signals": signal_data,
        "final": final_payload,
        "current": current_payload,
    })


def _latest_baseline(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[int, dict[str, dict[str, float]]]] = []
    for record in records:
        if record.get("record_type") != "baseline":
            continue
        sequence = int(record.get("sequence", 0))
        signals = record.get("signals")
        if isinstance(signals, dict):
            candidates.append((
                sequence,
                {
                    signal: {
                        "mean": float(values["mean"]),
                        "std": float(values["std"]),
                    }
                    for signal, values in signals.items()
                    if signal in SIGNALS and isinstance(values, dict)
                },
            ))
            continue
        signal = record.get("signal")
        if signal is None and "signal_index" in record:
            index = int(record["signal_index"])
            signal = SIGNALS[index] if 0 <= index < len(SIGNALS) else None
        if signal not in SIGNALS:
            continue
        group = str(record.get("bid", record.get("baseline_id", sequence)))
        entry = grouped.setdefault(group, {"sequence": sequence, "signals": {}})
        entry["sequence"] = max(int(entry["sequence"]), sequence)
        entry["signals"][signal] = {
            "mean": float(record["mean"]),
            "std": float(record["std"]),
        }
    candidates.extend(
        (int(entry["sequence"]), entry["signals"])
        for entry in grouped.values()
    )
    return max(candidates, key=lambda item: item[0])[1] if candidates else {}


def _sse_event(name: str, payload: dict[str, Any]) -> str:
    data = json.dumps({**payload, "access_control": access_control_label()})
    return f"event: {name}\ndata: {data}\n\n"


@proctor_blueprint.get("/proctor/stream")
@requires_role(_PROCTOR_ROLES, allow_stream_query=True)
def stream_proctor_events() -> Any:
    persistence = current_app.extensions["bams_session_persistence"]
    engine = current_app.extensions["bams_engine"].client
    try:
        persistence.read_exam_sessions()
    except EngineUnavailable:
        return _response({"error": "engine unavailable"}, 503)

    @stream_with_context
    def events() -> Iterator[str]:
        emitted_flags: set[int] = set()
        finalized_students: set[int] = set()
        try:
            while True:
                try:
                    sessions = persistence.read_exam_sessions()
                    by_student: dict[int, list[dict[str, Any]]] = {}
                    for session in sessions.values():
                        by_student.setdefault(
                            int(session["student_id"]), []
                        ).append(session)

                    for student_id, student_sessions in by_student.items():
                        if student_id in finalized_students:
                            continue
                        records = engine.read_records(student_id, 0, 100000)
                        decisions = [
                            record for record in records
                            if record.get("record_type") == "finalize"
                        ]
                        if decisions:
                            decision = max(
                                decisions,
                                key=lambda record: int(record["sequence"]),
                            )
                            finalized_students.add(student_id)
                            if (
                                decision.get("flagged")
                                and student_id not in emitted_flags
                            ):
                                emitted_flags.add(student_id)
                                yield _sse_event("flag", _decision(decision))
                            continue

                        active_session = next(
                            (
                                session for session in student_sessions
                                if not session["submitted"]
                                and not session["timed_out"]
                                and float(session["started_at"])
                                + float(session["timeout_seconds"])
                                > time.time()
                            ),
                            None,
                        )
                        if active_session is None:
                            continue
                        latest = current_app.extensions[
                            "bams_scoring"
                        ].latest_result(student_id)
                        yield _sse_event("current_risk", {
                            "student_id": student_id,
                            "risk_score": (
                                latest.risk_score if latest is not None else None
                            ),
                            "timestamp": (
                                latest.timestamp if latest is not None else None
                            ),
                            "status": (
                                latest.status if latest is not None else "unscored"
                            ),
                        })
                    yield _sse_event("tick", {})
                except EngineUnavailable:
                    yield _sse_event("error", {"error": "engine unavailable"})
                    return
                time.sleep(1.0)
        finally:
            emitted_flags.clear()
            finalized_students.clear()

    response = Response(events(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Access-Control"] = access_control_label()
    return response
