"""Acil çıkış kimlik doğrulama, PBKDF2-HMAC-SHA256 özetleme ve artan bekleme (exponential backoff) modülü."""

from __future__ import annotations

import hmac
import hashlib
import json
import secrets
import time
from typing import Callable

from app.core.database import Database

PBKDF2_ITERATIONS: int = 600_000


def compute_backoff_seconds(failed_attempts: int) -> int:
    """Başarısız deneme sayısına göre uygulanacak bekleme süresini (saniye) döndürür."""
    if failed_attempts <= 0:
        return 0
    if failed_attempts <= 2:
        return 5
    if failed_attempts == 3:
        return 30
    if failed_attempts == 4:
        return 120
    return 600


class EmergencyAuthManager:
    """Acil çıkış şifresini yöneten, doğrulayan ve artan bekleme uygulayan sınıf."""

    def __init__(
        self,
        db: Database,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self._time_fn = time_fn

    def has_password(self) -> bool:
        raw = self.db.get_setting("emergency_password_hash", "").strip()
        if not raw:
            return False
        try:
            data = json.loads(raw)
            return bool(data.get("salt") and data.get("hash"))
        except Exception:
            return False

    def set_password(self, plain_password: str) -> None:
        cleaned = plain_password.strip()
        if len(cleaned) < 4:
            raise ValueError("Acil çıkış şifresi en az 4 karakter olmalıdır.")

        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            cleaned.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )
        payload = json.dumps(
            {
                "salt": salt.hex(),
                "hash": digest.hex(),
                "iterations": PBKDF2_ITERATIONS,
            }
        )
        self.db.set_setting("emergency_password_hash", payload)
        self.db.set_setting("emergency_failed_attempts", "0")
        self.db.set_setting("emergency_lockout_until", "0")
        self.db.log_audit("EMERGENCY_PASSWORD_SET", "Acil çıkış şifresi yapılandırıldı/güncellendi.")

    def get_remaining_lockout_seconds(self) -> int:
        try:
            lockout_until = float(self.db.get_setting("emergency_lockout_until", "0"))
        except ValueError:
            lockout_until = 0.0
        now = self._time_fn()
        if lockout_until > now:
            return max(1, int(round(lockout_until - now)))
        return 0

    def get_failed_attempts(self) -> int:
        try:
            return int(self.db.get_setting("emergency_failed_attempts", "0"))
        except ValueError:
            return 0

    def verify_password(self, candidate_password: str) -> tuple[bool, int, str]:
        """Şifreyi doğrular.

        Dönüş: (başarılı_mı, kalan_bekleme_saniyesi, mesaj)
        """
        remaining = self.get_remaining_lockout_seconds()
        if remaining > 0:
            self.db.log_audit(
                "EMERGENCY_AUTH_LOCKED",
                f"Bekleme süresi dolmadan deneme yapıldı ({remaining} sn kaldı).",
            )
            return False, remaining, f"Çok fazla hatalı deneme. Lütfen {remaining} saniye bekleyin."

        raw = self.db.get_setting("emergency_password_hash", "").strip()
        if not raw:
            return False, 0, "Acil çıkış şifresi henüz tanımlanmamış."

        try:
            data = json.loads(raw)
            salt = bytes.fromhex(data["salt"])
            expected_hash = bytes.fromhex(data["hash"])
            iterations = int(data.get("iterations", PBKDF2_ITERATIONS))
        except Exception:
            return False, 0, "Şifre verisi bozuk."

        candidate_digest = hashlib.pbkdf2_hmac(
            "sha256",
            candidate_password.strip().encode("utf-8"),
            salt,
            iterations,
        )

        if hmac.compare_digest(candidate_digest, expected_hash):
            self.db.set_setting("emergency_failed_attempts", "0")
            self.db.set_setting("emergency_lockout_until", "0")
            self.db.log_audit("EMERGENCY_AUTH_SUCCESS", "Acil çıkış şifresi doğrulandı, kilit açıldı.")
            return True, 0, "Acil çıkış onaylandı."

        # Hatalı giriş -> sayacı artır ve bekleme uygula
        attempts = self.get_failed_attempts() + 1
        backoff = compute_backoff_seconds(attempts)
        lockout_until = self._time_fn() + backoff

        self.db.set_setting("emergency_failed_attempts", str(attempts))
        self.db.set_setting("emergency_lockout_until", str(lockout_until))
        self.db.log_audit(
            "EMERGENCY_AUTH_FAIL",
            f"Hatalı şifre denemesi (#{attempts}). {backoff} sn bekleme uygulandı.",
        )
        return False, backoff, f"Hatalı şifre! {backoff} saniye boyunca yeni deneme engellendi."
