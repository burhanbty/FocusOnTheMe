"""Acil çıkış PBKDF2 şifre doğrulama, artan bekleme (exponential backoff) ve loglama testleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.auth import EmergencyAuthManager, compute_backoff_seconds
from app.core.database import Database


def test_compute_backoff_schedule() -> None:
    assert compute_backoff_seconds(0) == 0
    assert compute_backoff_seconds(1) == 5
    assert compute_backoff_seconds(2) == 5
    assert compute_backoff_seconds(3) == 30
    assert compute_backoff_seconds(4) == 120
    assert compute_backoff_seconds(5) == 600
    assert compute_backoff_seconds(10) == 600


def test_emergency_auth_backoff_and_audit_log(tmp_path: Path) -> None:
    fake_now = [1000.0]
    db = Database(tmp_path / "auth_test.db")
    auth = EmergencyAuthManager(db, time_fn=lambda: fake_now[0])

    assert not auth.has_password()

    with pytest.raises(ValueError):
        auth.set_password("123")  # 4 karakterden kısa

    auth.set_password("GizliSifre2026!")
    assert auth.has_password()

    # 1. yanlış deneme -> 5 sn bekleme
    ok, wait_s, _ = auth.verify_password("yanlis1")
    assert not ok
    assert wait_s == 5
    assert auth.get_remaining_lockout_seconds() == 5

    # Bekleme süresi dolmadan doğru şifre girilse bile reddedilmeli
    fake_now[0] += 2.0
    ok_during_lock, rem_s, _ = auth.verify_password("GizliSifre2026!")
    assert not ok_during_lock
    assert rem_s == 3

    # Süre dolduktan sonra 2. yanlış deneme -> 5 sn
    fake_now[0] += 4.0
    ok2, wait2, _ = auth.verify_password("yanlis2")
    assert not ok2
    assert wait2 == 5

    # 3. yanlış deneme -> 30 sn
    fake_now[0] += 6.0
    ok3, wait3, _ = auth.verify_password("yanlis3")
    assert not ok3
    assert wait3 == 30

    # 4. yanlış deneme -> 120 sn
    fake_now[0] += 31.0
    ok4, wait4, _ = auth.verify_password("yanlis4")
    assert not ok4
    assert wait4 == 120

    # Süre dolduktan sonra doğru şifre -> başarılı ve sayaç sıfırlanır
    fake_now[0] += 121.0
    ok_final, wait_final, _ = auth.verify_password("GizliSifre2026!")
    assert ok_final
    assert wait_final == 0
    assert auth.get_failed_attempts() == 0

    logs = db.get_audit_logs(limit=20)
    event_types = [row["event_type"] for row in logs]
    assert "EMERGENCY_PASSWORD_SET" in event_types
    assert "EMERGENCY_AUTH_FAIL" in event_types
    assert "EMERGENCY_AUTH_LOCKED" in event_types
    assert "EMERGENCY_AUTH_SUCCESS" in event_types
