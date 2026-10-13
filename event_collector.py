"""OS/DBMS concept: event ingestion as an append-only write path."""

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class BehaviorEvent:
    """One behavior-only event sent immediately to the server."""

    student_id: int
    signal: str
    value: float
    timestamp: float
    metadata: Mapping[str, str]


class EventSink(Protocol):
    """Server endpoint used by the collector without client buffering."""

    def post_event(self, event: BehaviorEvent) -> None:
        """Accept one event immediately."""


class EventCollector:
    """Validate and forward browser behavior events to a server sink."""

    def __init__(self, sink: EventSink) -> None:
        """Create an immediate, non-buffering collector."""
        ...

    def collect(self, event: BehaviorEvent) -> None:
        """Post one event immediately to the configured sink."""
        ...