"""Bağımsız Acil Kurtarma Aracı (recover.py).

Bu betik PySide6 veya üçüncü parti kütüphanelere ihtiyaç duymadan yalnızca Python
standart kütüphanesi (ctypes, winreg, subprocess, json) ile çalışabilecek şekilde
tasarlanmıştır.

Yaptığı işlemler:
1. Çalışan Ders Kilidi / Watchdog süreçlerini güvenli biçimde durdurur.
2. Windows Görev Çubuğunu (Shell_TrayWnd ve Shell_SecondaryTrayWnd) tekrar görünür yapar (SW_SHOW).
3. Görev Yöneticisi engelini (HKCU DisableTaskMgr) kaldırır.
4. Hem HKCU hem HKLM altındaki Microsoft Edge kısıtlama politikalarını (URLBlocklist, URLAllowlist,
   InPrivateModeAvailability, BrowserGuestModeEnabled) temizler.
5. Oturum açılışındaki Zamanlanmış Görevi (DersKilidiBootRecovery) siler.
6. data/state_snapshot.json içindeki lock_active bayrağını False olarak günceller.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg
from typing import Any

SW_SHOW = 5
CREATE_NO_WINDOW = 0x08000000

TASK_NAME = "DersKilidiBootRecovery"
EDGE_POLICY_PATH = r"Software\Policies\Microsoft\Edge"
EDGE_BLOCKLIST_PATH = r"Software\Policies\Microsoft\Edge\URLBlocklist"
EDGE_ALLOWLIST_PATH = r"Software\Policies\Microsoft\Edge\URLAllowlist"
SYSTEM_POLICY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def restore_taskbar() -> bool:
    """Windows görev çubuğunu (birincil ve ikincil ekranlar) görünür yapar."""
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowExW.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL

        primary = user32.FindWindowW("Shell_TrayWnd", None)
        if primary:
            user32.ShowWindow(wintypes.HWND(primary), SW_SHOW)

        secondary = 0
        while True:
            secondary = user32.FindWindowExW(0, secondary, "Shell_SecondaryTrayWnd", None)
            if not secondary:
                break
            user32.ShowWindow(wintypes.HWND(secondary), SW_SHOW)
        return True
    except Exception:
        return False


def restore_task_manager() -> bool:
    """HKCU altındaki DisableTaskMgr değerini siler."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            SYSTEM_POLICY_PATH,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        ) as key:
            try:
                winreg.DeleteValue(key, "DisableTaskMgr")
            except FileNotFoundError:
                pass
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _delete_reg_subkey_values(root_hive: int, subkey_path: str) -> None:
    try:
        with winreg.OpenKey(
            root_hive,
            subkey_path,
            0,
            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
        ) as key:
            while True:
                try:
                    val_name, _, _ = winreg.EnumValue(key, 0)
                    winreg.DeleteValue(key, val_name)
                except OSError:
                    break
    except OSError:
        pass

    try:
        winreg.DeleteKeyEx(root_hive, subkey_path, winreg.KEY_WOW64_64KEY, 0)
    except OSError:
        try:
            winreg.DeleteKey(root_hive, subkey_path)
        except OSError:
            pass


def restore_edge_policies() -> dict[str, bool]:
    """Hem HKCU hem HKLM altındaki Edge politikalarını temizler."""
    status = {"hkcu": False, "hklm": False}
    for name, hive in (("hkcu", winreg.HKEY_CURRENT_USER), ("hklm", winreg.HKEY_LOCAL_MACHINE)):
        try:
            _delete_reg_subkey_values(hive, EDGE_BLOCKLIST_PATH)
            _delete_reg_subkey_values(hive, EDGE_ALLOWLIST_PATH)
            try:
                with winreg.OpenKey(
                    hive,
                    EDGE_POLICY_PATH,
                    0,
                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
                ) as edge_key:
                    for val_name in ("InPrivateModeAvailability", "BrowserGuestModeEnabled"):
                        try:
                            winreg.DeleteValue(edge_key, val_name)
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass
            status[name] = True
        except OSError:
            status[name] = False
    return status


def remove_scheduled_task(task_name: str = TASK_NAME) -> bool:
    """DersKilidiBootRecovery zamanlanmış görevini siler."""
    try:
        proc = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0:
            return True
        out = (proc.stderr or proc.stdout or "").lower()
        return ("cannot find" in out) or ("bulunam" in out) or ("sistem belirtilen" in out)
    except Exception:
        return False


def stop_lock_processes(snapshot_path: Path) -> list[int]:
    """Durum dosyasındaki main_pid ve watchdog_pid süreçlerini sonlandırır."""
    killed_pids: list[int] = []
    my_pid = os.getpid()
    if not snapshot_path.exists():
        return killed_pids

    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return killed_pids

    for key in ("watchdog_pid", "main_pid"):
        pid = int(data.get(key) or 0)
        if pid > 0 and pid != my_pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    timeout=5,
                    creationflags=CREATE_NO_WINDOW,
                )
                killed_pids.append(pid)
            except Exception:
                pass
    return killed_pids


def clear_state_snapshot(snapshot_path: Path, reason: str = "recover_script") -> None:
    """state_snapshot.json içindeki lock_active durumunu False yapar."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {}
    if snapshot_path.exists():
        try:
            state = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    state["lock_active"] = False
    state["deactivated_at"] = time.time()
    state["deactivated_at_iso"] = datetime.now().isoformat(timespec="seconds")
    state["deactivated_reason"] = reason

    tmp = snapshot_path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(snapshot_path))


def run_full_recovery(
    reason: str = "manual_recover",
    kill_processes: bool = True,
    snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Tüm kurtarma adımlarını sırasıyla çalıştırır ve sonuç özetini döndürür."""
    base_dir = _get_base_dir()
    snap_file = snapshot_path or (base_dir / "data" / "state_snapshot.json")

    # Önce durum dosyasını pasife çek ki Watchdog ana süreci tekrar başlatmasın
    clear_state_snapshot(snap_file, reason=reason)

    killed: list[int] = []
    if kill_processes:
        killed = stop_lock_processes(snap_file)

    taskbar_ok = restore_taskbar()
    taskmgr_ok = restore_task_manager()
    edge_status = restore_edge_policies()
    schtasks_ok = remove_scheduled_task()

    return {
        "reason": reason,
        "killed_pids": killed,
        "taskbar_restored": taskbar_ok,
        "taskmgr_restored": taskmgr_ok,
        "edge_restored": edge_status,
        "schtasks_removed": schtasks_ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ders Kilidi Bağımsız Acil Kurtarma Aracı")
    parser.add_argument(
        "--auto-boot-clean",
        action="store_true",
        help="Oturum açılışında (yeniden başlatma sonrası) otomatik temizlik modu",
    )
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="Çalışan süreçleri sonlandırmadan sadece sistem ayarlarını geri al",
    )
    args = parser.parse_args(argv)

    reason = "auto_boot_clean" if args.auto_boot_clean else "manual_recover_cli"
    summary = run_full_recovery(reason=reason, kill_processes=not args.no_kill)

    if not args.auto_boot_clean:
        print("=== Ders Kilidi Kurtarma Tamamlandı ===")
        print(f"Sebep                 : {summary['reason']}")
        print(f"Görev Çubuğu Gösterildi: {summary['taskbar_restored']}")
        print(f"Görev Yöneticisi Açıldı: {summary['taskmgr_restored']}")
        print(f"Edge Politikaları     : HKCU={summary['edge_restored']['hkcu']}, HKLM={summary['edge_restored']['hklm']}")
        print(f"Zamanlanmış Görev Sil : {summary['schtasks_removed']}")
        if summary["killed_pids"]:
            print(f"Sonlandırılan PID'ler : {summary['killed_pids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
