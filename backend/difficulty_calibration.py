"""OS/DBMS concept: calibrated query-cost estimation for difficulty-aware signals."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ExpectedTiming:
    """Difficulty-adjusted expected time and residual standard deviation."""

    expected_time: float
    std: float


class DifficultyCalibrator:
    """Wrap LinearRegression for expected question timing by difficulty tier."""

    def __init__(self, random_state: int = 42) -> None:
        """Create an unfitted difficulty calibration model."""
        ...

    def fit(self, difficulty: Sequence[float], times: Sequence[float]) -> "DifficultyCalibrator":
        """Fit expected time and residual spread from labeled observations."""
        ...

    def expected_time(self, student_id: int, difficulty: float) -> ExpectedTiming:
        """Return a difficulty-adjusted timing expectation for one student."""
        ...