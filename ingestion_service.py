"""Service boundary for validation, locking, WAL writes, and scoring dispatch."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math
import time
from typing import Mapping, Protocol

from python.ingestion.event_collector import BehaviorEvent
from python.ml.baseline_engine import SIGNALS

from .engine_adapters import EngineEventSink


class EngineClient(Protocol):
    def write_event(self, event: BehaviorEvent) -> str: ...


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    server_timestamp: float


class IngestionService:
    """Validate, timestamp, buffer, persist, and score behavior events."""

    def __init__(self, engine: EngineClient) -> None:
        """Create an ingestion service using an engine with attached scoring."""
        self.engine = engine
        self.scoring = getattr(engine, "scoring", None)
        self.stream_buffer: dict[int, deque[BehaviorEvent]] = defaultdict(deque)
        self.sink = EngineEventSink(engine, self.scoring) if self.scoring is not None else None

    def ingest(
        self,
        student_id: int,
        signal: str,
        value: float,
        client_timestamp: float | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> IngestionResult:
        """Validate and immediately persist one server-timestamped event."""
        if not isinstance(student_id, int) or student_id <= 0:
            raise ValueError("student_id must be a positive integer")
        if not isinstance(signal, str) or not signal:
            raise ValueError("signal must be a non-empty string")
        event_value = float(value)
        if not math.isfinite(event_value):
            raise ValueError("value must be finite")
        if self.sink is None:
            raise RuntimeError("scoring service is unavailable")
        server_timestamp = time.time()
        event = BehaviorEvent(
            student_id=student_id,
            signal=signal,
            value=event_value,
            timestamp=server_timestamp,
            metadata={str(key): str(item) for key, item in (metadata or {}).items()},
        )
        self.stream_buffer[student_id].append(event)
        self.sink.post_event(event)
        return IngestionResult(f"{student_id}:{server_timestamp:.9f}", server_timestamp)

    def ingest_session(self, student_id: int, events: list[Mapping[str, object]]) -> object:
        """Ingest every event, then score the complete buffered session."""
        for event in events:
            self.ingest(
                student_id,
                str(event["signal"]),
                float(event["value"]),
                client_timestamp=float(event["timestamp"]) if "timestamp" in event else None,
                metadata=event.get("metadata") if isinstance(event.get("metadata"), Mapping) else None,
            )
        if self.scoring is None:
            raise RuntimeError("scoring service is unavailable")
        return self.scoring.finalize_session(student_id)
