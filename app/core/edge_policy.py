"""Microsoft Edge resmi Kayıt Defteri (Registry) politikaları yöneticisi (HKCU + HKLM)."""

from __future__ import annotations

import winreg
from typing import Any, Iterable

from app.config import (
    DEFAULT_ALLOWED_URLS,
    EDGE_ALLOWLIST_REG_PATH,
    EDGE_BLOCKLIST_REG_PATH,
    EDGE_POLICY_REG_PATH,
    EDGE_REQUIRED_LOCAL_SCHEMES,
)

HIVES: tuple[tuple[str, int], ...] = (
    ("HKCU", winreg.HKEY_CURRENT_USER),
    ("HKLM", winreg.HKEY_LOCAL_MACHINE),
)


def _delete_key_tree_values(root_hive: int, subkey_path: str) -> None:
    """Belirtilen alt anahtar içindeki tüm değerleri siler ve alt anahtarı kaldırır."""
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
    except FileNotFoundError:
        return
    except PermissionError:
        raise
    except OSError:
        pass

    try:
        winreg.DeleteKeyEx(root_hive, subkey_path, winreg.KEY_WOW64_64KEY, 0)
    except OSError:
        try:
            winreg.DeleteKey(root_hive, subkey_path)
        except OSError:
            pass


def apply_edge_policies(allowed_urls: Iterable[str] | None = None) -> dict[str, Any]:
    """Edge URLBlocklist, URLAllowlist, InPrivate ve Guest modu kısıtlarını hem HKCU hem HKLM'ye yazar.

    Yerel PDF ve ders klasörü dosyalarının Edge ile sorunsuz açılabilmesi için
    `file://*`, `edge://*` ve `chrome-extension://*` şemaları otomatik olarak
    URLAllowlist listesine dahil edilir.
    """
    raw_urls = list(allowed_urls) if allowed_urls is not None else list(DEFAULT_ALLOWED_URLS)
    urls: list[str] = []
    seen: set[str] = set()
    for item in [*EDGE_REQUIRED_LOCAL_SCHEMES, *raw_urls]:
        cleaned = item.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            urls.append(cleaned)

    result: dict[str, Any] = {"hkcu": False, "hklm": False, "errors": []}

    for hive_name, hive_root in HIVES:
        try:
            # 1. Ana Edge politika anahtarı: InPrivate ve Konuk Modu kapatma
            with winreg.CreateKeyEx(
                hive_root,
                EDGE_POLICY_REG_PATH,
                0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
            ) as edge_key:
                winreg.SetValueEx(edge_key, "InPrivateModeAvailability", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(edge_key, "BrowserGuestModeEnabled", 0, winreg.REG_DWORD, 0)

            # 2. URLBlocklist: "*"
            _delete_key_tree_values(hive_root, EDGE_BLOCKLIST_REG_PATH)
            with winreg.CreateKeyEx(
                hive_root,
                EDGE_BLOCKLIST_REG_PATH,
                0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
            ) as block_key:
                winreg.SetValueEx(block_key, "1", 0, winreg.REG_SZ, "*")

            # 3. URLAllowlist: kullanıcının izinli adresleri
            _delete_key_tree_values(hive_root, EDGE_ALLOWLIST_REG_PATH)
            with winreg.CreateKeyEx(
                hive_root,
                EDGE_ALLOWLIST_REG_PATH,
                0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
            ) as allow_key:
                for idx, pattern in enumerate(urls, start=1):
                    winreg.SetValueEx(allow_key, str(idx), 0, winreg.REG_SZ, pattern)

            result[hive_name.lower()] = True
        except PermissionError as exc:
            result["errors"].append(f"{hive_name} yetki hatası (Admin gerekli): {exc}")
        except OSError as exc:
            result["errors"].append(f"{hive_name} kayıt defteri hatası: {exc}")

    return result


def clear_edge_policies() -> dict[str, Any]:
    """Hem HKCU hem HKLM altındaki Edge ders modu politikalarını temizler."""
    result: dict[str, Any] = {"hkcu": False, "hklm": False, "errors": []}

    for hive_name, hive_root in HIVES:
        try:
            _delete_key_tree_values(hive_root, EDGE_BLOCKLIST_REG_PATH)
            _delete_key_tree_values(hive_root, EDGE_ALLOWLIST_REG_PATH)

            try:
                with winreg.OpenKey(
                    hive_root,
                    EDGE_POLICY_REG_PATH,
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

            result[hive_name.lower()] = True
        except PermissionError as exc:
            result["errors"].append(f"{hive_name} temizleme yetki hatası: {exc}")
        except OSError as exc:
            result["errors"].append(f"{hive_name} temizleme hatası: {exc}")

    return result


def read_edge_policy_state() -> dict[str, Any]:
    """Test ve doğrulama amacıyla HKCU ve HKLM altındaki mevcut Edge politikalarını okur."""
    snapshot: dict[str, Any] = {}
    for hive_name, hive_root in HIVES:
        hive_data: dict[str, Any] = {
            "inprivate_disabled": False,
            "guest_disabled": False,
            "blocklist": [],
            "allowlist": [],
        }
        try:
            with winreg.OpenKey(
                hive_root,
                EDGE_POLICY_REG_PATH,
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as edge_key:
                try:
                    inpriv, _ = winreg.QueryValueEx(edge_key, "InPrivateModeAvailability")
                    hive_data["inprivate_disabled"] = (int(inpriv) == 1)
                except FileNotFoundError:
                    pass
                try:
                    guest, _ = winreg.QueryValueEx(edge_key, "BrowserGuestModeEnabled")
                    hive_data["guest_disabled"] = (int(guest) == 0)
                except FileNotFoundError:
                    pass

            try:
                with winreg.OpenKey(
                    hive_root,
                    EDGE_BLOCKLIST_REG_PATH,
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                ) as bkey:
                    idx = 0
                    while True:
                        try:
                            _, val, _ = winreg.EnumValue(bkey, idx)
                            hive_data["blocklist"].append(str(val))
                            idx += 1
                        except OSError:
                            break
            except FileNotFoundError:
                pass

            try:
                with winreg.OpenKey(
                    hive_root,
                    EDGE_ALLOWLIST_REG_PATH,
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                ) as akey:
                    idx = 0
                    while True:
                        try:
                            _, val, _ = winreg.EnumValue(akey, idx)
                            hive_data["allowlist"].append(str(val))
                            idx += 1
                        except OSError:
                            break
            except FileNotFoundError:
                pass
        except OSError:
            pass
        snapshot[hive_name.lower()] = hive_data
    return snapshot
