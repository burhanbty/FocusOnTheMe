"""Durum yedeği, Dead-Man Switch (10 dk TEST_MODE / 14 saat), Crash-Loop ve recover.py testleri."""

from __future__ import annotations

from pathlib import Path
import time

from app import config
from app.core.rollback import build_recovery_command
from app.core.state_snapshot import StateSnapshotManager
from app.core.taskbar_lock import fit_window_to_work_area, get_work_area_rect, hide_taskbar, show_taskbar
import recover


def test_config_invariants_and_test_mode_timeout() -> None:
    # İlk sürümde TEST_MODE varsayılan True olmalı
    assert config.TEST_MODE is True
    # Karar 3: REBOOT_CLEARS_LOCK sabiti OLMAMALI
    assert not hasattr(config, "REBOOT_CLEARS_LOCK")

    # TEST_MODE=True iken 10 dk (600 sn), False iken 14 saat (50.400 sn)
    assert config.get_dead_man_timeout_seconds(True) == 600
    assert config.get_dead_man_timeout_seconds(False) == 14 * 3600


def test_state_snapshot_dead_man_switch_and_crash_loop(tmp_path: Path) -> None:
    snap_file = tmp_path / "state_snapshot.json"
    mgr = StateSnapshotManager(snap_file)

    assert mgr.read_state()["lock_active"] is False

    state = mgr.activate_lock(main_pid=1234, watchdog_pid=5678, logical_date="2026-10-30", timeout_seconds=600)
    assert state["lock_active"] is True
    assert state["timeout_seconds"] == 600

    now = state["started_at"]
    assert not mgr.is_expired(now + 599)
    assert mgr.is_expired(now + 600)
    assert mgr.get_remaining_seconds(now + 200) == 400

    # Crash-loop: 60 sn içinde 3 çökme
    assert not mgr.record_crash_and_check_loop(window_seconds=60.0, max_crashes=3)
    assert not mgr.record_crash_and_check_loop(window_seconds=60.0, max_crashes=3)
    assert mgr.record_crash_and_check_loop(window_seconds=60.0, max_crashes=3)

    mgr.deactivate_lock(reason="test_done")
    assert mgr.read_state()["lock_active"] is False


def test_work_area_calculation() -> None:
    x, y, w, h = get_work_area_rect(screen_width=1920, screen_height=1080)
    assert x == 0
    assert y == config.TOP_BAR_HEIGHT + 16  # 44 + 16 = 60
    assert w == 1920
    assert h == 1080 - 60


def test_build_recovery_command_contains_auto_boot_clean() -> None:
    cmd = build_recovery_command()
    assert "--auto-boot-clean" in cmd
    assert "recover" in cmd.lower()


def test_recover_script_clears_snapshot_and_restores_taskbar(tmp_path: Path) -> None:
    snap_file = tmp_path / "state_snapshot.json"
    mgr = StateSnapshotManager(snap_file)
    mgr.activate_lock(main_pid=999999, watchdog_pid=999998)
    assert mgr.read_state()["lock_active"] is True

    try:
        hide_taskbar()
        summary = recover.run_full_recovery(
            reason="unit_test_recovery",
            kill_processes=False,
            snapshot_path=snap_file,
        )
        assert summary["taskbar_restored"] is True
        assert mgr.read_state()["lock_active"] is False
    finally:
        show_taskbar()


def test_fit_window_to_work_area_avoids_top_bar() -> None:
    """İzinli uygulama penceresinin çubukla çakışmadan (y=60) çalışma alanına oturduğunu doğrular."""
    import win32gui
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    dummy_win = QWidget()
    dummy_win.setWindowTitle("Test İzinli Pencere")
    dummy_win.setGeometry(10, 10, 500, 400)
    dummy_win.show()
    app.processEvents()

    hwnd = int(dummy_win.winId())
    ok = fit_window_to_work_area(hwnd, screen_width=1920, screen_height=1080)
    assert ok is True

    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    assert left == 0
    assert top == config.WORK_AREA_TOP_OFFSET  # 44 + 16 = 60
    assert (right - left) == 1920
    assert (bottom - top) == 1080 - 60

    dummy_win.close()


def test_edge_policy_apply_and_clear_hkcu() -> None:
    """Edge politikalarının HKCU altına yazılıp çıkışta temizlendiğini doğrular."""
    from app.core.edge_policy import apply_edge_policies, clear_edge_policies, read_edge_policy_state

    try:
        res = apply_edge_policies(["gemini.google.com", "scholar.google.com"])
        assert res["hkcu"] is True

        state = read_edge_policy_state()
        assert state["hkcu"]["inprivate_disabled"] is True
        assert state["hkcu"]["guest_disabled"] is True
        assert state["hkcu"]["blocklist"] == ["*"]
        assert "gemini.google.com" in state["hkcu"]["allowlist"]
    finally:
        clear_res = clear_edge_policies()
        assert clear_res["hkcu"] is True
        after = read_edge_policy_state()
        assert after["hkcu"]["blocklist"] == []
        assert after["hkcu"]["allowlist"] == []


def test_watchdog_unlocks_when_test_mode_dead_man_expires(tmp_path: Path) -> None:
    """TEST_MODE=True (10 dk) dead-man süresi dolduğunda Watchdog'un kilidi otomatik açtığını doğrular."""
    import watchdog

    snap_file = tmp_path / "wd_snapshot.json"
    mgr = StateSnapshotManager(snap_file)
    state = mgr.activate_lock(timeout_seconds=600)
    # Süreyi geçmişe çekerek 10 dakikanın dolduğunu simüle et
    state["expires_at"] = time.time() - 5.0
    mgr.write_state(state)

    reason = watchdog.run_watchdog_loop(snapshot_path=snap_file, poll_interval=0.05, max_iterations=2)
    assert reason == "dead_man_expired"
    assert mgr.read_state()["lock_active"] is False
