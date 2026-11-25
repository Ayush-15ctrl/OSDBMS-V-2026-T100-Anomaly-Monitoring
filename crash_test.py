"""Crash-recovery smoke test for the Milestone 2 reference engine."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.engine_service.process import EngineSupervisor


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="bams-crash-test-"))
    supervisor: EngineSupervisor | None = None
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        settings = Settings(root / "bams.data", root / "bams.wal", engine_address=f"127.0.0.1:{port}")
        supervisor = EngineSupervisor(settings)
        supervisor.start()
        written = 500
        for sequence in range(500):
            supervisor.client.write_event({"student_id": 7, "event_type": "keypress", "timestamp": time.time(), "value": float(sequence)})
        assert supervisor.process is not None
        in_flight = threading.Event()
        write_errors: list[Exception] = []

        def write_during_kill() -> None:
            in_flight.set()
            try:
                supervisor.client.write_event({"student_id": 7, "event_type": "keypress", "timestamp": time.time(), "value": 500.0})
            except Exception as error:
                write_errors.append(error)

        writer = threading.Thread(target=write_during_kill, daemon=True)
        writer.start()
        if not in_flight.wait(timeout=1):
            raise RuntimeError("crash test writer did not enter the in-flight phase")
        time.sleep(0.01)
        supervisor.process.terminate()
        supervisor.process.join(timeout=2)
        if supervisor.process.is_alive():
            supervisor.process.kill()
            supervisor.process.join(timeout=2)
        if supervisor.process.is_alive():
            raise RuntimeError("engine worker did not terminate after kill")
        writer.join(timeout=2)
        if writer.is_alive():
            raise RuntimeError("crash test writer did not finish after worker termination")

        supervisor.start()
        recovered_before_completion = supervisor.client.read_records(7, 0, 2000)
        recovered_values = {int(item["value"]) for item in recovered_before_completion}
        for sequence in range(500, 1000):
            if sequence not in recovered_values:
                supervisor.client.write_event({"student_id": 7, "event_type": "keypress", "timestamp": time.time(), "value": float(sequence)})
        records = supervisor.client.read_records(7, 0, 2000)
        values = [int(item["value"]) for item in records]
        recovered = len(set(values))
        duplicated = len(values) - recovered
        lost = written + 500 - recovered
        print(f"killed_while_write={in_flight.is_set()} write_errors={len(write_errors)} written={written + 500} recovered={recovered} lost={lost} duplicated={duplicated}")
        if lost != 0 or duplicated != 0:
            raise SystemExit(1)
    finally:
        if supervisor is not None:
            supervisor.stop()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()