"""Service boundary for explainable anomaly, risk, and multivariate scoring."""

from dataclasses import dataclass, replace
from functools import lru_cache
import threading
import time
from typing import Protocol, Sequence

from app.hooks.events import FlagRaised
from python.ml.anomaly_detector import AnomalyResult
from python.ml.baseline_engine import SIGNALS
from python.ml.risk_scorer import RiskScorer
from .feature_vector import build_session_feature_vector, complete_question_count


class FinalizationStorage(Protocol):
    """Persistence interface for durable session-finalization decisions."""

    def read_record(self, student_id: int) -> dict[str, object] | None:
        ...

    def write_record(
        self,
        student_id: int,
        risk_score: float | None,
        flagged: bool,
        timestamp: float,
        source: str = "scoring",
    ) -> int:
        ...


@dataclass(frozen=True)
class ScoringResult:
    """Complete explainable scoring result for internal/proctor consumers."""

    student_id: int
    signal_results: Sequence[AnomalyResult]
    risk_score: float | None
    multivariate_score: float | None
    flagged: bool
    timestamp: float
    status: str = "scored"


class ScoringService:
    """Score evidence continuously and publish decisions at session end."""

    def __init__(
        self,
        anomaly_detector: object,
        risk_scorer: object,
        event_bus: object,
        finalization_storage: FinalizationStorage | None = None,
    ) -> None:
        """Create a scoring service from injected detector components."""
        self.anomaly_detector = anomaly_detector
        self.risk_scorer = risk_scorer
        self.event_bus = event_bus
        self.finalization_storage = finalization_storage
        self.multivariate_detector = getattr(risk_scorer, "multivariate_detector", None)
        self._buffers: dict[int, dict[str, list[float]]] = {}
        self._last_scored_questions: dict[int, int] = {}
        self._latest_results: dict[int, ScoringResult] = {}
        self._finalized_students: set[int] = set()
        self._finalization_locks: dict[int, threading.Lock] = {}
        self._finalization_locks_guard = threading.Lock()
        self.minimum_questions = 10
        self.risk_threshold = 0.463710

    def score_event(self, student_id: int, signal: str, value: float) -> ScoringResult:
        """Update the running risk score without publishing a review flag."""
        self._ensure_not_finalized(student_id)
        if signal not in SIGNALS:
            latest = self._latest_results.get(student_id)
            if latest is not None and latest.risk_score is not None:
                return latest
            return self._insufficient(student_id, "insufficient data")
        result = self.anomaly_detector.score_event(student_id, signal, value)
        buffer = self._buffers.setdefault(student_id, {name: [] for name in SIGNALS})
        buffer[signal].append(value)
        question_count = complete_question_count(buffer)
        if question_count < self.minimum_questions:
            return self._insufficient(student_id, "insufficient data")
        if question_count <= self._last_scored_questions.get(student_id, 0):
            return self._latest_results[student_id]
        self._last_scored_questions[student_id] = question_count
        vector = self.current_feature_vector(student_id)
        return self._finish(student_id, [result], vector)

    def score_session(self, student_id: int, events: Sequence[dict[str, float]]) -> ScoringResult:
        """Score a session through the same explainable pipeline."""
        self._ensure_not_finalized(student_id)
        results = self.anomaly_detector.score_session(student_id, events)
        buffer = self._buffers.setdefault(student_id, {name: [] for name in SIGNALS})
        for event in events:
            if event["signal"] in buffer:
                buffer[event["signal"]].append(float(event["value"]))
        if complete_question_count(buffer) < self.minimum_questions:
            return self._insufficient(student_id, "insufficient data")
        vector = self.current_feature_vector(student_id)
        self._last_scored_questions[student_id] = complete_question_count(buffer)
        return self._finish(student_id, results, vector)

    def latest_result(self, student_id: int) -> ScoringResult | None:
        """Return the most recent live result for a student, if any."""
        return self._latest_results.get(student_id)

    def finalize_session(
        self, student_id: int, source: str = "scoring"
    ) -> ScoringResult:
        """Make and publish at most one threshold decision for a completed session."""
        with self._finalization_locks_guard:
            student_lock = self._finalization_locks.setdefault(
                student_id, threading.Lock()
            )
        with student_lock:
            return self._finalize_session_locked(student_id, source)

    def _finalize_session_locked(
        self, student_id: int, source: str = "scoring"
    ) -> ScoringResult:
        if self.finalization_storage is not None:
            stored = self.finalization_storage.read_record(student_id)
            if stored is not None:
                latest = self._latest_results.get(student_id)
                if (
                    stored["risk_score"] is None
                    and latest is not None
                    and latest.risk_score is not None
                ):
                    final_result = replace(
                        latest,
                        flagged=latest.risk_score >= self.risk_threshold,
                    )
                    self.finalization_storage.write_record(
                        student_id,
                        final_result.risk_score,
                        final_result.flagged,
                        final_result.timestamp,
                        source="recovery",
                    )
                    self._latest_results[student_id] = final_result
                    self._finalized_students.add(student_id)
                    return final_result
                final_result = ScoringResult(
                    student_id=student_id,
                    signal_results=latest.signal_results if latest is not None else (),
                    risk_score=(
                        float(stored["risk_score"])
                        if stored["risk_score"] is not None
                        else None
                    ),
                    multivariate_score=(
                        latest.multivariate_score if latest is not None else None
                    ),
                    flagged=bool(stored["flagged"]),
                    timestamp=float(stored["timestamp"]),
                    status=latest.status if latest is not None else "finalized",
                )
                self._latest_results[student_id] = final_result
                self._finalized_students.add(student_id)
                return final_result

        latest = self._latest_results.get(student_id)
        if student_id in self._finalized_students:
            if latest is None:
                raise RuntimeError("finalized session has no scoring result")
            return latest

        if latest is None:
            latest = self._insufficient(student_id, "insufficient data")
        flagged = latest.risk_score is not None and latest.risk_score >= self.risk_threshold
        final_result = replace(latest, flagged=flagged)
        if self.finalization_storage is not None:
            if source == "scoring":
                self.finalization_storage.write_record(
                    student_id,
                    final_result.risk_score,
                    final_result.flagged,
                    final_result.timestamp,
                )
            else:
                self.finalization_storage.write_record(
                    student_id,
                    final_result.risk_score,
                    final_result.flagged,
                    final_result.timestamp,
                    source=source,
                )
        self._latest_results[student_id] = final_result
        self._finalized_students.add(student_id)
        if final_result.flagged and final_result.risk_score is not None:
            self.event_bus.publish(
                FlagRaised(
                    student_id,
                    final_result.signal_results,
                    final_result.risk_score,
                    final_result.timestamp,
                )
            )
        return final_result

    def current_feature_vector(self, student_id: int) -> list[float]:
        """Build the current session vector from the student's buffered events."""
        buffer = self._buffers.get(student_id, {name: [] for name in SIGNALS})
        profile = self.anomaly_detector.baselines.load(student_id)
        return build_session_feature_vector(
            [{"signal": name, "value": value} for name, values in buffer.items() for value in values],
            profile,
        )

    def _insufficient(self, student_id: int, status: str) -> ScoringResult:
        result = ScoringResult(student_id, [], None, None, False, time.time(), status)
        self._latest_results[student_id] = result
        return result

    def _finish(self, student_id: int, results: Sequence[AnomalyResult], vector: list[float]) -> ScoringResult:
        names = tuple(getattr(self.risk_scorer, "signal_names", SIGNALS))
        risk_vector = vector[:len(names)]
        prediction = self.risk_scorer.predict_risk(risk_vector)
        multivariate_score = None
        if self.multivariate_detector is not None:
            multivariate_score = self.multivariate_detector.score(risk_vector).anomaly_score
        timestamp = time.time()
        flagged = prediction.probability >= self.risk_threshold
        result = ScoringResult(student_id, results, prediction.probability, multivariate_score, flagged, timestamp)
        self._latest_results[student_id] = result
        return result

    def _ensure_not_finalized(self, student_id: int) -> None:
        if student_id in self._finalized_students:
            raise RuntimeError(f"session for student {student_id} has already been finalized")


@lru_cache(maxsize=1)
def _cached_risk_scorer() -> RiskScorer:
    """Fit the process-wide frozen synthetic split once."""
    from statistics import mean, pstdev

    from python.ml.baseline_engine import BaselineProfile, SignalBaseline
    from python.synthetic.data_generator import SyntheticDataGenerator
    from .feature_vector import build_session_feature_vector

    training_vectors: list[list[float]] = []
    labels: list[int] = []
    for student_id in range(1, 201):
        generator = SyntheticDataGenerator(seed=6101)
        practice = generator.practice_history(student_id, 5)
        profile = BaselineProfile(
            student_id=student_id,
            **{
                signal: SignalBaseline(
                    mean=mean([
                        float(event["value"])
                        for session in practice
                        for event in session.events
                        if event["signal"] == signal
                    ]),
                    std=max(pstdev([
                        float(event["value"])
                        for session in practice
                        for event in session.events
                        if event["signal"] == signal
                    ]), 1e-6),
                )
                for signal in SIGNALS
            },
        )
        for behavior in ("honest", "nervous", "paste", "friend_feeding"):
            exam = generator.exam_session(student_id, behavior)
            training_vectors.append(build_session_feature_vector(exam.events, profile))
            labels.append(int(behavior in {"paste", "friend_feeding"}))
    scorer = RiskScorer(SIGNALS, random_state=17).fit(
        training_vectors, labels
    )
    return scorer


def train_risk_scorer(engine: object) -> RiskScorer:
    """Load the cached frozen scorer and persist its weights for this engine."""
    scorer = _cached_risk_scorer()
    model = scorer._model
    if model is None:
        raise RuntimeError("risk scorer failed to train")

    model_record = {
        "record_type": "model",
        "model_label": "trained on synthetic data",
        "student_id": 0,
        "student_range": "1-200",
        "seed": 6101,
        "signal_count": len(SIGNALS),
    }
    coefficients = [float(model.intercept_[0]), *[float(value) for value in model.coef_[0]]]
    records = engine.read_records(0, 0, 100000)
    model_records = sorted(
        (
            record for record in records
            if record.get("record_type") == "model"
            and all(record.get(key) == value for key, value in model_record.items())
        ),
        key=lambda record: int(record["sequence"]),
    )
    if model_records:
        stored_model = model_records[-1]
        start_sequence = int(stored_model["sequence"])
        end_sequence = min(
            (
                int(record["sequence"])
                for record in records
                if record.get("record_type") == "model"
                and int(record["sequence"]) > start_sequence
            ),
            default=float("inf"),
        )
        stored_coefficient_records = [
            record
            for record in records
            if record.get("record_type") == "model_coefficient"
            and start_sequence < int(record["sequence"]) < end_sequence
        ]
        stored_coefficients = {
            int(record["index"]): float(record["coefficient"])
            for record in stored_coefficient_records
        }
        expected_coefficients = dict(enumerate(coefficients))
        if (
            len(stored_coefficients) == len(stored_coefficient_records)
            and all(
                expected_coefficients.get(index) == coefficient
                for index, coefficient in stored_coefficients.items()
            )
        ):
            for index, coefficient in expected_coefficients.items():
                if index not in stored_coefficients:
                    engine.write_event({
                        "record_type": "model_coefficient",
                        "student_id": 0,
                        "index": index,
                        "coefficient": coefficient,
                    })
            return scorer

    engine.write_event(model_record)
    for index, coefficient in enumerate(coefficients):
        engine.write_event({
            "record_type": "model_coefficient",
            "student_id": 0,
            "index": index,
            "coefficient": float(coefficient),
        })
    return scorer
