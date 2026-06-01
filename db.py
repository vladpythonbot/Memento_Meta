import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from config import DB_PATH, DEFAULT_TIMEZONE


@dataclass(frozen=True)
class Task:
    id: int
    user_id: int
    title: str
    status: str
    created_at: str
    completed_at: str | None
    important: bool | None = None
    urgent: bool | None = None


@dataclass(frozen=True)
class Note:
    id: int
    user_id: int
    body: str
    created_at: str


@dataclass(frozen=True)
class FocusSession:
    id: int
    user_id: int
    method: str
    duration_minutes: int
    status: str
    started_at: str
    finished_at: str | None


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


async def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                timezone TEXT NOT NULL DEFAULT 'Europe/Kyiv',
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                important INTEGER,
                urgent INTEGER
            )
        """)
        await ensure_column(db, "tasks", "important", "INTEGER")
        await ensure_column(db, "tasks", "urgent", "INTEGER")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'started',
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
        """)
        await db.commit()


async def ensure_column(db: aiosqlite.Connection, table: str, column: str, definition: str) -> None:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in await cursor.fetchall()]

    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def ensure_user(user_id: int, first_name: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, first_name, timezone, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                first_name = excluded.first_name
        """, (user_id, first_name, DEFAULT_TIMEZONE, utc_now()))
        await db.commit()


async def add_note(user_id: int, body: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO notes (user_id, body, created_at) VALUES (?, ?, ?)",
            (user_id, body, utc_now()),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def delete_note(user_id: int, note_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ?",
            (note_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def add_task(user_id: int, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tasks (user_id, title, status, created_at) VALUES (?, ?, 'open', ?)",
            (user_id, title, utc_now()),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def complete_task(user_id: int, task_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE tasks
            SET status = 'done', completed_at = ?
            WHERE id = ? AND user_id = ? AND status = 'open'
        """, (utc_now(), task_id, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def update_task_matrix(user_id: int, task_id: int, important: bool, urgent: bool) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE tasks
            SET important = ?, urgent = ?
            WHERE id = ? AND user_id = ? AND status = 'open'
        """, (int(important), int(urgent), task_id, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_open_tasks(user_id: int, limit: int = 10) -> list[Task]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, user_id, title, status, created_at, completed_at, important, urgent
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()

    return [row_to_task(row) for row in rows]


async def get_matrix_tasks(user_id: int, limit: int = 40) -> list[Task]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, user_id, title, status, created_at, completed_at, important, urgent
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY
                CASE
                    WHEN important = 1 AND urgent = 1 THEN 0
                    WHEN important = 1 AND urgent = 0 THEN 1
                    WHEN important = 0 AND urgent = 1 THEN 2
                    WHEN important = 0 AND urgent = 0 THEN 3
                    ELSE 4
                END,
                id DESC
            LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()

    return [row_to_task(row) for row in rows]


async def get_next_action_task(user_id: int) -> Task | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, user_id, title, status, created_at, completed_at, important, urgent
            FROM tasks
            WHERE user_id = ? AND status = 'open'
            ORDER BY
                CASE
                    WHEN important = 1 AND urgent = 1 THEN 0
                    WHEN important = 1 AND urgent = 0 THEN 1
                    WHEN important IS NULL OR urgent IS NULL THEN 2
                    WHEN important = 0 AND urgent = 1 THEN 3
                    ELSE 4
                END,
                id ASC
            LIMIT 1
        """, (user_id,))
        row = await cursor.fetchone()

    return row_to_task(row) if row else None


def row_to_task(row) -> Task:
    return Task(
        id=row[0],
        user_id=row[1],
        title=row[2],
        status=row[3],
        created_at=row[4],
        completed_at=row[5],
        important=None if row[6] is None else bool(row[6]),
        urgent=None if row[7] is None else bool(row[7]),
    )


async def get_recent_notes(user_id: int, limit: int = 5) -> list[Note]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, user_id, body, created_at
            FROM notes
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()

    return [Note(*row) for row in rows]


async def start_focus_session(user_id: int, method: str, duration_minutes: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO focus_sessions (user_id, method, duration_minutes, status, started_at)
            VALUES (?, ?, ?, 'started', ?)
        """, (user_id, method, duration_minutes, utc_now()))
        await db.commit()
        return int(cursor.lastrowid)


async def get_active_focus_session(user_id: int) -> FocusSession | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, user_id, method, duration_minutes, status, started_at, finished_at
            FROM focus_sessions
            WHERE user_id = ? AND status = 'started'
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,))
        row = await cursor.fetchone()

    return FocusSession(*row) if row else None


async def finish_focus_session(user_id: int, session_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE focus_sessions
            SET status = 'done', finished_at = ?
            WHERE id = ? AND user_id = ? AND status = 'started'
        """, (utc_now(), session_id, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def cancel_focus_session(user_id: int, session_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE focus_sessions
            SET status = 'cancelled', finished_at = ?
            WHERE id = ? AND user_id = ? AND status = 'started'
        """, (utc_now(), session_id, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_daily_summary(user_id: int) -> dict[str, int]:
    today = dt.datetime.now(dt.UTC).date().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        done_tasks = await count_query(
            db,
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'done' AND completed_at LIKE ?",
            (user_id, f"{today}%"),
        )
        open_tasks = await count_query(
            db,
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'open'",
            (user_id,),
        )
        notes = await count_query(
            db,
            "SELECT COUNT(*) FROM notes WHERE user_id = ? AND created_at LIKE ?",
            (user_id, f"{today}%"),
        )
        focus_minutes = await count_query(
            db,
            """
            SELECT COALESCE(SUM(duration_minutes), 0)
            FROM focus_sessions
            WHERE user_id = ? AND status = 'done' AND finished_at LIKE ?
            """,
            (user_id, f"{today}%"),
        )

    return {
        "done_tasks": done_tasks,
        "open_tasks": open_tasks,
        "notes": notes,
        "focus_minutes": focus_minutes,
    }


async def get_period_summary(user_id: int, days: int = 7) -> dict:
    today = dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=days - 1)
    start_prefix = start.isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        done_tasks = await count_query(
            db,
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'done' AND completed_at >= ?",
            (user_id, start_prefix),
        )
        created_tasks = await count_query(
            db,
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND created_at >= ?",
            (user_id, start_prefix),
        )
        notes = await count_query(
            db,
            "SELECT COUNT(*) FROM notes WHERE user_id = ? AND created_at >= ?",
            (user_id, start_prefix),
        )
        focus_minutes = await count_query(
            db,
            """
            SELECT COALESCE(SUM(duration_minutes), 0)
            FROM focus_sessions
            WHERE user_id = ? AND status = 'done' AND finished_at >= ?
            """,
            (user_id, start_prefix),
        )

    daily = []
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        prefix = day.isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            day_done = await count_query(
                db,
                "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'done' AND completed_at LIKE ?",
                (user_id, f"{prefix}%"),
            )
            day_focus = await count_query(
                db,
                """
                SELECT COALESCE(SUM(duration_minutes), 0)
                FROM focus_sessions
                WHERE user_id = ? AND status = 'done' AND finished_at LIKE ?
                """,
                (user_id, f"{prefix}%"),
            )
        daily.append({"date": prefix, "done_tasks": day_done, "focus_minutes": day_focus})

    return {
        "days": days,
        "done_tasks": done_tasks,
        "created_tasks": created_tasks,
        "notes": notes,
        "focus_minutes": focus_minutes,
        "daily": daily,
    }


async def count_query(db: aiosqlite.Connection, query: str, params: tuple) -> int:
    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    return int(row[0] or 0)
