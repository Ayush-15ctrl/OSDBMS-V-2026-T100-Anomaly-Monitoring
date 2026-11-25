"""Service boundary for offline baseline batches and cold-start resolution."""

from typing import Iterable, Mapping

from python.ml.baseline_engine import BaselineProfile


class BaselineService:
    """Coordinate baseline construction without exposing storage to HTTP routes."""

    def __init__(self, baseline_engine: object, cold_start_resolver: object) -> None:
        """Create a service from injected baseline components."""
        self.baseline_engine = baseline_engine
        self.cold_start_resolver = cold_start_resolver

    def build(self, student_id: int, history: Iterable[Mapping[str, float]]) -> BaselineProfile:
        """Build and persist one student's offline baseline."""
        return self.baseline_engine.build(student_id, history)

    def build_all(self, histories: Mapping[int, Iterable[Mapping[str, float]]]) -> dict[int, BaselineProfile]:
        """Run the offline batch baseline build for all students."""
        return self.baseline_engine.build_all(histories)

    def get(self, student_id: int) -> BaselineProfile:
        """Load one student's baseline for internal scoring or admin views."""
        return self.baseline_engine.load(student_id)

    def cold_start(self, student_id: int, vector: Iterable[float], sessions: int) -> object:
        """Resolve a limited-history student to a provisional cohort baseline."""
        return self.cold_start_resolver.resolve(student_id, list(vector), sessions)
