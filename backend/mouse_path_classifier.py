"""OS/DBMS concept: feature extraction from low-level input event streams."""

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MousePathFeatures:
    """Behavior-only features extracted from timestamped cursor points."""

    path_length_ratio: float
    curvature: float
    jitter: float
    velocity_variance: float
    pause_count: int


@dataclass(frozen=True)
class MousePathPrediction:
    """Classification result and feature importances for one path."""

    label: str
    feature_importances: dict[str, float]


class MousePathClassifier:
    """Wrap a shallow seeded DecisionTreeClassifier."""

    def __init__(self, max_depth: int = 4, random_state: int = 42) -> None:
        """Create an unfitted natural-versus-directed path classifier."""
        ...

    @staticmethod
    def extract_features(points: Sequence[tuple[float, float, float]]) -> MousePathFeatures:
        """Extract path-length, curvature, jitter, velocity, and pause features."""
        ...

    def fit(self, X: Sequence[MousePathFeatures], y: Sequence[str]) -> "MousePathClassifier":
        """Fit the shallow classifier."""
        ...

    def predict(self, features: MousePathFeatures) -> MousePathPrediction:
        """Classify one path and expose learned feature importances."""
        ...