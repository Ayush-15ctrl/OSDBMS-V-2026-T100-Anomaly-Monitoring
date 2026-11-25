"""Adapters from the Phase 2 engine client to service-layer protocols."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
import time
from uuid import uuid4
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from python.ingestion.event_collector import BehaviorEvent
from python.ml.baseline_engine import SIGNALS


class EngineBaselineStorage:
    """Student-scoped baseline storage backed by typed engine event records."""

    def __init__(self, engine: Any, source: str | None = None) -> None:
        self.engine = engine
        self.source = source

    def write_record(self, student_id: int, event: object) -> int:
        payload = dict(event) if isinstance(event, Mapping) else asdict(event) if is_dataclass(event) else {"value": event}
        signals = payload.get("signals")
        if isinstance(signals, Mapping):
            group_id = uuid4().hex[:8]
            sequence = 0
            for signal, statistics in signals.items():
                signal_name = str(signal)
                signal_field = (
                    {"signal_index": SIGNALS.index(signal_name)}
                    if signal_name in SIGNALS
                    else {"signal": signal_name}
                )
                mean = round(float(statistics["mean"]), 6)
                raw_std = float(statistics["std"])
                std = round(raw_std, 6)
                if 0 < raw_std and std == 0.0:
                    std = 0.000001
                result = self.engine.write_event({
                    "record_type": "baseline",
                    "schema_version": 1,
                    "student_id": int(student_id),
                    "bid": group_id,
                    **signal_field,
                    "mean": mean,
                    "std": std,
                    **({"source": self.source} if self.source is not None else {}),
                })
                sequence = int(result["sequence"])
            return sequence
        result = self.engine.write_event({
            "record_type": "baseline",
            "schema_version": 1,
            "student_id": int(student_id),
            **payload,
            **({"source": self.source} if self.source is not None else {}),
        })
        return int(result["sequence"])

    def read_records(self, student_id: int, offset: int, count: int) -> list[object]:
        records = self.engine.read_records(int(student_id), offset, count)
        baselines = []
        grouped: dict[str, dict[str, object]] = {}
        for record in records:
            if record.get("record_type") != "baseline":
                continue
            group_id_value = record.get("bid", record.get("baseline_id"))
            if group_id_value is not None and (
                "signal" in record or "signal_index" in record
            ):
                signal = (
                    str(record["signal"])
                    if "signal" in record
                    else SIGNALS[int(record["signal_index"])]
                )
                group_id = str(group_id_value)
                grouped.setdefault(group_id, {
                    "record_type": "baseline",
                    "schema_version": record["schema_version"],
                    "student_id": record["student_id"],
                    "signals": {},
                    "sequence": record["sequence"],
                    **(
                        {"source": record["source"]}
                        if "source" in record else {}
                    ),
                })
                grouped[group_id]["signals"][signal] = {  # type: ignore[index]
                    "mean": record["mean"],
                    "std": record["std"],
                }
            else:
                baselines.append(record)
        baselines.extend(grouped.values())
        return sorted(baselines, key=lambda record: int(record["sequence"]))


class EngineSessionPersistence:
    """Persist and enumerate session operations through the event write path."""

    def __init__(self, engine: Any, student_ids: Iterable[int] = ()) -> None:
        self.engine = engine
        self.student_ids = {int(student_id) for student_id in student_ids}
        self._seen_sequences: set[int] = set()

    def log_write(self, operation: object) -> int:
        payload = dict(operation) if isinstance(operation, Mapping) else asdict(operation) if is_dataclass(operation) else {"operation": operation}
        if "student_id" not in payload:
            raise ValueError("session operation requires student_id")
        payload["record_type"] = "session_op"
        payload["student_id"] = int(payload["student_id"])
        self.student_ids.add(payload["student_id"])
        result = self.engine.write_event(payload)
        sequence = int(result["sequence"])
        self._seen_sequences.add(sequence)
        return sequence

    def create_exam_session(
        self,
        session_id: str,
        student_id: int,
        exam_id: str,
        started_at: float,
        timeout_seconds: float,
        source: str | None = None,
    ) -> None:
        """Persist compact exam-session metadata and its initial open state."""
        self.student_ids.add(0)
        self._write_compact_exam_operation({
            "op": "s",
            "t": session_id,
            "u": int(student_id),
            "e": exam_id,
            **({"source": source} if source is not None else {}),
        })
        self._write_compact_exam_operation({
            "op": "d",
            "t": session_id,
            "u": int(student_id),
            "a": round(float(started_at) * 1000),
            "d": float(timeout_seconds),
            **({"source": source} if source is not None else {}),
        })
        if source is None:
            self.update_exam_session(session_id, student_id, False, False)
        else:
            self._write_compact_exam_operation({
                "op": "x",
                "t": session_id,
                "u": int(student_id),
                "s": False,
                "x": False,
                "source": source,
            })

    def update_exam_session_deadline(
        self,
        session_id: str,
        student_id: int,
        started_at: float,
        timeout_seconds: float,
    ) -> None:
        """Persist a session's server-owned start time and timeout duration."""
        self.student_ids.add(0)
        self._write_compact_exam_operation({
            "op": "d",
            "t": session_id,
            "u": int(student_id),
            "a": round(float(started_at) * 1000),
            "d": float(timeout_seconds),
        })

    def update_exam_session(
        self,
        session_id: str,
        student_id: int,
        submitted: bool,
        timed_out: bool,
    ) -> None:
        """Persist the current submitted and timed-out session state."""
        self.student_ids.add(0)
        self._write_compact_exam_operation({
            "op": "x",
            "t": session_id,
            "u": int(student_id),
            "s": bool(submitted),
            "x": bool(timed_out),
        })

    def read_exam_sessions(self) -> dict[str, dict[str, Any]]:
        """Rebuild current exam-session state from compact persisted operations."""
        sessions: dict[str, dict[str, Any]] = {}
        for operation in self.read_operations(0):
            if operation.get("op") not in {"s", "d", "x"}:
                continue
            session_id = str(operation["t"])
            state = sessions.setdefault(session_id, {
                "session_id": session_id,
                "student_id": int(operation["u"]),
                "exam_id": "",
                "started_at": 0.0,
                "timeout_seconds": 0.0,
                "submitted": False,
                "timed_out": False,
            })
            if operation["op"] == "s":
                state["student_id"] = int(operation["u"])
                state["exam_id"] = str(operation["e"])
            elif operation["op"] == "d":
                state["started_at"] = int(operation["a"]) / 1000
                state["timeout_seconds"] = float(operation["d"])
            else:
                state["submitted"] = bool(operation["s"])
                state["timed_out"] = bool(operation["x"])
        return {
            session_id: state
            for session_id, state in sessions.items()
            if state["exam_id"] and state["started_at"]
        }

    def read_exam_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a single exam session from the shared session-operation stream."""
        return self.read_exam_sessions().get(session_id)

    def _write_compact_exam_operation(self, operation: Mapping[str, Any]) -> int:
        payload = {"student_id": 0, **operation}
        return self.log_write(payload)

    def replay_log_on_startup(self) -> int:
        replayed = 0
        for student_id in sorted(self.student_ids):
            records = self.engine.read_records(student_id, 0, 100000)
            for record in records:
                if record.get("record_type") != "session_op":
                    continue
                sequence = int(record["sequence"])
                if sequence not in self._seen_sequences:
                    self._seen_sequences.add(sequence)
                    replayed += 1
        return replayed

    def read_operations(self, student_id: int) -> list[dict[str, Any]]:
        """Return one student's ordered session operations from the worker."""
        records = self.engine.read_records(int(student_id), 0, 100000)
        return sorted(
            [record for record in records if record.get("record_type") == "session_op"],
            key=lambda record: int(record["sequence"]),
        )

    def read_operations_for_token(self, session_token: str) -> list[dict[str, Any]]:
        """Return ordered session operations matching one server token."""
        operations: list[dict[str, Any]] = []
        for student_id in sorted(self.student_ids):
            operations.extend(
                operation
                for operation in self.read_operations(student_id)
                if operation.get("session_token") == session_token
            )
        return sorted(operations, key=lambda record: int(record["sequence"]))


class EngineFinalizeStorage:
    """Persist finalized scoring decisions through the engine event path."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def write_record(
        self,
        student_id: int,
        risk_score: float | None,
        flagged: bool,
        timestamp: float,
        source: str = "scoring",
    ) -> int:
        result = self.engine.write_event({
            "record_type": "finalize",
            "schema_version": 1,
            "student_id": int(student_id),
            "risk_score": risk_score,
            "flagged": bool(flagged),
            "source": source,
            "timestamp": float(timestamp),
        })
        return int(result["sequence"])

    def read_record(self, student_id: int) -> dict[str, Any] | None:
        records = self.engine.read_records(int(student_id), 0, 100000)
        decisions = [
            record for record in records
            if record.get("record_type") == "finalize"
        ]
        if not decisions:
            return None
        return max(decisions, key=lambda record: int(record["sequence"]))


class EngineEventSink:
    """Validate events, replace client time, persist, and invoke scoring."""

    def __init__(self, engine: Any, scoring: Any | Callable[[int, str, float], Any]) -> None:
        self.engine = engine
        self.scoring = scoring

    def post_event(self, event: BehaviorEvent) -> None:
        if not isinstance(event.student_id, int) or event.student_id <= 0:
            raise ValueError("student_id must be a positive integer")
        if not event.signal or not isinstance(event.signal, str):
            raise ValueError("signal must be a non-empty string")
        if not math.isfinite(float(event.value)):
            raise ValueError("value must be finite")
        metadata = {str(key): str(value) for key, value in event.metadata.items()}
        source = (
            metadata.pop("source")
            if metadata.get("source") == "synthetic"
            else None
        )
        persisted = {
            "record_type": "event",
            "student_id": event.student_id,
            "signal": event.signal,
            "value": round(float(event.value), 6),
            "timestamp": round(time.time(), 3),
            **(
                {"metadata": metadata}
                if metadata or source is None else {}
            ),
            **({"source": source} if source is not None else {}),
        }
        self.engine.write_event(persisted)
        if event.signal not in SIGNALS:
            return
        if callable(self.scoring):
            self.scoring(event.student_id, event.signal, float(event.value))
        else:
            self.scoring.score_event(event.student_id, event.signal, float(event.value))
