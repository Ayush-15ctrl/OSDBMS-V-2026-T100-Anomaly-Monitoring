"""Held-out synthetic evaluation for Stage 2 detector scores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sklearn.metrics import precision_score, recall_score, roc_auc_score

from python.ml.anomaly_detector import AnomalyDetector
from python.ml.baseline_engine import BaselineProfile
from python.ml.baseline_engine import SIGNALS
from python.ml.baseline_engine import SignalBaseline
from python.ml.multivariate_detector import MultivariateDetector
from python.ml.risk_scorer import RiskScorer
from python.synthetic.data_generator import SyntheticDataGenerator
from app.services.feature_vector import build_session_feature_vector


BEHAVIORS = ("honest", "nervous", "paste", "friend_feeding")
CHEATING = {"paste", "friend_feeding"}


@dataclass(frozen=True)
class Session:
    behavior: str
    z_vector: list[float]
    max_event_z: float
    mean_abs_z: float


class ProfileProvider:
    def __init__(self, profiles: dict[int, BaselineProfile]) -> None:
        self.profiles = profiles

    def load(self, student_id: int) -> BaselineProfile:
        return self.profiles[student_id]


def values(session: object, signal: str) -> list[float]:
    return [
        float(event["value"])
        for event in session.events  # type: ignore[union-attr]
        if event["signal"] == signal  # type: ignore[index]
    ]


def build_student_sessions(seed: int, student_id: int) -> list[Session]:
    generator = SyntheticDataGenerator(seed=seed)
    practice = generator.practice_history(student_id, 5)
    means = {
        signal: mean([value for session in practice for value in values(session, signal)])
        for signal in SIGNALS
    }
    stds = {
        signal: max(
            pstdev([value for session in practice for value in values(session, signal)]),
            1e-6,
        )
        for signal in SIGNALS
    }
    profile = BaselineProfile(
        student_id=student_id,
        **{
            signal: SignalBaseline(mean=means[signal], std=stds[signal])
            for signal in SIGNALS
        },
    )
    detector = AnomalyDetector(ProfileProvider({student_id: profile}), threshold=3.0)
    sessions = []
    for behavior in BEHAVIORS:
        exam = generator.exam_session(student_id, behavior)
        results = detector.score_session(
            student_id,
            [
                {"signal": event["signal"], "value": event["value"]}
                for event in exam.events
                if event["signal"] in SIGNALS
            ],
        )
        sessions.append(
            Session(
                behavior=behavior,
                z_vector=build_session_feature_vector(
                    [
                        {"signal": event["signal"], "value": event["value"]}
                        for event in exam.events
                        if event["signal"] in SIGNALS
                    ],
                    profile,
                ),
                max_event_z=max(abs(result.z_score) for result in results),
                mean_abs_z=mean(abs(result.z_score) for result in results),
            )
        )
    return sessions


def dataset(seed: int, first_student: int) -> list[Session]:
    sessions: list[Session] = []
    for student_id in range(first_student, first_student + 200):
        sessions.extend(build_student_sessions(seed, student_id))
    return sessions


def choose_threshold(scores: list[float], labels: list[int]) -> float:
    candidates = sorted(set(scores))
    best = (-1.0, candidates[0])
    for threshold in candidates:
        predictions = [int(score >= threshold) for score in scores]
        precision = precision_score(labels, predictions, zero_division=0)
        recall = recall_score(labels, predictions, zero_division=0)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        if (f1, -threshold) > (best[0], -best[1]):
            best = (f1, threshold)
    return best[1]


def report(name: str, threshold: float, scores: list[float], sessions: list[Session]) -> float:
    labels = [int(session.behavior in CHEATING) for session in sessions]
    predictions = [int(score >= threshold) for score in scores]
    precision = precision_score(labels, predictions, zero_division=0)
    recall = recall_score(labels, predictions, zero_division=0)
    honest_fpr = mean(prediction for prediction, session in zip(predictions, sessions) if session.behavior == "honest")
    nervous_fpr = mean(prediction for prediction, session in zip(predictions, sessions) if session.behavior == "nervous")
    roc_sessions = [session for session in sessions if session.behavior in {"nervous", "paste", "friend_feeding"}]
    roc_scores = [score for score, session in zip(scores, sessions) if session.behavior in {"nervous", "paste", "friend_feeding"}]
    roc_labels = [int(session.behavior in CHEATING) for session in roc_sessions]
    auc = roc_auc_score(roc_labels, roc_scores)
    print(f"{name}: threshold={threshold:.6f} precision={precision:.3f} recall={recall:.3f} honest_fpr={honest_fpr:.3f} nervous_fpr={nervous_fpr:.3f} cheating_vs_nervous_auc={auc:.3f}")
    for behavior in ("paste", "friend_feeding"):
        selected = [
            (score, session)
            for score, session in zip(scores, sessions)
            if session.behavior in {behavior, "honest", "nervous"}
        ]
        class_scores = [score for score, _ in selected]
        class_sessions = [session for _, session in selected]
        class_labels = [int(session.behavior == behavior) for session in class_sessions]
        class_predictions = [int(score >= threshold) for score in class_scores]
        print(
            f"  {behavior}: recall={recall_score(class_labels, class_predictions, zero_division=0):.3f} "
            f"precision_against_honest_nervous={precision_score(class_labels, class_predictions, zero_division=0):.3f}"
        )
    return auc


def prevalence_precision(
    threshold: float, scores: list[float], sessions: list[Session], prevalence: float
) -> float:
    predictions = [score >= threshold for score in scores]
    cheating_scores = [prediction for prediction, session in zip(predictions, sessions) if session.behavior in CHEATING]
    non_cheating_scores = [prediction for prediction, session in zip(predictions, sessions) if session.behavior not in CHEATING]
    true_positive_rate = mean(cheating_scores)
    false_positive_rate = mean(non_cheating_scores)
    return (true_positive_rate * prevalence) / max(
        true_positive_rate * prevalence + false_positive_rate * (1 - prevalence),
        1e-12,
    )


def main() -> None:
    training = dataset(seed=6101, first_student=1)
    validation = dataset(seed=7301, first_student=201)
    test = dataset(seed=9401, first_student=1001)

    z_validation = [session.max_event_z for session in validation]
    z_test = [session.max_event_z for session in test]
    session_z_validation = [session.mean_abs_z for session in validation]
    session_z_test = [session.mean_abs_z for session in test]
    labels = [int(session.behavior in CHEATING) for session in validation]
    z_threshold = choose_threshold(z_validation, labels)
    session_z_threshold = choose_threshold(session_z_validation, labels)

    training_labels = [int(session.behavior in CHEATING) for session in training]
    risk = RiskScorer(SIGNALS, random_state=17).fit(
        [session.z_vector for session in training], training_labels
    )
    validation_risk = [risk.predict_risk(session.z_vector).probability for session in validation]
    test_risk = [risk.predict_risk(session.z_vector).probability for session in test]
    risk_threshold = choose_threshold(validation_risk, labels)

    multivariate = MultivariateDetector(SIGNALS, contamination="auto", random_state=17).fit(
        [session.z_vector for session in training if session.behavior in {"honest", "nervous"}]
    )
    validation_multi = [multivariate.score(session.z_vector).anomaly_score for session in validation]
    test_multi = [multivariate.score(session.z_vector).anomaly_score for session in test]
    multi_threshold = choose_threshold(validation_multi, labels)

    print("training_students=1-200 seed=6101")
    print("validation_students=201-400 seed=7301")
    print("test_students=1001-1200 seed=9401")
    print("all_student_ranges_disjoint=True")
    print("thresholds_selected_on_validation=f1_cheating_vs_honest_nervous")
    z_auc = report("per_event_z_max_session", z_threshold, z_test, test)
    report("session_mean_abs_z", session_z_threshold, session_z_test, test)
    report("risk_scorer_logistic_signed_z_vector", risk_threshold, test_risk, test)
    report("multivariate_isolation_forest", multi_threshold, test_multi, test)
    print(f"risk_precision_prevalence_2pct={prevalence_precision(risk_threshold, test_risk, test, 0.02):.3f}")
    print(f"risk_precision_prevalence_10pct={prevalence_precision(risk_threshold, test_risk, test, 0.10):.3f}")
    print(
        f"z_score_auc={z_auc:.3f}; nervous shifts receive larger raw absolute z-scores, "
        f"so reversing the score ranking yields {1.0 - z_auc:.3f}"
    )


if __name__ == "__main__":
    main()
