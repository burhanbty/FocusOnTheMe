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


def test_study_folder_subfolder_navigation(tmp_path: Path) -> None:
    """Ders Klasörü panelinde alt klasörlerin göründüğünü, içine girilebildiğini ve üst klasöre dönülebildiğini doğrular."""
    from PySide6.QtWidgets import QApplication
    from app.ui.task_popover import StudyFolderPopover

    app = QApplication.instance() or QApplication([])
    root_dir = tmp_path / "DersKlasoru"
    sub_dir = root_dir / "CENG201" / "Hafta3"
    sub_dir.mkdir(parents=True)
    (root_dir / "Syllabus.pdf").write_text("pdf1", encoding="utf-8")
    (sub_dir / "OOP_Notes.pdf").write_text("pdf2", encoding="utf-8")

    pop = StudyFolderPopover()
    pop.load_folder(str(root_dir))
    app.processEvents()

    # Kök dizinde CENG201 klasörü ve Syllabus.pdf dosyası görünmeli
    root_texts = [pop.file_list.item(i).text() for i in range(pop.file_list.count())]
    assert any("CENG201" in t and "📁" in t for t in root_texts)
    assert any("Syllabus.pdf" in t and "📄" in t for t in root_texts)

    # CENG201 klasörüne tıkla -> içine girmeli
    folder_item = next(
        pop.file_list.item(i)
        for i in range(pop.file_list.count())
        if "CENG201" in pop.file_list.item(i).text()
    )
    pop._on_item_clicked(folder_item)
    app.processEvents()

    sub_texts = [pop.file_list.item(i).text() for i in range(pop.file_list.count())]
    assert any("Üst Klasöre Dön" in t for t in sub_texts)
    assert any("Hafta3" in t and "📁" in t for t in sub_texts)

    # Hafta3 alt klasörüne gir -> OOP_Notes.pdf görünmeli
    week_item = next(
        pop.file_list.item(i)
        for i in range(pop.file_list.count())
        if "Hafta3" in pop.file_list.item(i).text()
    )
    pop._on_item_clicked(week_item)
    app.processEvents()

    week_texts = [pop.file_list.item(i).text() for i in range(pop.file_list.count())]
    assert any("OOP_Notes.pdf" in t for t in week_texts)

    # Üst klasöre dön (..) tıkla -> tekrar CENG201 seviyesine dönmeli
    up_item = pop.file_list.item(0)
    pop._on_item_clicked(up_item)
    app.processEvents()
    back_texts = [pop.file_list.item(i).text() for i in range(pop.file_list.count())]
    assert any("Hafta3" in t for t in back_texts)
    pop.close()


def test_screenshot_proof_dialog_captures_and_saves(tmp_path: Path, monkeypatch) -> None:
    """Ekran görüntüsü kanıt diyaloğunun görüntüyü yakalayıp onaylandığında dosyaya kaydettiğini doğrular."""
    from PySide6.QtWidgets import QApplication
    from app.ui.proof_dialog import ScreenshotProofDialog

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "PROOFS_DIR", tmp_path / "proofs")

    dlg = ScreenshotProofDialog()
    confirmed_results: list[tuple[int, str]] = []
    dlg.proof_confirmed.connect(lambda tid, path: confirmed_results.append((tid, path)))

    sample_task = {"id": 42, "subject": "CENG201", "title": "Lab ödevi"}
    dlg.start_capture_for_task(sample_task, logical_date="2026-10-30")
    app.processEvents()

    assert dlg.isVisible() is True
    dlg._on_confirm_clicked()
    app.processEvents()

    assert len(confirmed_results) == 1
    tid, saved_path = confirmed_results[0]
    assert tid == 42
    assert Path(saved_path).exists()
    dlg.close()


def test_courses_idle_threshold_and_app_usage_tracking(tmp_path: Path) -> None:
    """10 ön tanımlı dersi, 2 dk (120 sn) boşta kalma eşiğini ve ders/uygulama süre takibini doğrular."""
    from PySide6.QtWidgets import QApplication
    from app.core.activity_tracker import is_user_actively_working
    from app.core.database import Database
    from app.ui.top_bar import TopBarWindow

    # Eşik 2 dakika (120 saniye) olmalı
    assert config.IDLE_THRESHOLD_SECONDS == 120
    assert is_user_actively_working(120, idle_seconds_override=45.0) is True
    assert is_user_actively_working(120, idle_seconds_override=119.9) is True
    assert is_user_actively_working(120, idle_seconds_override=120.0) is False
    assert is_user_actively_working(120, idle_seconds_override=300.0) is False

    db = Database(tmp_path / "courses_test.db")
    courses = db.get_courses()
    codes = [c["code"] for c in courses]
    for expected in ("CENG101", "CENG113", "CENG201", "CENG203", "CENG207", "CENG209", "ENGR227", "ENGR265", "MATH101", "MATH201"):
        assert expected in codes

    ldate = "2026-10-30"
    db.set_active_course("CENG201")
    assert db.get_active_course() == "CENG201"

    db.increment_course_study_seconds("CENG201", 125, logical_date=ldate)
    db.increment_app_usage_seconds("msedge.exe", "Microsoft Edge", 90, logical_date=ldate)
    db.increment_app_usage_seconds("sumatrapdf.exe", "SumatraPDF", 35, logical_date=ldate)

    c_stats = db.get_course_study_stats(ldate)
    assert len(c_stats) == 1
    assert c_stats[0]["course_code"] == "CENG201"
    assert c_stats[0]["active_seconds"] == 125

    a_stats = db.get_app_usage_stats(ldate)
    assert len(a_stats) == 2
    assert a_stats[0]["display_name"] == "Microsoft Edge"
    assert a_stats[0]["active_seconds"] == 90

    app = QApplication.instance() or QApplication([])
    bar = TopBarWindow()
    bar.update_course_timer_display("CENG201", 125, is_actively_working=True, courses=courses, course_stats=c_stats, app_stats=a_stats)
    assert "CENG201" in bar.course_timer_btn.text()
    assert "00:02:05" in bar.course_timer_btn.text()
    assert "Boşta" not in bar.course_timer_btn.text()

    bar.update_course_timer_display("CENG201", 125, is_actively_working=False)
    assert "Boşta" in bar.course_timer_btn.text()

    # Çubuk kapatılıp tekrar açıldığında (ör. acil çıkış sonrası yeni oturum) saat sayacı aktif kalmalı
    bar.allow_closing(True)
    bar.close()
    assert bar._clock_timer.isActive() is False

    bar.allow_closing(False)
    bar.show()
    app.processEvents()
    assert bar._clock_timer.isActive() is True

    # Tek işlemli record_active_tick testi
    new_sec = db.record_active_tick(
        logical_date=ldate,
        course_code="CENG201",
        is_active=True,
        app_exe="msedge.exe",
        app_display="Microsoft Edge",
    )
    assert new_sec == 126

    bar.allow_closing(True)
    bar.close()
