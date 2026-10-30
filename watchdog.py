"""Bağımsız Gözcü Süreç (watchdog.py).

Görevleri:
1. Ders modu aktifken (`lock_active == True`) ana sürecin (`main_pid`) çalışıp çalışmadığını izler.
2. Ana süreç dışarıdan zorla sonlandırılırsa olayı loglar ve `main.py --resume-lock` ile yeniden başlatır.
3. Eğer ana süreç 60 saniye içinde 3 kez üst üste çökerse (crash-loop), sistemi sonsuz kilide sokmamak
   için `recover.run_full_recovery` çalıştırarak tüm kısıtları güvenli biçimde kaldırır.
4. Dead-Man Switch süresini (`TEST_MODE=True` iken 10 dk, `False` iken 14 saat) bağımsız olarak denetler;
   süre dolduğunda tüm kısıtları otomatik olarak kaldırır.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

from app import config
from app.core.database import Database
from app.core.state_snapshot import StateSnapshotManager
import recover

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008


def _log_watchdog(message: str) -> None:
    config.ensure_data_dirs()
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"[{ts}] [PID={os.getpid()}] {message}\n"
    try:
        with open(config.WATCHDOG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        db = Database()
        db.log_audit("WATCHDOG", message)
    except Exception:
        pass


def _spawn_main_process() -> int:
    """Ana süreci (--resume-lock argümanıyla) yeniden başlatır ve yeni PID'yi döndürür."""
    if getattr(sys, "frozen", False):
        main_exe = config.BASE_DIR / "ders_kilidi.exe"
        cmd = [str(main_exe), "--resume-lock"]
    else:
        main_script = config.BASE_DIR / "main.py"
        cmd = [sys.executable, str(main_script), "--resume-lock"]

    proc = subprocess.Popen(
        cmd,
        cwd=str(config.BASE_DIR),
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )
    return int(proc.pid)


def run_watchdog_loop(
    snapshot_path: Path | None = None,
    poll_interval: float = 1.0,
    max_iterations: int | None = None,
) -> str:
    """Watchdog ana izleme döngüsü. Çıkış nedenini döndürür."""
    snap_mgr = StateSnapshotManager(snapshot_path)
    snap_mgr.update_pids(watchdog_pid=os.getpid())
    _log_watchdog("Watchdog izleme döngüsü başlatıldı.")

    iterations = 0
    while True:
        iterations += 1
        state = snap_mgr.read_state()

        if not state.get("lock_active", False):
            _log_watchdog("lock_active=False algılandı, Watchdog normal olarak sonlanıyor.")
            return "lock_inactive"

        # Dead-Man Switch kontrolü
        if snap_mgr.is_expired():
            _log_watchdog("Dead-Man Switch süresi doldu! Otomatik kurtarma başlatılıyor.")
            recover.run_full_recovery(
                reason="dead_man_switch_expired",
                kill_processes=True,
                snapshot_path=snap_mgr.snapshot_path,
            )
            return "dead_man_expired"

        main_pid = int(state.get("main_pid") or 0)
        if main_pid > 0 and not psutil.pid_exists(main_pid):
            # Tekrar oku: belki ana süreç tam o anda normal çıkış yapıp lock_active=False yazmıştır
            time.sleep(0.15)
            state_recheck = snap_mgr.read_state()
            if not state_recheck.get("lock_active", False):
                _log_watchdog("Ana süreç normal çıkış yaptı, Watchdog sonlanıyor.")
                return "lock_inactive"

            is_crash_loop = snap_mgr.record_crash_and_check_loop(window_seconds=60.0, max_crashes=3)
            if is_crash_loop:
                _log_watchdog("Ana süreç 60 sn içinde 3 kez kapandı (Crash-Loop)! Otomatik kurtarma çalıştırılıyor.")
                recover.run_full_recovery(
                    reason="crash_loop_recovery",
                    kill_processes=False,
                    snapshot_path=snap_mgr.snapshot_path,
                )
                return "crash_loop_recovered"

            try:
                new_pid = _spawn_main_process()
                snap_mgr.update_pids(main_pid=new_pid, watchdog_pid=os.getpid())
                _log_watchdog(f"Ana süreç (eski PID={main_pid}) sonlandırıldı; yeniden başlatıldı (yeni PID={new_pid}).")
            except Exception as exc:
                _log_watchdog(f"Ana süreç yeniden başlatılamadı ({exc}); sistem kurtarılıyor.")
                recover.run_full_recovery(
                    reason="main_restart_failed",
                    kill_processes=False,
                    snapshot_path=snap_mgr.snapshot_path,
                )
                return "restart_failed_recovered"

        if max_iterations is not None and iterations >= max_iterations:
            return "max_iterations_reached"

        time.sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ders Kilidi Bağımsız Watchdog Süreci")
    parser.add_argument("--snapshot", type=str, default=None, help="Özel state_snapshot.json dosya yolu")
    args = parser.parse_args(argv)

    snap_path = Path(args.snapshot) if args.snapshot else None
    run_watchdog_loop(snapshot_path=snap_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
