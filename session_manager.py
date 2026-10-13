"""OS/DBMS concept: WAL-backed recovery and server-side session state."""

from dataclasses import dataclass
from typing import Mapping, Protocol

from .event_collector import BehaviorEvent


@dataclass(frozen=True)
class SessionState:
    """Authoritative state needed to rehydrate an exam after refresh."""

    student_id: int
    exam_id: str
    session_token: str
    current_question: int
    timer_seconds_remaining: int
    answers: Mapping[int, str]
    last_event_timestamp: float | None


@dataclass(frozen=True)
class RefreshRecovery:
    """Result of reconnecting a page to an existing server session."""

    state: SessionState
    refresh_event: BehaviorEvent
    gap_duration: float


class SessionPersistence(Protocol):
    """Persistence boundary for WAL-before-state application."""

    def log_write(self, operation: object) -> int:
        """Durably append a session operation to the WAL."""

    def replay_log_on_startup(self) -> int:
        """Replay valid operations during recovery."""


class SessionManager:
    """Issue tokens and recover all exam state from the server side."""

    def __init__(self, persistence: SessionPersistence) -> None:
        """Create a manager backed by the bams_core WAL binding."""
        ...

    def start_session(self, student_id: int, exam_id: str) -> SessionState:
        """Issue or return a server-side session for one student and exam."""
        ...

    def apply_state(self, state: SessionState) -> SessionState:
        """Write a state operation to WAL before applying it."""
        ...

    def recover_session(self, session_token: str) -> SessionState:
        """Rehydrate authoritative state after reconnect or process restart."""
        ...

    def record_refresh(self, session_token: str, page_load_timestamp: float) -> RefreshRecovery:
        """Log refresh and return the recovered state plus the event gap."""
        ...

    def update_question(self, session_token: str, question: int) -> SessionState:
        """Persist the current question before changing server-side state."""
        ...

    def record_answer(self, session_token: str, question: int, answer: str) -> SessionState:
        """Persist an answer before applying it to the session state."""
        ...