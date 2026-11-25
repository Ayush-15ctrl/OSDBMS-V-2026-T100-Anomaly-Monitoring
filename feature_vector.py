"""Shared session feature construction for evaluation and live scoring."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import mean

from python.ml.baseline_engine import BaselineProfile, SIGNALS


REQUIRED_QUESTION_SIGNALS = (
    "time_per_question",
    "focus_switch_rate",
    "answer_change_rate",
    "answer_change_count",
    "navigation_order_deviation",
    "time_vs_difficulty",
)


def build_session_feature_vector(
    events: Iterable[Mapping[str, object]], baseline: BaselineProfile
) -> list[float]:
    """Compute per-signal session mean shifts normalized by the student baseline."""
    grouped: dict[str, list[float]] = {signal: [] for signal in SIGNALS}
    for event in events:
        signal = str(event["signal"])
        if signal in grouped:
            grouped[signal].append(float(event["value"]))
    return [
        (mean(grouped[signal]) - getattr(baseline, signal).mean) / getattr(baseline, signal).std
        if grouped[signal]
        else 0.0
        for signal in SIGNALS
    ]


# Kept as a small compatibility alias for callers of the original helper name.
session_z_vector = build_session_feature_vector


def complete_question_count(events_by_signal: Mapping[str, list[float]]) -> int:
    """Count questions with all consistently collected signal streams.

    Keystroke intervals and mouse entropy are intentionally absent when a
    student does not type or move the mouse enough, so they are not required
    to establish that a question was observed.
    """
    if any(not events_by_signal.get(signal) for signal in REQUIRED_QUESTION_SIGNALS):
        return 0
    return min(len(events_by_signal[signal]) for signal in REQUIRED_QUESTION_SIGNALS)
