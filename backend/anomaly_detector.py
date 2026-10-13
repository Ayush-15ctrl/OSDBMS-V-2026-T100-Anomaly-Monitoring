"""OS/DBMS concept: buffer-pool lookup and constant-time transaction scoring."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from .baseline_engine import BaselineProfile


@dataclass(frozen=True)
class AnomalyResult:
    """Explainable result for one behavior signal."""

    signal: str
    value: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    reason: str
    flagged: bool


class BaselineProvider(Protocol):
    """Source for isolated student baseline profiles."""

    def load(self, student_id: int) -> BaselineProfile:
        """Return the profile for exactly one student."""


class AnomalyDetector:
    """Score behavior events against a student's persisted profile."""

    def __init__(self, baselines: BaselineProvider, threshold: float = 3.0) -> None:
        """Create a detector with a constant-time z-score threshold."""
        ...

    def score_event(self, student_id: int, signal: str, value: float) -> AnomalyResult:
        """Return an explainable z-score result for one event."""
        ...

    def score_session(
        self, student_id: int, events: Iterable[Mapping[str, float]]
    ) -> list[AnomalyResult]:
        """Score one result per signal represented in a session."""
        ...