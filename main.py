"""Ders Kilidi (FocusMe) — Ana Uygulama Giriş Noktası ve Denetleyicisi (main.py)."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from typing import Any

import psutil
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app import config
from app.core.activity_tracker import get_foreground_app_info, is_user_actively_working
from app.core.auth import EmergencyAuthManager
from app.core.database import Database
from app.core.input_blocker import InputBlocker
from app.core.logical_date import get_logical_date
from app.core.process_enforcer import ProcessEnforcer
from app.core.process_launcher import launch_non_elevated, open_file_in_default_app
from app.core.rollback import apply_all_system_locks, rollback_all_system_locks
from app.core.state_snapshot import StateSnapshotManager
from app.core.taskbar_lock import ensure_taskbar_hidden
from app.ui.backdrop_window import DesktopBackdropWindow
from app.ui.emergency_dialog import EmergencyExitDialog
from app.ui.morning_setup import MorningSetupWindow
from app.ui.proof_dialog import ScreenshotProofDialog
from app.ui.summary_screen import SummaryScreenWindow
from app.ui.thought_modal import ThoughtModal
from app.ui.top_bar import TopBarWindow
from app.ui.warning_toast import WarningToast
import recover

CREATE_NEW_PROCESS_GROUP = 0x00000200


class ThreadSafeBridge(QObject):
    """Arka plan klavye kancası (keyboard thread) ile Qt ana thread'i arasındaki güvenli sinyal köprüsü."""

    open_thought_modal_signal = Signal()


class StudyLockController(QObject):
    """Sabah kurulum ekranı, ders kilidi kabuğu, denetleyici döngüsü ve özet ekranını yöneten ana sınıf."""

    def __init__(self, app: QApplication, resume_mode: bool = False) -> None:
        super().__init__()
        self.app = app
        self.resume_mode = resume_mode

        config.ensure_data_dirs()
        self.db = Database()
        self.auth_mgr = EmergencyAuthManager(self.db)
        self.snapshot_mgr = StateSnapshotManager()

        self.bridge = ThreadSafeBridge()
        self.bridge.open_thought_modal_signal.connect(self.open_thought_modal)

        self.input_blocker = InputBlocker(
            on_thought_shortcut=lambda: self.bridge.open_thought_modal_signal.emit()
        )
        self.enforcer = ProcessEnforcer(
            on_warning_update=self._on_warnings_updated,
            on_app_closed=self._on_unauthorized_app_closed,
        )

        # Pencereler
        self.setup_win: MorningSetupWindow | None = None
        self.backdrop_win: DesktopBackdropWindow | None = None
        self.top_bar_win: TopBarWindow | None = None
        self.warning_toast: WarningToast | None = None
        self.thought_modal: ThoughtModal | None = None
        self.emergency_dialog: EmergencyExitDialog | None = None
        self.proof_dialog: ScreenshotProofDialog | None = None
        self.summary_win: SummaryScreenWindow | None = None

        self._lock_active: bool = False
        self._watchdog_pid: int = 0

        # 1 saniyelik ana denetim zamanlayıcısı
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(config.ENFORCER_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._on_second_tick)

    def start(self) -> None:
        state = self.snapshot_mgr.read_state()
        if state.get("lock_active", False):
            if self.snapshot_mgr.is_expired():
                rollback_all_system_locks(reason="expired_on_startup")
                self.show_morning_setup()
                return
            if self.resume_mode:
                self.enter_study_lock_mode(resumed=True)
                return
            # Eğer başka bir ana süreç şu an canlı olarak çalışıyorsa onun durumunu bozma, çık
            existing_main_pid = int(state.get("main_pid") or 0)
            if existing_main_pid > 0 and existing_main_pid != os.getpid() and psutil.pid_exists(existing_main_pid):
                sys.exit(0)
            rollback_all_system_locks(reason="stale_session_cleanup")

        self.show_morning_setup()

    def show_morning_setup(self) -> None:
        if self.summary_win is not None:
            self.summary_win.hide()
        if self.setup_win is None:
            self.setup_win = MorningSetupWindow(self.db, self.auth_mgr)
            self.setup_win.start_study_mode_requested.connect(self.enter_study_lock_mode)
        self.setup_win.refresh_all()
        self.setup_win.show()
        self.setup_win.raise_()
        self.setup_win.activateWindow()

    def enter_study_lock_mode(self, resumed: bool = False) -> None:
        logical_date = get_logical_date()
        tasks = self.db.get_tasks_for_date(logical_date)
        if not tasks:
            self.show_morning_setup()
            return

        if self.setup_win is not None:
            self.setup_win.hide()

        self._lock_active = True
        self.db.start_or_resume_session(logical_date)

        # İlk tamamlanmamış görevin dersini varsayılan aktif ders olarak senkronize et
        first_pending = next((t for t in tasks if not t.get("completed")), None)
        if first_pending and first_pending.get("subject"):
            subj = str(first_pending["subject"]).strip()
            if subj:
                self.db.set_active_course(subj)

        # 1. Sistem kısıtlarını ve durum yedeğini etkinleştir
        allowed_urls = self.db.get_allowed_urls(only_enabled=True)
        if not resumed:
            apply_all_system_locks(
                allowed_urls=allowed_urls,
                logical_date=logical_date,
            )
        else:
            self.snapshot_mgr.update_pids(main_pid=os.getpid())
            ensure_taskbar_hidden()

        # 2. Bağımsız Watchdog sürecini başlat veya mevcut olanı doğrula
        self._ensure_watchdog_running()

        # 3. Beyaz listeyi denetleyiciye yükle
        allowed_apps = self.db.get_allowed_apps(only_enabled=True)
        self.enforcer.set_allowed_apps(allowed_apps)
        self.enforcer.register_own_pid(os.getpid())
        if self._watchdog_pid > 0:
            self.enforcer.register_own_pid(self._watchdog_pid)

        # 4. Kabuk pencerelerini oluştur ve göster
        if self.backdrop_win is None:
            self.backdrop_win = DesktopBackdropWindow()
        self.backdrop_win.allow_closing(False)
        self.backdrop_win.showFullScreen()

        if self.top_bar_win is None:
            self.top_bar_win = TopBarWindow()
            self.top_bar_win.app_launch_requested.connect(self._on_launch_app)
            self.top_bar_win.task_toggled.connect(self._on_task_toggled)
            self.top_bar_win.course_changed.connect(self._on_course_changed)
            self.top_bar_win.course_popover_opening.connect(
                lambda: self._refresh_top_bar_course_and_activity(
                    is_actively_working=is_user_actively_working(config.IDLE_THRESHOLD_SECONDS),
                    full_lists=True,
                )
            )
            self.top_bar_win.thought_parking_requested.connect(self.open_thought_modal)
            self.top_bar_win.study_file_open_requested.connect(self._on_open_study_file)
            self.top_bar_win.emergency_exit_requested.connect(self.open_emergency_dialog)

        self.top_bar_win.allow_closing(False)
        self.top_bar_win.refresh_test_mode_badge()
        self.top_bar_win.set_allowed_apps(allowed_apps)
        self.top_bar_win.set_tasks(tasks)
        self.top_bar_win.set_study_folder(self.db.get_study_folder())
        self._refresh_top_bar_course_and_activity(is_actively_working=True, full_lists=True)
        self.top_bar_win.show()
        self.top_bar_win.raise_()

        if self.warning_toast is None:
            self.warning_toast = WarningToast()

        if self.thought_modal is None:
            self.thought_modal = ThoughtModal()
            self.thought_modal.thought_submitted.connect(self._on_thought_submitted)

        if self.emergency_dialog is None:
            self.emergency_dialog = EmergencyExitDialog(self.auth_mgr)
            self.emergency_dialog.emergency_unlocked.connect(
                lambda: self.exit_study_lock_mode(reason="emergency_exit", show_summary=False)
            )

        if self.proof_dialog is None:
            self.proof_dialog = ScreenshotProofDialog()
            self.proof_dialog.proof_confirmed.connect(self._on_proof_confirmed)
            self.proof_dialog.proof_cancelled.connect(self._on_proof_cancelled)

        # 5. Klavye kancasını ve 1 sn'lik denetim döngüsünü başlat
        self.input_blocker.start()
        self._tick_timer.start()

    def _ensure_watchdog_running(self) -> None:
        if not self._lock_active:
            return
        state = self.snapshot_mgr.read_state()
        if not state.get("lock_active", False):
            return
        existing_wd_pid = int(state.get("watchdog_pid") or 0)
        if existing_wd_pid > 0 and psutil.pid_exists(existing_wd_pid):
            self._watchdog_pid = existing_wd_pid
            self.enforcer.register_own_pid(existing_wd_pid)
            return

        try:
            if getattr(sys, "frozen", False):
                wd_exe = config.BASE_DIR / "ders_kilidi_watchdog.exe"
                if not wd_exe.exists():
                    return
                cmd = [str(wd_exe)]
            else:
                wd_script = config.BASE_DIR / "watchdog.py"
                python_exe = sys.executable
                cmd = [python_exe, str(wd_script)]

            proc = subprocess.Popen(
                cmd,
                cwd=str(config.BASE_DIR),
                creationflags=CREATE_NEW_PROCESS_GROUP,
            )
            self._watchdog_pid = int(proc.pid)
            self.snapshot_mgr.update_pids(main_pid=os.getpid(), watchdog_pid=self._watchdog_pid)
            self.enforcer.register_own_pid(self._watchdog_pid)
        except Exception:
            pass

    def _on_course_changed(self, course_code: str) -> None:
        self.db.set_active_course(course_code)
        actively_working = is_user_actively_working(config.IDLE_THRESHOLD_SECONDS)
        self._refresh_top_bar_course_and_activity(is_actively_working=actively_working, full_lists=True)

    def _refresh_top_bar_course_and_activity(
        self,
        is_actively_working: bool,
        full_lists: bool = False,
        known_course_sec: int | None = None,
    ) -> None:
        if self.top_bar_win is None:
            return
        logical_date = get_logical_date()
        active_course = self.db.get_active_course()
        course_sec = (
            known_course_sec
            if known_course_sec is not None
            else self.db.get_course_study_seconds(active_course, logical_date)
        )

        # Tam listeleri yalnızca başlangıçta, ders değiştiğinde veya popover açıkken sorgula
        need_lists = full_lists or self.top_bar_win.course_popover.isVisible()
        courses = self.db.get_courses() if need_lists else None
        course_stats = self.db.get_course_study_stats(logical_date) if need_lists else None
        app_stats = self.db.get_app_usage_stats(logical_date) if need_lists else None

        self.top_bar_win.update_course_timer_display(
            course_code=active_course,
            active_seconds=course_sec,
            is_actively_working=is_actively_working,
            courses=courses,
            course_stats=course_stats,
            app_stats=app_stats,
        )

    def _on_second_tick(self) -> None:
        if not self._lock_active:
            return

        # 1. Dead-Man Switch süresi doldu mu?
        if self.snapshot_mgr.is_expired():
            self.db.log_audit("DEAD_MAN_SWITCH", "Dead-Man Switch süresi doldu, kilit otomatik açıldı.")
            self.exit_study_lock_mode(reason="dead_man_expired", show_summary=True)
            return

        # 2. Görev çubuğunun gizli kaldığından emin ol
        ensure_taskbar_hidden()

        # 3. Kullanıcı aktif olarak çalışıyor mu? (Son 2 dk = 120 sn içinde fare/scroll/dokunma/klavye var mı?)
        logical_date = get_logical_date()
        actively_working = is_user_actively_working(config.IDLE_THRESHOLD_SECONDS)
        active_course = self.db.get_active_course()

        app_exe: str | None = None
        app_disp: str | None = None
        if actively_working:
            fg_app = get_foreground_app_info(own_pids=self.enforcer.own_pids)
            if fg_app is not None:
                app_exe = fg_app["exe_name"]
                app_disp = fg_app["display_name"]

        course_sec = self.db.record_active_tick(
            logical_date=logical_date,
            course_code=active_course,
            is_active=actively_working,
            app_exe=app_exe,
            app_display=app_disp,
        )

        self._refresh_top_bar_course_and_activity(
            is_actively_working=actively_working,
            full_lists=False,
            known_course_sec=course_sec,
        )

        # 4. Watchdog hala hayatta mı kontrol et
        self._ensure_watchdog_running()

        # 5. Pencere ve süreç denetleyicisini çalıştır
        self.enforcer.tick()

    def _on_warnings_updated(self, warnings: list[dict[str, Any]]) -> None:
        if self.warning_toast is not None:
            self.warning_toast.update_warnings(warnings)

    def _on_unauthorized_app_closed(self, app_name: str) -> None:
        self.db.increment_blocked_app_count(app_name=app_name)

    def _on_launch_app(self, exe_path: str) -> None:
        res = launch_non_elevated(exe_path)
        self.db.log_audit(
            "APP_LAUNCH",
            f"Uygulama başlatıldı: {exe_path} (yöntem={res.get('method')}, elevated={res.get('elevated')})",
        )

    def _on_open_study_file(self, file_path: str) -> None:
        open_file_in_default_app(file_path)

    def _on_task_toggled(self, task_id: int, completed: bool) -> None:
        logical_date = get_logical_date()

        # Eğer görev tamamlanıyorsa ve ekran görüntüsü kanıtı zorunluysa:
        # Görev panelini gizle ve 250 ms sonra Ekran Görüntüsü Kanıtı onay diyaloğunu aç
        if completed and self.db.is_screenshot_proof_required():
            tasks = self.db.get_tasks_for_date(logical_date)
            target_task = next((t for t in tasks if int(t["id"]) == int(task_id)), None)
            if target_task is not None and self.proof_dialog is not None:
                if self.top_bar_win is not None:
                    self.top_bar_win.task_popover.hide()
                QTimer.singleShot(
                    250,
                    lambda t=target_task, d=logical_date: self.proof_dialog.start_capture_for_task(t, d)
                    if self.proof_dialog is not None
                    else None,
                )
                return

        self._finalize_task_completion(task_id=task_id, completed=completed, proof_path=None)

    def _on_proof_confirmed(self, task_id: int, saved_path: str) -> None:
        self._finalize_task_completion(
            task_id=task_id,
            completed=True,
            proof_path=saved_path or None,
        )

    def _on_proof_cancelled(self, task_id: int) -> None:
        # Kullanıcı kanıt ekranında Vazgeç'e bastı -> görevi tamamlanmamış olarak koru
        logical_date = get_logical_date()
        self.db.set_task_completed(task_id=task_id, completed=False)
        tasks = self.db.get_tasks_for_date(logical_date)
        if self.top_bar_win is not None:
            self.top_bar_win.set_tasks(tasks)

    def _finalize_task_completion(
        self,
        task_id: int,
        completed: bool,
        proof_path: str | None = None,
    ) -> None:
        logical_date = get_logical_date()
        self.db.set_task_completed(task_id=task_id, completed=completed, proof_path=proof_path)
        tasks = self.db.get_tasks_for_date(logical_date)

        # Sıradaki tamamlanmamış görevin dersine otomatik geçiş yap
        next_pending = next((t for t in tasks if not t.get("completed")), None)
        if next_pending and next_pending.get("subject"):
            self.db.set_active_course(str(next_pending["subject"]).strip())

        if self.top_bar_win is not None:
            self.top_bar_win.set_tasks(tasks)
            self._refresh_top_bar_course_and_activity(
                is_actively_working=is_user_actively_working(config.IDLE_THRESHOLD_SECONDS)
            )

        # Tüm görevler tamamlandıysa oturumu bitir ve tebrik ekranını aç
        if tasks and all(bool(t.get("completed")) for t in tasks):
            self.db.mark_session_status("completed", logical_date)
            self.exit_study_lock_mode(reason="all_tasks_completed", show_summary=True)

    def open_thought_modal(self) -> None:
        if not self._lock_active or self.thought_modal is None:
            return
        self.thought_modal.open_modal()

    def _on_thought_submitted(self, text: str) -> None:
        self.db.add_thought(text)

    def open_emergency_dialog(self) -> None:
        if not self._lock_active or self.emergency_dialog is None:
            return
        self.emergency_dialog.open_dialog()

    def exit_study_lock_mode(self, reason: str = "normal", show_summary: bool = True) -> None:
        self._lock_active = False
        self._tick_timer.stop()
        self.input_blocker.stop()

        rollback_all_system_locks(reason=reason, delete_scheduled_task=True)

        if reason == "emergency_exit":
            self.db.mark_session_status("emergency_exit")

        for win in (self.warning_toast, self.thought_modal, self.emergency_dialog, self.proof_dialog):
            if win is not None:
                win.hide()

        if self.top_bar_win is not None:
            self.top_bar_win.task_popover.hide()
            self.top_bar_win.folder_popover.hide()
            self.top_bar_win.course_popover.hide()
            self.top_bar_win.allow_closing(True)
            self.top_bar_win.close()

        if self.backdrop_win is not None:
            self.backdrop_win.allow_closing(True)
            self.backdrop_win.close()

        if show_summary:
            self._show_summary_screen()
        else:
            self.show_morning_setup()

    def _show_summary_screen(self) -> None:
        logical_date = get_logical_date()
        stats = self.db.get_session_stats(logical_date)
        thoughts = self.db.get_thoughts_for_date(logical_date)
        course_stats = self.db.get_course_study_stats(logical_date)
        app_stats = self.db.get_app_usage_stats(logical_date)

        if self.summary_win is None:
            self.summary_win = SummaryScreenWindow()
            self.summary_win.new_session_requested.connect(self.show_morning_setup)

        self.summary_win.load_summary(
            stats=stats,
            thoughts=thoughts,
            course_stats=course_stats,
            app_stats=app_stats,
        )
        self.summary_win.show()
        self.summary_win.raise_()
        self.summary_win.activateWindow()


def _install_crash_safety_handlers() -> None:
    """Yakalanmayan istisnalarda ve sinyal çıkışlarında sistemin kilitli kalmamasını sağlar."""
    orig_excepthook = sys.excepthook

    def _safe_excepthook(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
        try:
            snap = StateSnapshotManager()
            if snap.read_state().get("lock_active", False):
                rollback_all_system_locks(reason="unhandled_exception")
        except Exception:
            pass
        orig_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _safe_excepthook

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda s, f: (rollback_all_system_locks(reason="signal_exit"), sys.exit(0)))
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ders Kilidi Masaüstü Uygulaması")
    parser.add_argument("--resume-lock", action="store_true", help="Aktif kilit oturumunu kaldığı yerden sürdür")
    parser.add_argument("--recover", action="store_true", help="Kurtarma modunu çalıştır")
    parser.add_argument("--auto-boot-clean", action="store_true", help="Açılışta otomatik kurtarma temizliği yap")
    args = parser.parse_args(argv)

    if args.recover or args.auto_boot_clean:
        rec_args = ["--auto-boot-clean"] if args.auto_boot_clean else []
        return recover.main(rec_args)

    _install_crash_safety_handlers()

    app = QApplication(sys.argv)
    app.setApplicationName("Ders Kilidi")
    controller = StudyLockController(app=app, resume_mode=args.resume_lock)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
