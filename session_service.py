"""Service boundary for server-owned exam state and refresh recovery."""

from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any
from uuid import uuid4

from python.ingestion.event_collector import BehaviorEvent
from python.ingestion.session_manager import RefreshRecovery, SessionState


class SessionService:
    """Keep authoritative session state and persist every transition."""

    def __init__(self, session_manager: object) -> None:
        """Create a service around a session persistence adapter."""
        self.persistence = session_manager
        self._states: dict[str, SessionState] = {}

    def start(self, student_id: int, exam_id: str) -> SessionState:
        """Start a server-side session and persist its initial state."""
        if student_id <= 0 or not exam_id:
            raise ValueError("student_id and exam_id are required")
        state = SessionState(
            student_id=student_id,
            exam_id=exam_id,
            session_token=uuid4().hex,
            current_question=0,
            timer_seconds_remaining=0,
            answers={},
            last_event_timestamp=time.time(),
        )
        self._states[state.session_token] = state
        self._persist(state, "start")
        return state

    def state(self, session_token: str) -> SessionState:
        """Return memory state or rehydrate it from ordered session records."""
        if session_token in self._states:
            return self._states[session_token]
        operations = self.persistence.read_operations_for_token(session_token)
        if not operations:
            raise KeyError(f"unknown session: {session_token}")
        state = self._state_from_operation(operations[-1])
        self._states[session_token] = state
        return state

    def refresh(self, session_token: str, page_load_timestamp: float) -> RefreshRecovery:
        """Persist a server-timestamped refresh and return the recovered state."""
        state = self.state(session_token)
        server_timestamp = time.time()
        previous = state.last_event_timestamp or server_timestamp
        gap_duration = max(0.0, server_timestamp - previous)
        refreshed = SessionState(
            student_id=state.student_id,
            exam_id=state.exam_id,
            session_token=state.session_token,
            current_question=state.current_question,
            timer_seconds_remaining=state.timer_seconds_remaining,
            answers=dict(state.answers),
            last_event_timestamp=server_timestamp,
        )
        self._states[session_token] = refreshed
        self._persist(refreshed, "refresh", gap_duration)
        refresh_event = BehaviorEvent(
            student_id=state.student_id,
            signal="refresh_gap",
            value=gap_duration,
            timestamp=server_timestamp,
            metadata={"session_token": session_token},
        )
        return RefreshRecovery(refreshed, refresh_event, gap_duration)

    def update_question(self, session_token: str, question: int) -> SessionState:
        """Persist the current question before changing server-side state."""
        state = self.state(session_token)
        updated = SessionState(
            state.student_id, state.exam_id, state.session_token, question,
            state.timer_seconds_remaining, dict(state.answers), time.time()
        )
        self._states[session_token] = updated
        self._persist(updated, "update_question")
        return updated

    def record_answer(self, session_token: str, question: int, answer: str) -> SessionState:
        """Persist an answer before applying it to server-side state."""
        state = self.state(session_token)
        answers = dict(state.answers)
        answers[int(question)] = str(answer)
        updated = SessionState(
            state.student_id, state.exam_id, state.session_token, state.current_question,
            state.timer_seconds_remaining, answers, time.time()
        )
        self._states[session_token] = updated
        self._persist(updated, "record_answer")
        return updated

    def _persist(self, state: SessionState, operation: str, gap_duration: float | None = None) -> None:
        payload: dict[str, Any] = {
            "student_id": state.student_id,
            "operation": operation,
            "session_token": state.session_token,
            "state": self._state_payload(state),
        }
        if gap_duration is not None:
            payload["gap_duration"] = gap_duration
        self.persistence.log_write(payload)

    @staticmethod
    def _state_payload(state: SessionState) -> dict[str, Any]:
        payload = asdict(state)
        payload["answers"] = {str(key): value for key, value in state.answers.items()}
        return payload

    @staticmethod
    def _state_from_operation(operation: dict[str, Any]) -> SessionState:
        payload = operation["state"]
        return SessionState(
            student_id=int(payload["student_id"]),
            exam_id=str(payload["exam_id"]),
            session_token=str(payload["session_token"]),
            current_question=int(payload["current_question"]),
            timer_seconds_remaining=int(payload["timer_seconds_remaining"]),
            answers={int(key): str(value) for key, value in payload["answers"].items()},
            last_event_timestamp=payload["last_event_timestamp"],
        )
