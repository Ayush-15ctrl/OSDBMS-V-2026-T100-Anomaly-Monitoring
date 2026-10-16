"""OS/DBMS concept: multi-column index-style detection over correlated signals."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MultivariateResult:
    """Explainable IsolationForest result for a signal vector."""

    anomaly_score: float
    predicted_anomaly: bool
    contributing_features: list[str]


class MultivariateDetector:
    """Wrap a seeded IsolationForest for combinations of mild deviations."""

    def __init__(
        self, feature_names: Sequence[str], contamination: str | float = "auto", random_state: int = 42
    ) -> None:
        """Create an unfitted multivariate detector."""
        ...

    def fit(self, X: Sequence[Sequence[float]]) -> "MultivariateDetector":
        """Fit the forest on per-signal z-score vectors."""
        ...

    def score(self, vector: Sequence[float]) -> MultivariateResult:
        """Return an anomaly score and the features contributing most."""
        ...