"""Sistem kilitlerini uygulama, Zamanlanmış Görev (schtasks) yönetimi ve merkezi geri alma (rollback) modülü."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import winreg
from pathlib import Path
from typing import Any

from app import config
from app.core.edge_policy import apply_edge_policies, clear_edge_policies
from app.core.state_snapshot import StateSnapshotManager
from app.core.taskbar_lock import hide_taskbar, show_taskbar

CREATE_NO_WINDOW = 0x08000000


def is_user_admin() -> bool:
    """Mevcut sürecin Yönetici (Elevated Admin) yetkisiyle çalışıp çalışmadığını döndürür."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_task_manager_disabled(disabled: bool) -> tuple[bool, str]:
    """HKCU altında DisableTaskMgr değerini ayarlar (1) veya siler (etkinleştirir)."""
    try:
        if disabled:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                config.SYSTEM_POLICY_REG_PATH,
                0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
            ) as key:
                winreg.SetValueEx(
                    key,
                    config.DISABLE_TASKMGR_VALUE_NAME,
                    0,
                    winreg.REG_DWORD,
                    1,
                )
            return True, "DisableTaskMgr=1 ayarlandı."
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    config.SYSTEM_POLICY_REG_PATH,
                    0,
                    winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
                ) as key:
                    winreg.DeleteValue(key, config.DISABLE_TASKMGR_VALUE_NAME)
            except FileNotFoundError:
                pass
            return True, "DisableTaskMgr kaldırıldı."
    except PermissionError as exc:
        return False, f"DisableTaskMgr yetki hatası (Admin gerekli): {exc}"
    except OSError as exc:
        return False, f"DisableTaskMgr kayıt defteri hatası: {exc}"


def is_task_manager_disabled() -> bool:
    """HKCU altında DisableTaskMgr == 1 olup olmadığını döndürür."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            config.SYSTEM_POLICY_REG_PATH,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            val, _ = winreg.QueryValueEx(key, config.DISABLE_TASKMGR_VALUE_NAME)
            return int(val) == 1
    except OSError:
        return False


def build_recovery_command() -> str:
    """Zamanlanmış görev için recover.py / recover.exe çalıştırma komutunu oluşturur."""
    if getattr(sys, "frozen", False):
        recover_exe = config.BASE_DIR / "recover.exe"
        if recover_exe.exists():
            return f'"{recover_exe}" --auto-boot-clean'
        return f'"{sys.executable}" --recover --auto-boot-clean'

    recover_script = config.BASE_DIR / "recover.py"
    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    runner = pythonw_exe if pythonw_exe.exists() else python_exe
    return f'"{runner}" "{recover_script}" --auto-boot-clean'


def register_boot_recovery_task(
    task_name: str = config.BOOT_RECOVERY_TASK_NAME,
) -> tuple[bool, str]:
    """Oturum açılışında (/SC ONLOGON) en yüksek yetkiyle (/RL HIGHEST) çalışan kurtarma görevi oluşturur."""
    tr_cmd = build_recovery_command()
    cmd = [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        tr_cmd,
        "/SC",
        "ONLOGON",
        "/RL",
        "HIGHEST",
        "/F",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0:
            return True, (proc.stdout or "Zamanlanmış görev oluşturuldu.").strip()
        err = (proc.stderr or proc.stdout or f"Return code {proc.returncode}").strip()
        return False, err
    except Exception as exc:
        return False, str(exc)


def unregister_boot_recovery_task(
    task_name: str = config.BOOT_RECOVERY_TASK_NAME,
) -> tuple[bool, str]:
    """Açılış kurtarma zamanlanmış görevini (schtasks) siler."""
    cmd = [
        "schtasks",
        "/Delete",
        "/TN",
        task_name,
        "/F",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0:
            return True, "Zamanlanmış görev silindi."
        err = (proc.stderr or proc.stdout or "").strip()
        # Görev zaten yoksa başarılı kabul edilir
        if "cannot find" in err.lower() or "bulunam" in err.lower() or "sistem belirtilen" in err.lower():
            return True, "Zamanlanmış görev zaten mevcut değil."
        return False, err
    except Exception as exc:
        return False, str(exc)


def is_boot_recovery_task_registered(
    task_name: str = config.BOOT_RECOVERY_TASK_NAME,
) -> bool:
    """Açılış kurtarma zamanlanmış görevinin sistemde kayıtlı olup olmadığını sorgular."""
    cmd = ["schtasks", "/Query", "/TN", task_name]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode == 0
    except Exception:
        return False


def apply_all_system_locks(
    allowed_urls: list[str] | None = None,
    logical_date: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Ders modu başlarken tüm sistem kısıtlarını ve çökme güvenliği kaydını devreye alır."""
    snapshot_mgr = StateSnapshotManager()
    state = snapshot_mgr.activate_lock(
        logical_date=logical_date,
        timeout_seconds=timeout_seconds,
    )

    schtasks_ok, schtasks_msg = register_boot_recovery_task()
    taskbar_ok = hide_taskbar()
    taskmgr_ok, taskmgr_msg = set_task_manager_disabled(True)
    edge_res = apply_edge_policies(allowed_urls)

    return {
        "state": state,
        "schtasks_ok": schtasks_ok,
        "schtasks_msg": schtasks_msg,
        "taskbar_hidden": taskbar_ok,
        "taskmgr_disabled": taskmgr_ok,
        "taskmgr_msg": taskmgr_msg,
        "edge_policy": edge_res,
    }


def rollback_all_system_locks(
    reason: str = "normal",
    delete_scheduled_task: bool = True,
) -> dict[str, Any]:
    """Görev çubuğu, DisableTaskMgr, Edge politikaları ve zamanlanmış görevi güvenli biçimde temizler."""
    taskbar_ok = show_taskbar()
    taskmgr_ok, taskmgr_msg = set_task_manager_disabled(False)
    edge_res = clear_edge_policies()

    schtasks_ok = True
    schtasks_msg = "Atlandı"
    if delete_scheduled_task:
        schtasks_ok, schtasks_msg = unregister_boot_recovery_task()

    snapshot_mgr = StateSnapshotManager()
    snapshot_mgr.deactivate_lock(reason=reason)

    return {
        "reason": reason,
        "taskbar_shown": taskbar_ok,
        "taskmgr_restored": taskmgr_ok,
        "taskmgr_msg": taskmgr_msg,
        "edge_cleared": edge_res,
        "schtasks_deleted": schtasks_ok,
        "schtasks_msg": schtasks_msg,
    }
