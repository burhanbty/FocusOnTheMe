"""Aktif çalışma (etkileşim / boşta kalma) algılayıcısı ve ön plan uygulama süre takipçisi.

Özellikler:
1. Windows `user32.GetLastInputInfo` API'si ile son fare hareketi, tıklama, sayfa kaydırma (scroll),
   dokunmatik ekran dokunuşu veya klavye tuş basımından bu yana geçen süreyi ölçer.
2. Etkileşim süresi `IDLE_THRESHOLD_SECONDS` (120 sn = 2 dakika) altındaysa kullanıcıyı "Aktif Çalışıyor",
   üzerindeyse "Duraklatıldı (Boşta)" olarak değerlendirir.
3. `win32gui.GetForegroundWindow()` ile o an odakta olan uygulamayı tespit ederek hangi uygulamada
   ne kadar süre geçirildiğini hesaplar.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Any

import psutil
import win32gui
import win32process

from app import config

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

FRIENDLY_APP_NAMES: dict[str, str] = {
    "msedge.exe": "Microsoft Edge",
    "chrome.exe": "Google Chrome",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "sumatrapdf.exe": "SumatraPDF",
    "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Acrobat Reader",
    "foxitpdfreader.exe": "Foxit PDF Reader",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "onenote.exe": "Microsoft OneNote",
    "obsidian.exe": "Obsidian",
    "notion.exe": "Notion",
    "anki.exe": "Anki",
    "code.exe": "Visual Studio Code",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "clion64.exe": "CLion",
    "idea64.exe": "IntelliJ IDEA",
    "notepad.exe": "Not Defteri",
    "calc.exe": "Hesap Makinesi",
    "calculatorapp.exe": "Hesap Makinesi",
    "cmd.exe": "Komut İstemi (CMD)",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell 7",
    "wt.exe": "Windows Terminal",
}

IGNORED_FOREGROUND_EXES: frozenset[str] = frozenset(
    {
        "ders_kilidi.exe",
        "ders_kilidi_watchdog.exe",
        "recover.exe",
        "explorer.exe",
        "dwm.exe",
        "searchhost.exe",
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "lockapp.exe",
    }
)


def get_idle_seconds() -> float:
    """Son kullanıcı etkileşiminden (fare, kaydırma, dokunma, klavye) bu yana geçen saniyeyi döndürür."""
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        tick_now = int(kernel32.GetTickCount()) & 0xFFFFFFFF
        last_tick = int(lii.dwTime) & 0xFFFFFFFF
        elapsed_ms = (tick_now - last_tick) & 0xFFFFFFFF
        return max(0.0, elapsed_ms / 1000.0)
    except Exception:
        return 0.0


def is_user_actively_working(
    threshold_seconds: int = config.IDLE_THRESHOLD_SECONDS,
    idle_seconds_override: float | None = None,
) -> bool:
    """Son etkileşim süresi eşik değerin (varsayılan 120 sn = 2 dk) altındaysa True döndürür."""
    idle_sec = idle_seconds_override if idle_seconds_override is not None else get_idle_seconds()
    return idle_sec < float(threshold_seconds)


def _resolve_uwp_child_pid(frame_hwnd: int, frame_pid: int) -> int:
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


def get_friendly_app_name(exe_name: str, fallback_title: str = "") -> str:
    """Çalıştırılabilir dosya adından okunabilir uygulama adı üretir."""
    norm = (exe_name or "").strip().lower()
    if norm in FRIENDLY_APP_NAMES:
        return FRIENDLY_APP_NAMES[norm]
    if norm.endswith(".exe"):
        base = norm[:-4]
        return base.replace("_", " ").replace("-", " ").title()
    return fallback_title or norm or "Bilinmeyen Uygulama"


def get_foreground_app_info(own_pids: set[int] | None = None) -> dict[str, Any] | None:
    """O an ön planda (odakta) olan pencerenin uygulama bilgilerini döndürür.

    Eğer odak Ders Kilidi'nin kendi kabuk pencerelerindeyse veya masaüstündeyse None döndürür.
    """
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        cls_name = win32gui.GetClassName(hwnd) or ""
        if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return None

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid or pid <= 4:
            return None

        if own_pids and int(pid) in own_pids:
            return None
        if int(pid) == os.getpid():
            return None

        if cls_name == "ApplicationFrameWindow":
            pid = _resolve_uwp_child_pid(int(hwnd), int(pid))

        proc = psutil.Process(int(pid))
        exe_name = (proc.name() or "").strip().lower()
        if not exe_name or exe_name in IGNORED_FOREGROUND_EXES:
            return None

        title = (win32gui.GetWindowText(hwnd) or "").strip()
        display_name = get_friendly_app_name(exe_name, fallback_title=title)
        return {
            "pid": int(pid),
            "hwnd": int(hwnd),
            "exe_name": exe_name,
            "display_name": display_name,
            "window_title": title,
        }
    except Exception:
        return None


def format_duration_hms(seconds: int) -> str:
    """Saniyeyi SS:DD:SN (00:00:00) biçiminde döndürür."""
    sec = max(0, int(seconds))
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    rem = sec % 60
    return f"{hours:02d}:{minutes:02d}:{rem:02d}"


def format_duration_human(seconds: int) -> str:
    """Saniyeyi okunabilir Türkçe süre metnine (örn. '1 sa 15 dk' veya '24 dk 10 sn') çevirir."""
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec} sn"
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    rem_sec = sec % 60
    if hours > 0:
        return f"{hours} sa {minutes} dk"
    if rem_sec > 0 and minutes < 10:
        return f"{minutes} dk {rem_sec} sn"
    return f"{minutes} dk"
