"""Phase 3 audit boundary for a future hash-chained audit log."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AuditEntry:
    """Structured audit payload reserved for the Phase 3 implementation."""

    action: str
    actor: str | None
    payload: dict[str, Any]
    timestamp: float


class AuditSink(Protocol):
    """Replaceable audit persistence contract."""

    def record(self, entry: AuditEntry) -> None:
        """Persist one audit entry."""

    def verify_chain(self) -> bool:
        """Verify the integrity of the complete audit chain."""


class NullAuditSink:
    """Explicit no-op audit sink used until Phase 3 audit logging is enabled."""

    def record(self, entry: AuditEntry) -> None:
        """Accept no audit entry while reporting the disabled feature status."""
        return None

    def verify_chain(self) -> bool:
        """Report that the Phase 3 audit chain is not available."""
        return False

    def status(self) -> str:
        """Return the UI-visible audit status."""
        return "AUDIT LOG: Phase 3"