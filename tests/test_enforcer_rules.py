"""Korumalı süreçler, TEST_MODE muafiyeti, beyaz liste, non-elevated başlatıcı ve UI bileşen testleri."""

from __future__ import annotations

import os
from pathlib import Path
import time

import psutil

from app import config
from app.core.process_enforcer import is_process_allowed, is_process_protected
from app.core.process_launcher import is_pid_elevated, launch_non_elevated


def test_system_protected_processes_constant() -> None:
    required_protected = {
        "explorer.exe",
        "dwm.exe",
        "csrss.exe",
        "winlogon.exe",
        "services.exe",
        "svchost.exe",
        "msmpeng.exe",
        "ders_kilidi.exe",
        "ders_kilidi_watchdog.exe",
        "recover.exe",
    }
    for proc_name in required_protected:
        assert proc_name in config.SYSTEM_PROTECTED_PROCESSES
        assert is_process_protected(proc_name) is True

    assert is_process_protected("notepad.exe") is False
    assert is_process_protected("chrome.exe") is False


def test_test_mode_exemptions_and_whitelist() -> None:
    allowed_paths = {os.path.normcase(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")}
    allowed_names = {"msedge.exe"}

    # İzinli uygulama her iki modda da serbest
    assert is_process_allowed("msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", allowed_paths, allowed_names, test_mode=True)
    assert is_process_allowed("msedge.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", allowed_paths, allowed_names, test_mode=False)

    # TEST_MODE=True iken cmd, powershell, taskmgr muaf
    for tool in ("cmd.exe", "powershell.exe", "pwsh.exe", "taskmgr.exe"):
        assert is_process_allowed(tool, rf"C:\Windows\System32\{tool}", allowed_paths, allowed_names, test_mode=True) is True
        assert is_process_allowed(tool, rf"C:\Windows\System32\{tool}", allowed_paths, allowed_names, test_mode=False) is False

    # İzinsiz uygulama (notepad.exe) her iki modda da engelli
    assert is_process_allowed("notepad.exe", r"C:\Windows\System32\notepad.exe", allowed_paths, allowed_names, test_mode=True) is False
    assert is_process_allowed("notepad.exe", r"C:\Windows\System32\notepad.exe", allowed_paths, allowed_names, test_mode=False) is False


def test_non_elevated_launcher_starts_non_admin_process() -> None:
    """Çubuktan/başlatıcıdan açılan uygulamanın yönetici yetkisiyle (elevated) çalışmadığını doğrular."""
    res = launch_non_elevated(r"C:\Windows\System32\hostname.exe")
    assert res["ok"] is True
    assert res["elevated"] is False


def test_ui_top_bar_and_popover_geometry(tmp_path: Path) -> None:
    """Üst çubuk konumunu (8px boşluk, 44px yükseklik) ve görev/klasör popover panellerini doğrular."""
    from PySide6.QtWidgets import QApplication
    from app.ui.top_bar import TopBarWindow

    app = QApplication.instance() or QApplication([])
    bar = TopBarWindow()
    bar.show()
    app.processEvents()

    # Üst çubuk ekranın üstünde 8 px boşluklu ve 44 px yüksekliğinde olmalı
    assert bar.x() == config.TOP_BAR_MARGIN  # 8 px
    assert bar.y() == config.TOP_BAR_MARGIN  # 8 px
    assert bar.height() == config.TOP_BAR_HEIGHT  # 44 px
    assert bar.test_mode_badge.isVisible() is True

    # Görev yükleme ve orta buton metni
    sample_tasks = [
        {"id": 1, "subject": "Matematik", "title": "20 soru çöz", "estimated_minutes": 30, "completed": 1},
        {"id": 2, "subject": "Fizik", "title": "Optik tekrarı", "estimated_minutes": 45, "completed": 0},
    ]
    bar.set_tasks(sample_tasks)
    assert "Fizik: Optik tekrarı" in bar.center_task_btn.text()
    assert "1/2" in bar.center_task_btn.text()

    # Görev panelini (TaskPopover) açıp kapatma
    from PySide6.QtTest import QTest

    bar.toggle_task_popover()
    QTest.qWait(150)
    assert bar.task_popover.isVisible() is True

    bar.toggle_task_popover()
    QTest.qWait(180)
    assert bar.task_popover.isVisible() is False

    # Ders Klasörü panelini (StudyFolderPopover) test etme
    study_dir = tmp_path / "DersNotlari"
    study_dir.mkdir()
    (study_dir / "Turev_Notlari.pdf").write_text("dummy pdf", encoding="utf-8")
    bar.set_study_folder(str(study_dir))
    bar.toggle_study_folder_popover()
    app.processEvents()
    assert bar.folder_popover.isVisible() is True
    assert bar.folder_popover.file_list.count() == 1

    bar.folder_popover.hide()
    bar.allow_closing(True)
    bar.close()


def test_enforcer_5s_countdown_wm_close_and_explorer_folder(monkeypatch) -> None:
    """5 sn geri sayım -> WM_CLOSE -> 3 sn kill döngüsünü ve Explorer klasör penceresi WM_CLOSE davranışını doğrular."""
    import win32con
    import win32gui
    from app.core.process_enforcer import ProcessEnforcer

    fake_now = [100.0]
    closed_apps: list[str] = []
    posted_messages: list[tuple[int, int]] = []

    enforcer = ProcessEnforcer(
        on_app_closed=lambda name: closed_apps.append(name),
        time_fn=lambda: fake_now[0],
    )
    enforcer.set_allowed_apps([{"name": "Edge", "exe_path": r"C:\Edge\msedge.exe", "exe_name": "msedge.exe", "enabled": 1}])

    # Sahte pencere listesi: 1 adet Explorer klasör penceresi (CabinetWClass) + 1 adet izinsiz uygulama (notepad.exe)
    fake_windows = [
        {
            "hwnd": 1001,
            "pid": 4444,
            "class_name": "CabinetWClass",
            "title": "İndirilenler",
            "exe_name": "explorer.exe",
            "exe_path": r"C:\Windows\explorer.exe",
            "rect": (100, 100, 800, 600),
        },
        {
            "hwnd": 2002,
            "pid": 888888,
            "class_name": "Notepad",
            "title": "Adsız - Not Defteri",
            "exe_name": "notepad.exe",
            "exe_path": r"C:\Windows\System32\notepad.exe",
            "rect": (100, 100, 800, 600),
        },
    ]

    monkeypatch.setattr(enforcer, "_enumerate_relevant_windows", lambda: fake_windows)
    monkeypatch.setattr(win32gui, "PostMessage", lambda h, m, w, l: posted_messages.append((h, m)))
    monkeypatch.setattr(win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda h: True)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)

    # t=100.0 (0. sn): Explorer klasörü anında WM_CLOSE alır, notepad için 5 sn geri sayım başlar
    w0 = enforcer.tick()
    assert (1001, win32con.WM_CLOSE) in posted_messages
    assert (2002, win32con.WM_CLOSE) not in posted_messages
    assert len(w0) == 1
    assert w0[0]["exe_name"] == "notepad.exe"
    assert w0[0]["remaining_seconds"] == 5
    assert w0[0]["stage"] == "countdown"

    # t=103.0 (3. sn): Kalan süre 2 sn
    fake_now[0] = 103.0
    w3 = enforcer.tick()
    assert w3[0]["remaining_seconds"] == 2
    assert (2002, win32con.WM_CLOSE) not in posted_messages

    # t=105.1 (5. sn doldu): notepad'e WM_CLOSE gönderilir
    fake_now[0] = 105.1
    w5 = enforcer.tick()
    assert (2002, win32con.WM_CLOSE) in posted_messages
    assert w5[0]["stage"] == "closing"
    assert closed_apps == []

    # t=108.5 (+3 sn grace süresi doldu): zorla kapatılır ve istatistiğe yazılır
    fake_now[0] = 108.5
    enforcer.tick()
    assert "notepad.exe" in closed_apps


def test_morning_setup_requires_at_least_one_task(tmp_path: Path) -> None:
    """Görev yoksa Ders Modunu Başlat butonunun devre dışı olduğunu, görev eklenince aktifleştiğini doğrular."""
    from PySide6.QtWidgets import QApplication
    from app.core.auth import EmergencyAuthManager
    from app.core.database import Database
    from app.ui.morning_setup import MorningSetupWindow

    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "setup_test.db")
    auth = EmergencyAuthManager(db)
    win = MorningSetupWindow(db, auth)

    assert win.start_btn.isEnabled() is False

    win.subject_edit.setText("Matematik")
    win.task_title_edit.setText("25 soru çöz")
    win._add_task()
    app.processEvents()

    assert win.start_btn.isEnabled() is True
    win.close()
