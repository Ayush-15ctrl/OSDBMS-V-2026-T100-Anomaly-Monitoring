"""OS/DBMS concept: deterministic decision policy over normalized telemetry."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RiskPrediction:
    """Calibrated risk probability and explainable model weights."""

    probability: float
    feature_weights: dict[str, float]


class RiskScorer:
    """Wrap a seeded scikit-learn LogisticRegression model."""

    def __init__(self, signal_names: Sequence[str], random_state: int = 42) -> None:
        """Create an unfitted scorer for the supplied signal ordering."""
        ...

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> "RiskScorer":
        """Fit the logistic model on per-signal z-score vectors."""
        ...

    def predict_risk(self, z_vector: Sequence[float]) -> RiskPrediction:
        """Return a calibrated probability and per-signal learned weights."""
        ...