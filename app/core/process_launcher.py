"""İzinli uygulamaları ve ders klasörü dosyalarını yükseltilmemiş (non-elevated) yetkiyle başlatma modülü.

Mimari:
1. Windows kabuk penceresinin (`GetShellWindow` -> `explorer.exe`) PID'si bulunur.
2. `explorer.exe` sürecinin erişim belirteci (`OpenProcessToken`) açılır ve `DuplicateTokenEx`
   ile birincil belirteç (`TokenPrimary`) olarak kopyalanır.
3. `advapi32.CreateProcessWithTokenW` API'si kullanılarak hedef uygulama doğrudan
   `explorer.exe`'nin yükseltilmemiş (Medium Integrity) güvenlik bağlamında başlatılır.
4. Eğer hedef bir belge/dosya ise (örn. PDF, DOCX) veya `CreateProcessWithTokenW`
   uygulanamazsa, `explorer.exe` üzerinden başlatma veya standart başlatma yedek olarak kullanılır.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
from pathlib import Path
from typing import Any

import psutil
import win32api
import win32con
import win32process
import win32security

advapi32 = ctypes.windll.advapi32
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

LOGON_WITH_PROFILE = 0x00000001
CREATE_NEW_CONSOLE = 0x00000010
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


CreateProcessWithTokenW = ctypes.WinDLL("advapi32", use_last_error=True).CreateProcessWithTokenW
CreateProcessWithTokenW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFOW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
CreateProcessWithTokenW.restype = wintypes.BOOL


def is_pid_elevated(pid: int | None = None) -> bool | None:
    """Belirtilen PID'ye sahip sürecin yükseltilmiş (Admin/Elevated) olup olmadığını döndürür.

    Dönüş:
    - True: Süreç yükseltilmiş (Elevated / High Integrity)
    - False: Süreç yükseltilmemiş (Non-Elevated / Medium Integrity)
    - None: Erişim reddedildi veya süreç bulunamadı
    """
    target_pid = pid if pid is not None else os.getpid()
    h_proc = None
    h_token = None
    try:
        h_proc = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, target_pid)
        h_token = win32security.OpenProcessToken(h_proc, win32con.TOKEN_QUERY)
        elevated = win32security.GetTokenInformation(h_token, win32security.TokenElevation)
        return bool(elevated)
    except Exception:
        return None
    finally:
        if h_token:
            try:
                win32api.CloseHandle(h_token)
            except Exception:
                pass
        if h_proc:
            try:
                win32api.CloseHandle(h_proc)
            except Exception:
                pass


def _enable_token_privileges() -> None:
    """CreateProcessWithTokenW için gerekli ayrıcalıkları mevcut süreçte etkinleştirir."""
    try:
        h_token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
        )
        for priv_name in (
            win32security.SE_IMPERSONATE_NAME,
            win32security.SE_INCREASE_QUOTA_NAME,
        ):
            try:
                luid = win32security.LookupPrivilegeValue(None, priv_name)
                win32security.AdjustTokenPrivileges(
                    h_token,
                    False,
                    [(luid, win32con.SE_PRIVILEGE_ENABLED)],
                )
            except Exception:
                pass
        win32api.CloseHandle(h_token)
    except Exception:
        pass


def _find_explorer_pid() -> int | None:
    """Çalışan Windows kabuğunun (explorer.exe) PID'sini döndürür."""
    shell_hwnd = user32.GetShellWindow()
    if shell_hwnd:
        _, pid = win32process.GetWindowThreadProcessId(shell_hwnd)
        if pid > 0:
            return int(pid)

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() == "explorer.exe":
                return int(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def launch_non_elevated(
    executable_or_file: str,
    args: list[str] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Uygulamayı veya dosyayı yükseltilmemiş (Explorer token'ı ile) başlatır.

    Dönüş sözlüğü:
    {
        "ok": bool,
        "pid": int | None,
        "method": "CreateProcessWithTokenW" | "subprocess_non_elevated" | "explorer_delegate" | "fallback",
        "elevated": bool | None,
        "error": str | None,
    }
    """
    target = executable_or_file.strip()
    if not target:
        return {"ok": False, "pid": None, "method": "none", "elevated": None, "error": "Boş dosya yolu"}

    arg_list = args or []
    ext = os.path.splitext(target)[1].lower()

    # Eğer hedef doğrudan bir .exe değilse (örn. Ders Klasöründeki bir PDF/belge ise),
    # explorer.exe üzerinden açarak hem varsayılan uygulamayla hem de non-elevated açılmasını sağla
    if ext not in (".exe", ".bat", ".cmd", ".com"):
        return open_file_in_default_app(target)

    cmd_parts = [f'"{target}"'] + [f'"{a}"' if " " in a else a for a in arg_list]
    cmd_line_str = " ".join(cmd_parts)
    work_dir = cwd or (os.path.dirname(target) if os.path.dirname(target) else None)

    # Yöntem 1: Explorer Token + CreateProcessWithTokenW
    _enable_token_privileges()
    explorer_pid = _find_explorer_pid()
    if explorer_pid:
        h_proc = None
        h_shell_token = None
        h_primary_token = None
        try:
            h_proc = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, explorer_pid)
            h_shell_token = win32security.OpenProcessToken(
                h_proc,
                win32con.TOKEN_DUPLICATE | win32con.TOKEN_ASSIGN_PRIMARY | win32con.TOKEN_QUERY,
            )
            h_primary_token = win32security.DuplicateTokenEx(
                h_shell_token,
                win32security.SecurityImpersonation,
                win32con. TOKEN_ASSIGN_PRIMARY
                | win32con.TOKEN_DUPLICATE
                | win32con.TOKEN_QUERY
                | win32con.TOKEN_ADJUST_DEFAULT
                | win32con.TOKEN_ADJUST_SESSIONID,
                win32security.TokenPrimary,
                None,
            )

            si = STARTUPINFOW()
            si.cb = ctypes.sizeof(STARTUPINFOW)
            pi = PROCESS_INFORMATION()
            cmd_buf = ctypes.create_unicode_buffer(cmd_line_str)

            ok = CreateProcessWithTokenW(
                int(h_primary_token),
                LOGON_WITH_PROFILE,
                target if os.path.isabs(target) else None,
                cmd_buf,
                0,
                None,
                work_dir,
                ctypes.byref(si),
                ctypes.byref(pi),
            )
            if ok:
                launched_pid = int(pi.dwProcessId)
                if pi.hThread:
                    kernel32.CloseHandle(pi.hThread)
                if pi.hProcess:
                    kernel32.CloseHandle(pi.hProcess)
                elev = is_pid_elevated(launched_pid)
                return {
                    "ok": True,
                    "pid": launched_pid,
                    "method": "CreateProcessWithTokenW",
                    "elevated": elev,
                    "error": None,
                }
            else:
                token_err = f"CreateProcessWithTokenW WinError={ctypes.get_last_error()}"
        except Exception as exc:
            token_err = str(exc)
        finally:
            for handle in (h_primary_token, h_shell_token, h_proc):
                if handle:
                    try:
                        win32api.CloseHandle(handle)
                    except Exception:
                        pass
    else:
        token_err = "explorer.exe PID bulunamadı"

    # Yöntem 2: Eğer mevcut süreç zaten yükseltilmemişse (non-elevated), doğrudan subprocess.Popen
    # de yükseltilmemiş süreç üretir.
    self_elevated = is_pid_elevated(os.getpid())
    if self_elevated is False:
        try:
            proc = subprocess.Popen([target] + arg_list, cwd=work_dir)
            elev = is_pid_elevated(proc.pid)
            return {
                "ok": True,
                "pid": proc.pid,
                "method": "subprocess_non_elevated",
                "elevated": elev,
                "error": None,
            }
        except Exception as exc:
            return {"ok": False, "pid": None, "method": "subprocess_non_elevated", "elevated": None, "error": str(exc)}

    # Yöntem 3: Mevcut süreç Admin ise ve CreateProcessWithTokenW başarısız olduysa,
    # explorer.exe'ye delege ederek (kabuk üzerinden non-elevated) başlat
    try:
        proc = subprocess.Popen(["explorer.exe", target] + arg_list, cwd=work_dir)
        return {
            "ok": True,
            "pid": proc.pid,
            "method": "explorer_delegate",
            "elevated": False,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "pid": None,
            "method": "failed",
            "elevated": None,
            "error": f"Token hatası: {token_err}; Explorer yedek hatası: {exc}",
        }


def open_file_in_default_app(file_path: str) -> dict[str, Any]:
    """Ders Klasöründeki bir dosyayı varsayılan uygulamasıyla (yükseltilmemiş) açar."""
    p = Path(file_path)
    if not p.exists():
        return {"ok": False, "pid": None, "method": "none", "elevated": None, "error": f"Dosya bulunamadı: {file_path}"}

    # Explorer token ile explorer.exe "<dosya>" çalıştırmak veya os.startfile kullanmak
    try:
        if is_pid_elevated(os.getpid()) is False:
            os.startfile(str(p))
            return {"ok": True, "pid": None, "method": "os.startfile", "elevated": False, "error": None}

        # Süreç Admin ise explorer.exe üzerinden açarak non-elevated delege et
        res = launch_non_elevated(r"C:\Windows\explorer.exe", [str(p)])
        if res["ok"]:
            return res
        os.startfile(str(p))
        return {"ok": True, "pid": None, "method": "os.startfile_fallback", "elevated": None, "error": None}
    except Exception as exc:
        return {"ok": False, "pid": None, "method": "failed", "elevated": None, "error": str(exc)}
