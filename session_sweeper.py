"""Finalize expired exam sessions that have not already been finalized."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import time
from typing import Any

from app.engine_service.process import EngineUnavailable


LOGGER = logging.getLogger("bams.app.session_sweeper")


def sweep_expired_sessions(
    sessions: Mapping[str, Any],
    scoring: Any,
    finalization_storage: Any,
    session_persistence: Any,
    *,
    now: float | None = None,
) -> int:
    """Finalize every expired, unfinished session not already in engine storage."""
    current_time = time.time() if now is None else now
    finalized = 0
    for session in list(sessions.values()):
        if session.submitted or session.timed_out:
            continue
        if current_time < session.started_at + session.timeout_seconds:
            continue
        if finalization_storage.read_record(session.student_id) is not None:
            session.timed_out = True
            session_persistence.update_exam_session(
                session.session_id,
                session.student_id,
                session.submitted,
                session.timed_out,
            )
            continue
        scoring.finalize_session(session.student_id)
        session.timed_out = True
        session_persistence.update_exam_session(
            session.session_id,
            session.student_id,
            session.submitted,
            session.timed_out,
        )
        finalized += 1
    return finalized


def run_sweep_loop(
    sweep: Callable[[], int],
    *,
    interval_seconds: float = 1.0,
) -> None:
    """Run the session sweep periodically, logging transient engine failures."""
    while True:
        try:
            sweep()
        except EngineUnavailable:
            LOGGER.warning("Expired-session sweep could not reach the engine", exc_info=True)
        except Exception:
            LOGGER.exception("Expired-session sweep failed")
        time.sleep(interval_seconds)
