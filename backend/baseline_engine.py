"""OS/DBMS concept: offline statistics, persisted records, and student isolation."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol


SIGNALS = (
    "keystroke_interval",
    "time_per_question",
    "focus_switch_rate",
    "answer_change_rate",
    "mouse_path_entropy",
    "answer_change_count",
    "navigation_order_deviation",
    "time_vs_difficulty",
)


@dataclass(frozen=True)
class SignalBaseline:
    """Mean and standard deviation for one behavior signal."""

    mean: float
    std: float


@dataclass(frozen=True)
class BaselineProfile:
    """Per-student baseline profile used by live anomaly scoring."""

    student_id: int
    keystroke_interval: SignalBaseline
    time_per_question: SignalBaseline
    focus_switch_rate: SignalBaseline
    answer_change_rate: SignalBaseline
    mouse_path_entropy: SignalBaseline
    answer_change_count: SignalBaseline
    navigation_order_deviation: SignalBaseline
    time_vs_difficulty: SignalBaseline


class BaselineStorage(Protocol):
    """Minimal persistence surface expected from the bams_core binding."""

    def write_record(self, student_id: int, event: object) -> int:
        """Persist one serialized baseline record and return its location."""

    def read_records(self, student_id: int, offset: int, count: int) -> list[object]:
        """Read persisted baseline records for one student."""


class BaselineEngine:
    """Build offline baselines and persist them through the storage engine."""

    def __init__(self, storage: BaselineStorage, epsilon: float = 1e-6) -> None:
        """Create an engine backed by a bams_core storage binding."""
        ...

    def build(
        self, student_id: int, history: Iterable[Mapping[str, float]]
    ) -> BaselineProfile:
        """Build and persist one student's baseline from historical sessions."""
        ...

    def build_all(
        self,
        histories: Mapping[int, Iterable[Mapping[str, float]]],
        workers: int | None = None,
    ) -> dict[int, BaselineProfile]:
        """Build all profiles in offline hash-sharded worker processes."""
        ...

    def load(self, student_id: int) -> BaselineProfile:
        """Load one student's profile from the buffer pool or storage."""
        ...