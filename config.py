"""Application settings and Phase 3 feature gates."""

from dataclasses import dataclass
import os
from pathlib import Path


PHASE3_ACCESS_CONTROL = False
PHASE3_AUDIT_LOG = False
PHASE3_DASHBOARD = False


@dataclass(frozen=True)
class Settings:
    """Runtime configuration shared by the API and engine process."""

    storage_path: Path
    wal_path: Path
    engine_address: str = "127.0.0.1:8765"
    engine_authkey: str = "bams-m2-local"
    engine_timeout_seconds: float = 2.0
    synthetic_data_enabled: bool = False
    phase3_access_control: bool = PHASE3_ACCESS_CONTROL
    phase3_audit_log: bool = PHASE3_AUDIT_LOG
    phase3_dashboard: bool = PHASE3_DASHBOARD
    storage_schema_version: int = 1


def load_settings() -> Settings:
    """Load validated settings from the runtime environment."""
    data_dir = Path(os.environ.get("BAMS_DATA_DIR", "data"))
    return Settings(
        storage_path=Path(os.environ.get("BAMS_STORAGE_PATH", data_dir / "bams.data")),
        wal_path=Path(os.environ.get("BAMS_WAL_PATH", data_dir / "bams.wal")),
        engine_address=os.environ.get("BAMS_ENGINE_ADDRESS", "127.0.0.1:8765"),
        engine_authkey=os.environ.get("BAMS_ENGINE_AUTHKEY", "bams-m2-local"),
        engine_timeout_seconds=float(os.environ.get("BAMS_ENGINE_TIMEOUT", "2.0")),
        synthetic_data_enabled=os.environ.get("BAMS_SYNTHETIC_DATA", "0") == "1",
    )