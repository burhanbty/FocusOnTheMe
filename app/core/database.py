"""SQLite yerel veritabanı katmanı — görevler, beyaz liste, düşünce parkı, ayarlar ve istatistikler."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.config import DB_PATH, DEFAULT_ALLOWED_URLS, DEFAULT_COURSES, ensure_data_dirs
from app.core.logical_date import calculate_streak, get_logical_date


class Database:
    """Ders Kilidi uygulaması için yerel SQLite veritabanı yöneticisi."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        ensure_data_dirs()
        self.db_path = Path(db_path) if db_path is not None else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._seed_defaults_if_empty()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logical_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    estimated_minutes INTEGER,
                    completed INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    proof_path TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_logical_date
                    ON tasks(logical_date);

                CREATE TABLE IF NOT EXISTS daily_sessions (
                    logical_date TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    focus_seconds INTEGER NOT NULL DEFAULT 0,
                    blocked_app_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS allowed_apps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    exe_path TEXT NOT NULL UNIQUE,
                    exe_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS allowed_urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_pattern TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS thoughts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    logical_date TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS courses (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS course_study_logs (
                    logical_date TEXT NOT NULL,
                    course_code TEXT NOT NULL,
                    active_seconds INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (logical_date, course_code)
                );

                CREATE TABLE IF NOT EXISTS app_usage_logs (
                    logical_date TEXT NOT NULL,
                    exe_name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    active_seconds INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (logical_date, exe_name)
                );
                """
            )

    def _seed_defaults_if_empty(self) -> None:
        with self.connect() as conn:
            url_count = conn.execute("SELECT COUNT(*) FROM allowed_urls").fetchone()[0]
            if url_count == 0:
                for url in DEFAULT_ALLOWED_URLS:
                    conn.execute(
                        "INSERT OR IGNORE INTO allowed_urls (url_pattern, enabled) VALUES (?, 1)",
                        (url,),
                    )

            course_count = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
            if course_count == 0:
                for idx, (code, name) in enumerate(DEFAULT_COURSES, start=1):
                    conn.execute(
                        "INSERT OR IGNORE INTO courses (code, name, sort_order) VALUES (?, ?, ?)",
                        (code, name, idx),
                    )

            app_count = conn.execute("SELECT COUNT(*) FROM allowed_apps").fetchone()[0]
            if app_count == 0:
                edge_candidates = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ]
                for candidate in edge_candidates:
                    if os.path.exists(candidate):
                        conn.execute(
                            "INSERT OR IGNORE INTO allowed_apps (name, exe_path, exe_name, enabled) VALUES (?, ?, ?, 1)",
                            ("Microsoft Edge", candidate, "msedge.exe"),
                        )
                        break

            # Varsayılan ayarlar
            default_course_code = DEFAULT_COURSES[0][0] if DEFAULT_COURSES else "CENG101"
            default_settings = {
                "require_screenshot_proof": "0",
                "study_folder_path": "",
                "active_course_code": default_course_code,
                "emergency_failed_attempts": "0",
                "emergency_lockout_until": "0",
            }
            for k, v in default_settings.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

    # ------------------------------------------------------------------
    # Ayarlar (Settings)
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def is_screenshot_proof_required(self) -> bool:
        return self.get_setting("require_screenshot_proof", "0") == "1"

    def set_screenshot_proof_required(self, required: bool) -> None:
        self.set_setting("require_screenshot_proof", "1" if required else "0")

    def get_study_folder(self) -> str:
        return self.get_setting("study_folder_path", "").strip()

    def set_study_folder(self, folder_path: str) -> None:
        self.set_setting("study_folder_path", folder_path.strip())

    # ------------------------------------------------------------------
    # Görev Yönetimi (Tasks)
    # ------------------------------------------------------------------
    def add_task(
        self,
        title: str,
        subject: str,
        estimated_minutes: int | None = None,
        logical_date: str | None = None,
    ) -> int:
        ldate = logical_date or get_logical_date()
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM tasks WHERE logical_date = ?",
                (ldate,),
            ).fetchone()[0]
            cur = conn.execute(
                """
                INSERT INTO tasks (logical_date, title, subject, estimated_minutes, completed, sort_order, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (ldate, title.strip(), subject.strip(), estimated_minutes, max_order + 1, now_iso),
            )
            return int(cur.lastrowid)

    def delete_task(self, task_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def get_tasks_for_date(self, logical_date: str | None = None) -> list[dict[str, Any]]:
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE logical_date = ? ORDER BY sort_order ASC, id ASC",
                (ldate,),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_task_completed(
        self,
        task_id: int,
        completed: bool,
        proof_path: str | None = None,
    ) -> None:
        completed_at = datetime.now().isoformat(timespec="seconds") if completed else None
        with self.connect() as conn:
            if proof_path is not None:
                conn.execute(
                    "UPDATE tasks SET completed = ?, completed_at = ?, proof_path = ? WHERE id = ?",
                    (1 if completed else 0, completed_at, proof_path, task_id),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?",
                    (1 if completed else 0, completed_at, task_id),
                )

    def are_all_tasks_completed(self, logical_date: str | None = None) -> bool:
        tasks = self.get_tasks_for_date(logical_date)
        if not tasks:
            return False
        return all(bool(t["completed"]) for t in tasks)

    # ------------------------------------------------------------------
    # Günlük Oturum ve İstatistikler (Daily Sessions & Stats)
    # ------------------------------------------------------------------
    def start_or_resume_session(self, logical_date: str | None = None) -> dict[str, Any]:
        ldate = logical_date or get_logical_date()
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_sessions WHERE logical_date = ?",
                (ldate,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO daily_sessions (logical_date, started_at, status, focus_seconds, blocked_app_count)
                    VALUES (?, ?, 'active', 0, 0)
                    """,
                    (ldate, now_iso),
                )
            else:
                conn.execute(
                    "UPDATE daily_sessions SET status = 'active' WHERE logical_date = ?",
                    (ldate,),
                )
            updated = conn.execute(
                "SELECT * FROM daily_sessions WHERE logical_date = ?",
                (ldate,),
            ).fetchone()
            return dict(updated)

    def increment_focus_seconds(self, seconds: int = 1, logical_date: str | None = None) -> None:
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            conn.execute(
                "UPDATE daily_sessions SET focus_seconds = focus_seconds + ? WHERE logical_date = ?",
                (max(0, int(seconds)), ldate),
            )

    def increment_blocked_app_count(self, app_name: str = "", logical_date: str | None = None) -> None:
        ldate = logical_date or get_logical_date()
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                "UPDATE daily_sessions SET blocked_app_count = blocked_app_count + 1 WHERE logical_date = ?",
                (ldate,),
            )
            conn.execute(
                "INSERT INTO audit_log (timestamp, event_type, details) VALUES (?, 'BLOCKED_APP', ?)",
                (now_iso, f"İzinsiz uygulama kapatıldı: {app_name}"),
            )

    def mark_session_status(self, status: str, logical_date: str | None = None) -> None:
        ldate = logical_date or get_logical_date()
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            if status == "completed":
                conn.execute(
                    "UPDATE daily_sessions SET status = ?, completed_at = ? WHERE logical_date = ?",
                    (status, now_iso, ldate),
                )
            else:
                conn.execute(
                    "UPDATE daily_sessions SET status = ? WHERE logical_date = ?",
                    (status, ldate),
                )

    def get_session_stats(self, logical_date: str | None = None) -> dict[str, Any]:
        ldate = logical_date or get_logical_date()
        tasks = self.get_tasks_for_date(ldate)
        completed_tasks = sum(1 for t in tasks if t["completed"])
        total_tasks = len(tasks)

        with self.connect() as conn:
            session_row = conn.execute(
                "SELECT * FROM daily_sessions WHERE logical_date = ?",
                (ldate,),
            ).fetchone()
            completed_dates_rows = conn.execute(
                "SELECT logical_date FROM daily_sessions WHERE status = 'completed'"
            ).fetchall()

        completed_dates = [r["logical_date"] for r in completed_dates_rows]
        streak = calculate_streak(completed_dates, reference_logical_date=ldate)

        focus_seconds = int(session_row["focus_seconds"]) if session_row else 0
        blocked_count = int(session_row["blocked_app_count"]) if session_row else 0
        status = str(session_row["status"]) if session_row else "idle"

        return {
            "logical_date": ldate,
            "completed_tasks": completed_tasks,
            "total_tasks": total_tasks,
            "focus_seconds": focus_seconds,
            "focus_minutes": round(focus_seconds / 60.0, 1),
            "blocked_app_count": blocked_count,
            "streak_days": streak,
            "status": status,
        }

    # ------------------------------------------------------------------
    # İzinli Uygulamalar (Beyaz Liste)
    # ------------------------------------------------------------------
    def get_allowed_apps(self, only_enabled: bool = True) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if only_enabled:
                rows = conn.execute(
                    "SELECT * FROM allowed_apps WHERE enabled = 1 ORDER BY id ASC"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM allowed_apps ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def add_allowed_app(self, name: str, exe_path: str) -> int:
        norm_path = os.path.normpath(exe_path.strip())
        exe_name = os.path.basename(norm_path).lower()
        display_name = name.strip() or os.path.splitext(os.path.basename(norm_path))[0]
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO allowed_apps (name, exe_path, exe_name, enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(exe_path) DO UPDATE SET
                    name = excluded.name,
                    exe_name = excluded.exe_name,
                    enabled = 1
                """,
                (display_name, norm_path, exe_name),
            )
            return int(cur.lastrowid or 0)

    def remove_allowed_app(self, app_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM allowed_apps WHERE id = ?", (app_id,))

    # ------------------------------------------------------------------
    # İzinli Siteler (Edge URLAllowlist)
    # ------------------------------------------------------------------
    def get_allowed_urls(self, only_enabled: bool = True) -> list[str]:
        with self.connect() as conn:
            if only_enabled:
                rows = conn.execute(
                    "SELECT url_pattern FROM allowed_urls WHERE enabled = 1 ORDER BY id ASC"
                ).fetchall()
            else:
                rows = conn.execute("SELECT url_pattern FROM allowed_urls ORDER BY id ASC").fetchall()
            return [str(r["url_pattern"]) for r in rows]

    def add_allowed_url(self, url_pattern: str) -> None:
        cleaned = url_pattern.strip()
        if not cleaned:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO allowed_urls (url_pattern, enabled) VALUES (?, 1)",
                (cleaned,),
            )

    def remove_allowed_url(self, url_pattern: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM allowed_urls WHERE url_pattern = ?", (url_pattern.strip(),))

    # ------------------------------------------------------------------
    # Düşünce Park Alanı (Thoughts)
    # ------------------------------------------------------------------
    def add_thought(self, content: str, logical_date: str | None = None) -> int:
        cleaned = content.strip()
        if not cleaned:
            return 0
        ldate = logical_date or get_logical_date()
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO thoughts (logical_date, content, created_at) VALUES (?, ?, ?)",
                (ldate, cleaned, now_iso),
            )
            return int(cur.lastrowid)

    def get_thoughts_for_date(self, logical_date: str | None = None) -> list[dict[str, Any]]:
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thoughts WHERE logical_date = ? ORDER BY id ASC",
                (ldate,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Denetim Kaydı (Audit Log)
    # ------------------------------------------------------------------
    def log_audit(self, event_type: str, details: str) -> None:
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (timestamp, event_type, details) VALUES (?, ?, ?)",
                (now_iso, event_type, details),
            )

    def get_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Dersler, Ders Çalışma Süreleri ve Uygulama Kullanım Süreleri
    # ------------------------------------------------------------------
    def get_courses(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT code, name, sort_order FROM courses ORDER BY sort_order ASC, code ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def add_course(self, code: str, name: str) -> None:
        clean_code = code.strip().upper()
        clean_name = name.strip()
        if not clean_code:
            return
        if not clean_name:
            clean_name = clean_code
        with self.connect() as conn:
            max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM courses").fetchone()[0]
            conn.execute(
                """
                INSERT INTO courses (code, name, sort_order)
                VALUES (?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET name = excluded.name
                """,
                (clean_code, clean_name, max_order + 1),
            )

    def get_active_course(self) -> str:
        default_code = DEFAULT_COURSES[0][0] if DEFAULT_COURSES else "CENG101"
        val = self.get_setting("active_course_code", default_code).strip()
        return val or default_code

    def set_active_course(self, course_code: str) -> None:
        cleaned = course_code.strip()
        if cleaned:
            self.set_setting("active_course_code", cleaned)

    def increment_course_study_seconds(
        self,
        course_code: str,
        seconds: int = 1,
        logical_date: str | None = None,
    ) -> None:
        code = (course_code or "").strip() or self.get_active_course()
        ldate = logical_date or get_logical_date()
        delta = max(0, int(seconds))
        if delta <= 0:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO course_study_logs (logical_date, course_code, active_seconds)
                VALUES (?, ?, ?)
                ON CONFLICT(logical_date, course_code) DO UPDATE SET
                    active_seconds = course_study_logs.active_seconds + excluded.active_seconds
                """,
                (ldate, code, delta),
            )

    def get_course_study_seconds(
        self,
        course_code: str,
        logical_date: str | None = None,
    ) -> int:
        code = (course_code or "").strip() or self.get_active_course()
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT active_seconds FROM course_study_logs WHERE logical_date = ? AND course_code = ?",
                (ldate, code),
            ).fetchone()
            return int(row["active_seconds"]) if row else 0

    def get_course_study_stats(self, logical_date: str | None = None) -> list[dict[str, Any]]:
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    l.course_code,
                    COALESCE(c.name, l.course_code) AS course_name,
                    l.active_seconds
                FROM course_study_logs l
                LEFT JOIN courses c ON c.code = l.course_code
                WHERE l.logical_date = ? AND l.active_seconds > 0
                ORDER BY l.active_seconds DESC, l.course_code ASC
                """,
                (ldate,),
            ).fetchall()
            return [dict(r) for r in rows]

    def increment_app_usage_seconds(
        self,
        exe_name: str,
        display_name: str,
        seconds: int = 1,
        logical_date: str | None = None,
    ) -> None:
        norm_exe = (exe_name or "").strip().lower()
        if not norm_exe:
            return
        disp = (display_name or "").strip() or norm_exe
        ldate = logical_date or get_logical_date()
        delta = max(0, int(seconds))
        if delta <= 0:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_usage_logs (logical_date, exe_name, display_name, active_seconds)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(logical_date, exe_name) DO UPDATE SET
                    display_name = excluded.display_name,
                    active_seconds = app_usage_logs.active_seconds + excluded.active_seconds
                """,
                (ldate, norm_exe, disp, delta),
            )

    def get_app_usage_stats(self, logical_date: str | None = None) -> list[dict[str, Any]]:
        ldate = logical_date or get_logical_date()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT exe_name, display_name, active_seconds
                FROM app_usage_logs
                WHERE logical_date = ? AND active_seconds > 0
                ORDER BY active_seconds DESC, display_name ASC
                """,
                (ldate,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_active_tick(
        self,
        logical_date: str,
        course_code: str,
        is_active: bool,
        app_exe: str | None = None,
        app_display: str | None = None,
    ) -> int:
        """1 saniyelik döngüde tüm süre güncellemelerini TEK bir SQLite işleminde yapar
        ve seçili dersin güncel toplam saniyesini döndürür.
        """
        code = (course_code or "").strip() or "CENG101"
        with self.connect() as conn:
            if is_active:
                conn.execute(
                    "UPDATE daily_sessions SET focus_seconds = focus_seconds + 1 WHERE logical_date = ?",
                    (logical_date,),
                )
                conn.execute(
                    """
                    INSERT INTO course_study_logs (logical_date, course_code, active_seconds)
                    VALUES (?, ?, 1)
                    ON CONFLICT(logical_date, course_code) DO UPDATE SET
                        active_seconds = course_study_logs.active_seconds + 1
                    """,
                    (logical_date, code),
                )
                if app_exe:
                    norm_exe = app_exe.strip().lower()
                    disp = (app_display or "").strip() or norm_exe
                    conn.execute(
                        """
                        INSERT INTO app_usage_logs (logical_date, exe_name, display_name, active_seconds)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(logical_date, exe_name) DO UPDATE SET
                            display_name = excluded.display_name,
                            active_seconds = app_usage_logs.active_seconds + 1
                        """,
                        (logical_date, norm_exe, disp),
                    )
            row = conn.execute(
                "SELECT active_seconds FROM course_study_logs WHERE logical_date = ? AND course_code = ?",
                (logical_date, code),
            ).fetchone()
            return int(row["active_seconds"]) if row else 0
