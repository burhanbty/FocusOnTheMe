"""1 saniyelik pencere ve süreç denetleyicisi (ProcessEnforcer).

Görevleri:
1. Windows Dosya Gezgini klasör pencerelerini (`CabinetWClass`, `ExploreWClass`) `WM_CLOSE` ile kapatmak
   (`explorer.exe` sürecini asla sonlandırmadan).
2. Görünür üst seviye uygulama pencerelerini taramak; beyaz listede olmayan pencereler için:
   - 5 saniye geri sayımlı uyarı üretmek,
   - 5. saniye sonunda `WM_CLOSE` göndermek,
   - 3 saniye sonra hala kapanmadıysa (ve `SYSTEM_PROTECTED_PROCESSES` içinde değilse) zorla sonlandırmak (`kill`).
3. `TEST_MODE=True` iken `cmd.exe`, `powershell.exe`, `pwsh.exe`, `taskmgr.exe` vb. araçları muaf tutmak.
4. İzinli uygulama pencerelerini üst çubukla (`y < 60`) çakışmayacak şekilde çalışma alanına (`x=0, y=60, w=W, h=H-60`) oturtmak.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Callable

import psutil
import win32con
import win32gui
import win32process

from app import config
from app.core.taskbar_lock import fit_window_to_work_area, get_work_area_rect

GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_EX_TOOLWINDOW = 0x00000080
WS_CHILD = 0x40000000

EXPLORER_FOLDER_CLASSES: frozenset[str] = frozenset({"CabinetWClass", "ExploreWClass"})
IGNORED_WINDOW_CLASSES: frozenset[str] = frozenset(
    {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "NotifyIconOverflowWindow",
        "Windows.UI.Core.CoreWindow",
        "IME",
        "MSCTFIME UI",
        "tooltips_class32",
        "SysShadow",
    }
)


@dataclass
class PendingViolation:
    """Kapatılma sürecindeki izinsiz uygulama penceresi kaydı."""

    key: str
    pid: int
    hwnd: int
    exe_name: str
    exe_path: str
    window_title: str
    first_seen_at: float
    wm_close_sent: bool = False
    wm_close_sent_at: float = 0.0
    counted_in_stats: bool = False


def is_process_protected(
    exe_name: str,
    pid: int | None = None,
    own_pids: set[int] | None = None,
) -> bool:
    """Sürecin sistem korumalı listede veya kendi süreçlerimiz arasında olup olmadığını döndürür."""
    if pid is not None and own_pids and pid in own_pids:
        return True
    if pid is not None and pid in (0, 4, os.getpid()):
        return True
    norm_name = (exe_name or "").strip().lower()
    if not norm_name:
        return True
    return norm_name in config.SYSTEM_PROTECTED_PROCESSES


def is_process_allowed(
    exe_name: str,
    exe_path: str,
    allowed_exe_paths: set[str],
    allowed_exe_names: set[str],
    test_mode: bool | None = None,
    pid: int | None = None,
    own_pids: set[int] | None = None,
) -> bool:
    """Bir sürecin çalışmasına izin verilip verilmediğini değerlendirir."""
    if is_process_protected(exe_name, pid=pid, own_pids=own_pids):
        return True

    norm_name = (exe_name or "").strip().lower()
    norm_path = os.path.normcase(os.path.normpath(exe_path.strip())) if exe_path else ""

    active_test_mode = config.TEST_MODE if test_mode is None else test_mode
    if active_test_mode and norm_name in config.TEST_MODE_EXEMPT_PROCESSES:
        return True

    if norm_path and norm_path in allowed_exe_paths:
        return True
    if norm_name and norm_name in allowed_exe_names:
        return True

    return False


def _resolve_uwp_child_pid(frame_hwnd: int, frame_pid: int) -> int:
    """ApplicationFrameHost.exe penceresinin içindeki gerçek UWP uygulama PID'sini bulur."""
    resolved_pid = frame_pid

    def _child_cb(child_hwnd: int, _: Any) -> bool:
        nonlocal resolved_pid
        try:
            _, cpid = win32process.GetWindowThreadProcessId(child_hwnd)
            if cpid and cpid != frame_pid:
                resolved_pid = int(cpid)
                return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(frame_hwnd, _child_cb, None)
    except Exception:
        pass
    return resolved_pid


def _get_process_identity(pid: int) -> tuple[str, str]:
    """PID için (exe_name_lower, exe_full_path) döndürür."""
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        try:
            exe = proc.exe() or ""
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            exe = name
        return name, exe
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return "", ""


class ProcessEnforcer:
    """1 saniyelik döngüde pencereleri denetleyen, uyarı gösteren ve çalışma alanını koruyan motor."""

    def __init__(
        self,
        on_warning_update: Callable[[list[dict[str, Any]]], None] | None = None,
        on_app_closed: Callable[[str], None] | None = None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.on_warning_update = on_warning_update
        self.on_app_closed = on_app_closed
        self._time_fn = time_fn

        self.allowed_exe_paths: set[str] = set()
        self.allowed_exe_names: set[str] = set()
        self.own_pids: set[int] = {os.getpid()}
        self._violations: dict[str, PendingViolation] = {}
        self._positioned_hwnds: set[int] = set()

    def set_allowed_apps(self, apps: list[dict[str, Any]]) -> None:
        paths: set[str] = set()
        names: set[str] = set()
        for app in apps:
            if not app.get("enabled", 1):
                continue
            raw_path = (app.get("exe_path") or "").strip()
            raw_name = (app.get("exe_name") or "").strip().lower()
            if raw_path:
                paths.add(os.path.normcase(os.path.normpath(raw_path)))
                names.add(os.path.basename(raw_path).lower())
            if raw_name:
                names.add(raw_name)
        self.allowed_exe_paths = paths
        self.allowed_exe_names = names

    def register_own_pid(self, pid: int) -> None:
        if pid and pid > 0:
            self.own_pids.add(int(pid))

    def _enumerate_relevant_windows(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        def _enum_cb(hwnd: int, _: Any) -> bool:
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                cls_name = win32gui.GetClassName(hwnd) or ""
                if cls_name in IGNORED_WINDOW_CLASSES:
                    return True

                title = (win32gui.GetWindowText(hwnd) or "").strip()
                ex_style = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
                if (ex_style & WS_EX_TOOLWINDOW) and cls_name not in EXPLORER_FOLDER_CLASSES:
                    return True

                rect = win32gui.GetWindowRect(hwnd)
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                if width < 50 or height < 30:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if not pid or pid in self.own_pids:
                    return True

                if cls_name == "ApplicationFrameWindow":
                    pid = _resolve_uwp_child_pid(hwnd, int(pid))

                exe_name, exe_path = _get_process_identity(int(pid))
                if not exe_name and cls_name not in EXPLORER_FOLDER_CLASSES:
                    return True

                # Başlığı olmayan arka plan kukla pencerelerini atla
                if not title and cls_name not in EXPLORER_FOLDER_CLASSES:
                    return True

                results.append(
                    {
                        "hwnd": int(hwnd),
                        "pid": int(pid),
                        "class_name": cls_name,
                        "title": title,
                        "exe_name": exe_name,
                        "exe_path": exe_path,
                        "rect": rect,
                    }
                )
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass
        return results

    def _ensure_allowed_window_in_work_area(self, win_info: dict[str, Any]) -> None:
        """İzinli uygulama ana penceresi üst çubuk alanına taşmışsa çalışma alanına oturtur."""
        hwnd = win_info["hwnd"]
        cls_name = win_info["class_name"]
        # Standart küçük diyalog pencerelerini (#32770 - Dosya Aç/Kaydet vb.) tam ekran yapma
        if cls_name == "#32770":
            return

        rect = win_info["rect"]
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top

        # Küçük yardımcı diyalogları zorla büyütme
        if width < 400 and height < 300:
            return

        _, target_y, target_w, target_h = get_work_area_rect()
        # Eğer pencere yeni açıldıysa, maximize edildiyse veya üst sınırı (y < target_y) çubukla çakışıyorsa:
        if (
            hwnd not in self._positioned_hwnds
            or top < target_y
            or abs(width - target_w) > 16 and win32gui.IsZoomed(hwnd)
        ):
            fit_window_to_work_area(hwnd)
            self._positioned_hwnds.add(hwnd)

    def tick(self) -> list[dict[str, Any]]:
        """1 saniyelik denetim adımı. Aktif uyarı listesini döndürür."""
        now = self._time_fn()
        windows = self._enumerate_relevant_windows()
        seen_keys: set[str] = set()

        for win in windows:
            hwnd = win["hwnd"]
            pid = win["pid"]
            cls_name = win["class_name"]
            exe_name = win["exe_name"]
            exe_path = win["exe_path"]
            title = win["title"]

            # 1. KARAR 1: Explorer klasör pencereleri WM_CLOSE ile anında kapatılır (explorer.exe öldürülmez)
            if cls_name in EXPLORER_FOLDER_CLASSES:
                try:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                except Exception:
                    pass
                continue

            # 2. İzinli veya korumalı mı kontrol et
            if is_process_allowed(
                exe_name=exe_name,
                exe_path=exe_path,
                allowed_exe_paths=self.allowed_exe_paths,
                allowed_exe_names=self.allowed_exe_names,
                test_mode=config.TEST_MODE,
                pid=pid,
                own_pids=self.own_pids,
            ):
                # Kendi penceremiz veya arka plan sistem penceresi değilse çalışma alanına oturt
                if not is_process_protected(exe_name, pid=pid, own_pids=self.own_pids):
                    self._ensure_allowed_window_in_work_area(win)
                continue

            # 3. TEST_MODE=False iken kaçış araçları (taskmgr, cmd, powershell, regedit) anında kapatılır
            if not config.TEST_MODE and exe_name in config.CRITICAL_ESCAPE_PROCESSES:
                try:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                except Exception:
                    pass
                if not is_process_protected(exe_name, pid=pid, own_pids=self.own_pids):
                    try:
                        psutil.Process(pid).kill()
                    except Exception:
                        pass
                if self.on_app_closed:
                    self.on_app_closed(exe_name or title)
                continue

            # 4. Standart izinsiz uygulama: 5 sn geri sayım -> WM_CLOSE -> 3 sn sonra kill
            vkey = f"{pid}:{exe_name}"
            seen_keys.add(vkey)
            if vkey not in self._violations:
                self._violations[vkey] = PendingViolation(
                    key=vkey,
                    pid=pid,
                    hwnd=hwnd,
                    exe_name=exe_name or "uygulama.exe",
                    exe_path=exe_path,
                    window_title=title or exe_name,
                    first_seen_at=now,
                )
            else:
                self._violations[vkey].hwnd = hwnd
                if title:
                    self._violations[vkey].window_title = title

        # Mevcut ihlalleri değerlendir
        active_warnings: list[dict[str, Any]] = []
        to_remove: list[str] = []

        for vkey, viol in list(self._violations.items()):
            elapsed = now - viol.first_seen_at
            proc_alive = psutil.pid_exists(viol.pid)
            win_alive = bool(viol.hwnd and win32gui.IsWindow(viol.hwnd) and win32gui.IsWindowVisible(viol.hwnd))

            if not proc_alive and not win_alive:
                if viol.wm_close_sent and not viol.counted_in_stats:
                    viol.counted_in_stats = True
                    if self.on_app_closed:
                        self.on_app_closed(viol.exe_name)
                to_remove.append(vkey)
                continue

            # Pencere kapandıysa ve henüz WM_CLOSE gönderilmediyse (kullanıcı kendisi kapattıysa)
            if vkey not in seen_keys and not viol.wm_close_sent:
                to_remove.append(vkey)
                continue

            if elapsed < config.WARNING_COUNTDOWN_SECONDS:
                rem = max(1, int(round(config.WARNING_COUNTDOWN_SECONDS - elapsed)))
                active_warnings.append(
                    {
                        "pid": viol.pid,
                        "exe_name": viol.exe_name,
                        "title": viol.window_title,
                        "remaining_seconds": rem,
                        "stage": "countdown",
                    }
                )
            elif not viol.wm_close_sent:
                # 5 saniye doldu -> WM_CLOSE gönder
                viol.wm_close_sent = True
                viol.wm_close_sent_at = now
                try:
                    if win_alive:
                        win32gui.PostMessage(viol.hwnd, win32con.WM_CLOSE, 0, 0)
                except Exception:
                    pass
                active_warnings.append(
                    {
                        "pid": viol.pid,
                        "exe_name": viol.exe_name,
                        "title": viol.window_title,
                        "remaining_seconds": 0,
                        "stage": "closing",
                    }
                )
            else:
                # WM_CLOSE gönderildi, 3 saniye ek süre kontrolü
                grace_elapsed = now - viol.wm_close_sent_at
                if grace_elapsed >= config.FORCE_KILL_GRACE_SECONDS:
                    if not is_process_protected(viol.exe_name, pid=viol.pid, own_pids=self.own_pids):
                        try:
                            proc = psutil.Process(viol.pid)
                            proc.terminate()
                            try:
                                proc.wait(timeout=0.3)
                            except psutil.TimeoutExpired:
                                proc.kill()
                        except Exception:
                            pass
                    if not viol.counted_in_stats:
                        viol.counted_in_stats = True
                        if self.on_app_closed:
                            self.on_app_closed(viol.exe_name)
                    to_remove.append(vkey)
                else:
                    active_warnings.append(
                        {
                            "pid": viol.pid,
                            "exe_name": viol.exe_name,
                            "title": viol.window_title,
                            "remaining_seconds": 0,
                            "stage": "closing",
                        }
                    )

        for k in to_remove:
            self._violations.pop(k, None)

        if self.on_warning_update is not None:
            self.on_warning_update(active_warnings)

        return active_warnings
