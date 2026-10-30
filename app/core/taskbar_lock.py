"""Windows Görev Çubuğu (Shell_TrayWnd) gizleme/gösterme ve çalışma alanı pencere konumlandırma modülü."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from app.config import TOP_BAR_HEIGHT, WORK_AREA_TOP_OFFSET

user32 = ctypes.windll.user32

# 64-bit HWND güvenliği için açık argtypes ve restype tanımları
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL

user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_RESTORE = 9
SW_SHOW = 5

SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

SM_CXSCREEN = 0
SM_CYSCREEN = 1


def _find_all_tray_windows() -> list[int]:
    """Birincil ve ikincil ekranlardaki görev çubuğu HWND listesini döndürür."""
    hwnds: list[int] = []
    primary = user32.FindWindowW("Shell_TrayWnd", None)
    if primary:
        hwnds.append(int(primary))

    secondary = 0
    while True:
        secondary = user32.FindWindowExW(0, secondary, "Shell_SecondaryTrayWnd", None)
        if not secondary:
            break
        hwnds.append(int(secondary))
    return hwnds


def hide_taskbar() -> bool:
    """Windows görev çubuğunu (ve varsa ikincil görev çubuklarını) gizler."""
    try:
        hwnds = _find_all_tray_windows()
        for hwnd in hwnds:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
        return True
    except Exception:
        return False


def show_taskbar() -> bool:
    """Windows görev çubuğunu (ve varsa ikincil görev çubuklarını) tekrar görünür yapar."""
    try:
        hwnds = _find_all_tray_windows()
        for hwnd in hwnds:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOW)
        return True
    except Exception:
        return False


def is_taskbar_visible() -> bool:
    """Birincil görev çubuğunun görünür olup olmadığını döndürür."""
    primary = user32.FindWindowW("Shell_TrayWnd", None)
    if not primary:
        return False
    return bool(user32.IsWindowVisible(wintypes.HWND(primary)))


def ensure_taskbar_hidden() -> None:
    """Görev çubuğu Windows tarafından tekrar görünür yapıldıysa yeniden gizler."""
    for hwnd in _find_all_tray_windows():
        if user32.IsWindowVisible(wintypes.HWND(hwnd)):
            user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)


def get_work_area_rect(
    screen_width: int | None = None,
    screen_height: int | None = None,
    bar_height: int = TOP_BAR_HEIGHT,
) -> tuple[int, int, int, int]:
    """İzinli uygulama pencerelerinin yerleştirileceği çalışma alanı dikdörtgenini döndürür.

    Kurallar:
    - x = 0
    - y = çubuk yüksekliği + 16 (44 + 16 = 60)
    - genişlik = ekran genişliği
    - yükseklik = ekran yüksekliği - çubuk yüksekliği - 16
    """
    sw = screen_width if screen_width is not None else int(user32.GetSystemMetrics(SM_CXSCREEN))
    sh = screen_height if screen_height is not None else int(user32.GetSystemMetrics(SM_CYSCREEN))
    top_y = bar_height + 16 if bar_height != TOP_BAR_HEIGHT else WORK_AREA_TOP_OFFSET
    return (0, top_y, sw, max(200, sh - top_y))


def fit_window_to_work_area(
    hwnd: int,
    screen_width: int | None = None,
    screen_height: int | None = None,
) -> bool:
    """Verilen üst seviye pencereyi üst çubukla çakışmayacak şekilde çalışma alanına oturtur."""
    h_wnd = wintypes.HWND(hwnd)
    if not hwnd or not user32.IsWindow(h_wnd):
        return False

    if user32.IsIconic(h_wnd) or user32.IsZoomed(h_wnd):
        user32.ShowWindow(h_wnd, SW_RESTORE)

    x, y, w, h = get_work_area_rect(screen_width, screen_height)
    res = user32.SetWindowPos(
        h_wnd,
        0,
        x,
        y,
        w,
        h,
        SWP_NOZORDER | SWP_SHOWWINDOW,
    )
    return bool(res)
