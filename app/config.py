"""Ders Kilidi (FocusMe) — Merkezi yapılandırma ve sistem sabitleri."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# TEST MODU (İlk sürümde varsayılan: True)
# True iken:
#   - Dead-man switch süresi 10 dakikadır (600 sn).
#   - cmd.exe, powershell.exe, pwsh.exe, taskmgr.exe denetleyici tarafından öldürülmez.
#   - Üst çubukta "TEST MODU" etiketi görünür.
# ---------------------------------------------------------------------------
TEST_MODE: bool = True

# ---------------------------------------------------------------------------
# Dizin ve Dosya Yolları
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR: Path = BASE_DIR / "data"
PROOFS_DIR: Path = DATA_DIR / "proofs"
DB_PATH: Path = DATA_DIR / "ders_kilidi.db"
STATE_SNAPSHOT_PATH: Path = DATA_DIR / "state_snapshot.json"
WATCHDOG_LOG_PATH: Path = DATA_DIR / "watchdog.log"

# ---------------------------------------------------------------------------
# Zaman ve Gün Sınırı Sabitleri
# ---------------------------------------------------------------------------
LOGICAL_DAY_BOUNDARY_HOUR: int = 4  # Gün sınırı: 04:00

DEAD_MAN_TIMEOUT_PROD_SECONDS: int = 14 * 3600  # 14 saat (50.400 sn)
DEAD_MAN_TIMEOUT_TEST_SECONDS: int = 10 * 60    # 10 dakika (600 sn)


def get_dead_man_timeout_seconds(test_mode: bool | None = None) -> int:
    """Aktif TEST_MODE durumuna göre dead-man switch süresini (saniye) döndürür."""
    active_test = TEST_MODE if test_mode is None else test_mode
    return DEAD_MAN_TIMEOUT_TEST_SECONDS if active_test else DEAD_MAN_TIMEOUT_PROD_SECONDS


# ---------------------------------------------------------------------------
# Üst Çubuk (Top Bar) ve Çalışma Alanı Düzen Sabitleri
# ---------------------------------------------------------------------------
TOP_BAR_MARGIN: int = 8                         # Kenarlardan 8 px boşluk
TOP_BAR_HEIGHT: int = 44                        # ~44 px yükseklik
TOP_BAR_RADIUS: int = 14                        # 14 px köşe yuvarlaklığı
WORK_AREA_TOP_OFFSET: int = TOP_BAR_HEIGHT + 16  # 44 + 16 = 60 px
POPOVER_FADE_MS: int = 120                      # En fazla 120 ms solma animasyonu

# ---------------------------------------------------------------------------
# Denetim Döngüsü ve Zamanlayıcı Sabitleri
# ---------------------------------------------------------------------------
ENFORCER_INTERVAL_MS: int = 1000        # ~1 sn'lik hafif kontrol döngüsü
WARNING_COUNTDOWN_SECONDS: int = 5      # 5 sn geri sayımlı uyarı
FORCE_KILL_GRACE_SECONDS: int = 3       # WM_CLOSE sonrası 3 sn bekleme

# ---------------------------------------------------------------------------
# Kayıt Defteri (Registry) ve Zamanlanmış Görev Sabitleri
# ---------------------------------------------------------------------------
BOOT_RECOVERY_TASK_NAME: str = "DersKilidiBootRecovery"

EDGE_POLICY_REG_PATH: str = r"Software\Policies\Microsoft\Edge"
EDGE_BLOCKLIST_REG_PATH: str = r"Software\Policies\Microsoft\Edge\URLBlocklist"
EDGE_ALLOWLIST_REG_PATH: str = r"Software\Policies\Microsoft\Edge\URLAllowlist"

SYSTEM_POLICY_REG_PATH: str = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
DISABLE_TASKMGR_VALUE_NAME: str = "DisableTaskMgr"

# ---------------------------------------------------------------------------
# Korumalı Sistem, Antivirüs ve Kendi Süreçlerimiz (Küçük harf normalize)
# Bu listedeki süreçler HİÇBİR KOŞULDA sonlandırılmaz (kill/terminate edilmez).
# ---------------------------------------------------------------------------
SYSTEM_PROTECTED_PROCESSES: frozenset[str] = frozenset(
    {
        # Temel Windows çekirdek ve oturum süreçleri
        "system",
        "idle",
        "registry",
        "memory compression",
        "secure system",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "lsm.exe",
        "svchost.exe",
        "fontdrvhost.exe",
        "dwm.exe",
        "winlogon.exe",
        "sihost.exe",
        "taskhostw.exe",
        "explorer.exe",
        "ctfmon.exe",
        "conhost.exe",
        "dllhost.exe",
        "runtimebroker.exe",
        "searchhost.exe",
        "searchindexer.exe",
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "textinputhost.exe",
        "applicationframehost.exe",
        "systemsettingsbroker.exe",
        "audiodg.exe",
        "spoolsv.exe",
        "wudfhost.exe",
        "wmiprvse.exe",
        "smartscreen.exe",
        "uhssvc.exe",
        "dashost.exe",
        "aggregatorhost.exe",
        "widgetservice.exe",
        "widgets.exe",
        " lockapp.exe",
        "lockapp.exe",
        "logonui.exe",
        "userinit.exe",
        "wlanext.exe",
        "SettingSyncHost.exe".lower(),
        # Windows Defender ve yaygın Antivirüs süreçleri
        "msmpeng.exe",
        "nissrv.exe",
        "securityhealthservice.exe",
        "securityhealthsystray.exe",
        "mpdefendercoreservice.exe",
        "mpcmdrun.exe",
        "avp.exe",
        "avpui.exe",
        "avgnt.exe",
        "avguard.exe",
        "bdagent.exe",
        "vsserv.exe",
        "mcshield.exe",
        "SophosHealth.exe".lower(),
        "eset.exe",
        "ekrn.exe",
        "egui.exe",
        # Kendi uygulama süreçlerimiz
        "ders_kilidi.exe",
        "ders_kilidi_watchdog.exe",
        "recover.exe",
        "python.exe",
        "pythonw.exe",
    }
)

# TEST_MODE = True iken öldürülmeyecek ve kapatılmayacak geliştirici/test araçları
TEST_MODE_EXEMPT_PROCESSES: frozenset[str] = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "taskmgr.exe",
        "wt.exe",
        "openconsole.exe",
        "code.exe",
        "antigravity.exe",
    }
)

# TEST_MODE = False iken 5 sn geri sayım beklemeden anında kapatılacak sistem kaçış araçları
CRITICAL_ESCAPE_PROCESSES: frozenset[str] = frozenset(
    {
        "taskmgr.exe",
        "regedit.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "wt.exe",
        "mmc.exe",
        "msconfig.exe",
    }
)

# Varsayılan önerilen izinli URL listesi (Gemini ve Google giriş altyapısı dahil)
DEFAULT_ALLOWED_URLS: list[str] = [
    "gemini.google.com",
    "accounts.google.com",
    "*.gstatic.com",
    "*.googleapis.com",
    "scholar.google.com",
]


def ensure_data_dirs() -> None:
    """Veri ve kanıt klasörlerinin varlığını garanti eder."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROOFS_DIR.mkdir(parents=True, exist_ok=True)
