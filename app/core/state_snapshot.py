"""Atomik durum yedeği (state_snapshot.json) ve Dead-Man Switch durumu yöneticisi."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app import config
from app.core.logical_date import get_logical_date


class StateSnapshotManager:
    """Kilit durumunu, süreç PID'lerini ve dead-man süresini atomik olarak diske yazar/okur."""

    def __init__(self, snapshot_path: Path | str | None = None) -> None:
        config.ensure_data_dirs()
        self.snapshot_path = (
            Path(snapshot_path) if snapshot_path is not None else config.STATE_SNAPSHOT_PATH
        )
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    def read_state(self) -> dict[str, Any]:
        if not self.snapshot_path.exists():
            return {"lock_active": False}
        try:
            content = self.snapshot_path.read_text(encoding="utf-8")
            data = json.loads(content)
            return data if isinstance(data, dict) else {"lock_active": False}
        except Exception:
            return {"lock_active": False}

    def write_state(self, state: dict[str, Any]) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.snapshot_path.with_suffix(f".tmp.{os.getpid()}")
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(str(tmp_path), str(self.snapshot_path))

    def activate_lock(
        self,
        main_pid: int | None = None,
        watchdog_pid: int | None = None,
        logical_date: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        duration = (
            timeout_seconds
            if timeout_seconds is not None
            else config.get_dead_man_timeout_seconds()
        )
        expires_at = now + duration
        state: dict[str, Any] = {
            "lock_active": True,
            "logical_date": logical_date or get_logical_date(),
            "started_at": now,
            "started_at_iso": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "expires_at": expires_at,
            "expires_at_iso": datetime.fromtimestamp(expires_at).isoformat(timespec="seconds"),
            "timeout_seconds": duration,
            "test_mode": bool(config.TEST_MODE),
            "main_pid": main_pid if main_pid is not None else os.getpid(),
            "watchdog_pid": watchdog_pid or 0,
            "crash_timestamps": [],
        }
        self.write_state(state)
        return state

    def update_pids(self, main_pid: int | None = None, watchdog_pid: int | None = None) -> None:
        state = self.read_state()
        if main_pid is not None:
            state["main_pid"] = main_pid
        if watchdog_pid is not None:
            state["watchdog_pid"] = watchdog_pid
        self.write_state(state)

    def record_crash_and_check_loop(
        self,
        window_seconds: float = 60.0,
        max_crashes: int = 3,
    ) -> bool:
        """Ana süreç beklenmedik şekilde kapandığında zaman damgasını kaydeder.

        Eğer son `window_seconds` içinde `max_crashes` veya daha fazla çökme olduysa
        True (çökme döngüsü algılandı) döndürür.
        """
        state = self.read_state()
        now = time.time()
        crashes = [
            float(ts)
            for ts in state.get("crash_timestamps", [])
            if (now - float(ts)) <= window_seconds
        ]
        crashes.append(now)
        state["crash_timestamps"] = crashes
        self.write_state(state)
        return len(crashes) >= max_crashes

    def is_expired(self, now: float | None = None) -> bool:
        """Dead-man switch süresinin dolup dolmadığını kontrol eder."""
        state = self.read_state()
        if not state.get("lock_active", False):
            return False
        expires_at = float(state.get("expires_at", 0.0))
        if expires_at <= 0:
            return False
        current = now if now is not None else time.time()
        return current >= expires_at

    def get_remaining_seconds(self, now: float | None = None) -> int:
        state = self.read_state()
        if not state.get("lock_active", False):
            return 0
        expires_at = float(state.get("expires_at", 0.0))
        current = now if now is not None else time.time()
        return max(0, int(round(expires_at - current)))

    def deactivate_lock(self, reason: str = "normal") -> None:
        state = self.read_state()
        state["lock_active"] = False
        state["deactivated_at"] = time.time()
        state["deactivated_at_iso"] = datetime.now().isoformat(timespec="seconds")
        state["deactivated_reason"] = reason
        self.write_state(state)
