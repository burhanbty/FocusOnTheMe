"""04:00 gün sınırı, seri (streak) hesaplama ve veritabanı görev akışı birim testleri."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.database import Database
from app.core.logical_date import calculate_streak, get_logical_date


def test_logical_date_boundary_before_0400() -> None:
    dt = datetime(2026, 10, 30, 3, 59, 59)
    assert get_logical_date(dt) == "2026-10-29"


def test_logical_date_boundary_at_0400() -> None:
    dt = datetime(2026, 10, 30, 4, 0, 0)
    assert get_logical_date(dt) == "2026-10-30"


def test_logical_date_boundary_afternoon() -> None:
    dt = datetime(2026, 10, 30, 14, 30, 0)
    assert get_logical_date(dt) == "2026-10-30"


def test_streak_calculation_consecutive_days() -> None:
    completed = ["2026-10-28", "2026-10-29", "2026-10-30"]
    assert calculate_streak(completed, reference_logical_date="2026-10-30") == 3


def test_streak_calculation_today_pending_yesterday_completed() -> None:
    completed = ["2026-10-27", "2026-10-28", "2026-10-29"]
    assert calculate_streak(completed, reference_logical_date="2026-10-30") == 3


def test_streak_calculation_broken_streak() -> None:
    completed = ["2026-10-25", "2026-10-26", "2026-10-28"]
    assert calculate_streak(completed, reference_logical_date="2026-10-30") == 0


def test_database_tasks_thoughts_and_stats(tmp_path: Path) -> None:
    db_file = tmp_path / "test_ders_kilidi.db"
    db = Database(db_file)

    ldate = "2026-10-30"
    assert db.get_tasks_for_date(ldate) == []
    assert not db.are_all_tasks_completed(ldate)

    t1 = db.add_task("20 soru çöz", "Matematik", estimated_minutes=40, logical_date=ldate)
    t2 = db.add_task("Makale oku", "Fizik", estimated_minutes=25, logical_date=ldate)

    tasks = db.get_tasks_for_date(ldate)
    assert len(tasks) == 2
    assert not db.are_all_tasks_completed(ldate)

    db.start_or_resume_session(ldate)
    db.increment_focus_seconds(120, ldate)
    db.increment_blocked_app_count("notepad.exe", ldate)

    db.add_thought("Kütüphaneden kitabı almayı unutma", ldate)
    thoughts = db.get_thoughts_for_date(ldate)
    assert len(thoughts) == 1
    assert thoughts[0]["content"] == "Kütüphaneden kitabı almayı unutma"

    db.set_task_completed(t1, True)
    assert not db.are_all_tasks_completed(ldate)

    db.set_task_completed(t2, True)
    assert db.are_all_tasks_completed(ldate)

    db.mark_session_status("completed", ldate)
    stats = db.get_session_stats(ldate)
    assert stats["completed_tasks"] == 2
    assert stats["total_tasks"] == 2
    assert stats["focus_seconds"] == 120
    assert stats["blocked_app_count"] == 1
    assert stats["streak_days"] == 1
