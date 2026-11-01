"""
database.py — SQLite database setup and query helpers for Study Planner.

All database interactions are isolated here to keep app.py clean.
Uses the stdlib sqlite3 module; no ORM required for this scale.
"""

import sqlite3
import os
from datetime import date, datetime


# Default database path; can be overridden via environment variable (useful in tests).
DB_PATH = os.environ.get("STUDY_PLANNER_DB", "study_planner.db")

# Valid priority values enforced at the DB helper level as a second line of defence.
VALID_PRIORITIES = ("low", "medium", "high")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Return a new SQLite connection with row_factory set to Row."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row          # access columns by name
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db(db_path: str = DB_PATH) -> None:
    """Create the tasks table if it does not already exist."""
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                course      TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                deadline    TEXT    NOT NULL,   -- stored as ISO-8601 date string
                priority    TEXT    NOT NULL DEFAULT 'medium',
                done        INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=done
                created_at  TEXT    NOT NULL DEFAULT (date('now'))
            )
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SEED_TASKS = [
    {
        "title": "Write literature review",
        "course": "Research Methods",
        "description": "Cover at least 10 peer-reviewed sources on the chosen topic.",
        "deadline": "2026-11-10",
        "priority": "high",
        "done": 0,
    },
    {
        "title": "Complete problem set 3",
        "course": "Calculus II",
        "description": "Chapters 7–9, integration techniques.",
        "deadline": "2026-11-05",
        "priority": "medium",
        "done": 0,
    },
    {
        "title": "Read chapters 4–6",
        "course": "Modern History",
        "description": "Focus on post-war economic recovery.",
        "deadline": "2026-11-03",
        "priority": "low",
        "done": 1,
    },
    {
        "title": "Lab report: titration experiment",
        "course": "Chemistry 101",
        "description": "Include error analysis and graphs.",
        "deadline": "2026-11-08",
        "priority": "high",
        "done": 0,
    },
    {
        "title": "Group presentation slides",
        "course": "Business Strategy",
        "description": "Prepare 15-slide deck for Thursday's class.",
        "deadline": "2026-11-06",
        "priority": "medium",
        "done": 0,
    },
    {
        "title": "Submit weekly reflection",
        "course": "Modern History",
        "description": "500-word reflection on the lecture material.",
        "deadline": "2026-10-28",   # intentionally in the past → overdue
        "priority": "low",
        "done": 0,
    },
]


def seed_db(db_path: str = DB_PATH) -> None:
    """Insert sample tasks only when the table is empty (first run)."""
    with get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:
            conn.executemany(
                """
                INSERT INTO tasks (title, course, description, deadline, priority, done)
                VALUES (:title, :course, :description, :deadline, :priority, :done)
                """,
                SEED_TASKS,
            )
            conn.commit()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def get_all_tasks(
    db_path: str = DB_PATH,
    course: str = "",
    priority: str = "",
    status: str = "",
    sort: str = "deadline",
) -> list[sqlite3.Row]:
    """
    Return tasks with optional filtering and sorting.

    Filters:
        course   — exact match (case-insensitive)
        priority — one of low/medium/high
        status   — 'done', 'pending', or '' (all)
    Sort:
        deadline | priority | course | title  (always ascending)
    """
    allowed_sorts = {"deadline", "priority", "course", "title", "created_at"}
    if sort not in allowed_sorts:
        sort = "deadline"

    conditions = []
    params: list = []

    if course:
        conditions.append("LOWER(course) = LOWER(?)")
        params.append(course)
    if priority and priority in VALID_PRIORITIES:
        conditions.append("priority = ?")
        params.append(priority)
    if status == "done":
        conditions.append("done = 1")
    elif status == "pending":
        conditions.append("done = 0")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Priority sort requires a custom CASE expression so low<medium<high
    if sort == "priority":
        order_expr = "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
    else:
        order_expr = sort

    query = f"SELECT * FROM tasks {where_clause} ORDER BY {order_expr}"

    with get_connection(db_path) as conn:
        return conn.execute(query, params).fetchall()


def get_task(task_id: int, db_path: str = DB_PATH) -> sqlite3.Row | None:
    """Return a single task by ID, or None if not found."""
    with get_connection(db_path) as conn:
        return conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()


def create_task(data: dict, db_path: str = DB_PATH) -> int:
    """Insert a new task and return its new ID."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (title, course, description, deadline, priority, done)
            VALUES (:title, :course, :description, :deadline, :priority, 0)
            """,
            data,
        )
        conn.commit()
        return cursor.lastrowid


def update_task(task_id: int, data: dict, db_path: str = DB_PATH) -> bool:
    """Update an existing task. Returns True if a row was affected."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE tasks
               SET title       = :title,
                   course      = :course,
                   description = :description,
                   deadline    = :deadline,
                   priority    = :priority
             WHERE id = :id
            """,
            {**data, "id": task_id},
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_task(task_id: int, db_path: str = DB_PATH) -> bool:
    """Delete a task by ID. Returns True if a row was deleted."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0


def toggle_done(task_id: int, db_path: str = DB_PATH) -> bool:
    """Flip the done flag of a task. Returns True if the task was found."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Dashboard stats helper
# ---------------------------------------------------------------------------

def get_stats(db_path: str = DB_PATH) -> dict:
    """
    Return aggregate stats for the dashboard and per-course progress bars.

    Returns a dict with:
        total, completed, overdue, due_soon (next 7 days, pending only)
        courses: list of {course, total, completed, pct}
    """
    today = date.today().isoformat()
    # 7 days from today (inclusive)
    from datetime import timedelta
    week_end = (date.today() + timedelta(days=7)).isoformat()

    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE done = 1"
        ).fetchone()[0]
        overdue = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE done = 0 AND deadline < ?", (today,)
        ).fetchone()[0]
        due_soon = conn.execute(
            """
            SELECT COUNT(*) FROM tasks
             WHERE done = 0 AND deadline >= ? AND deadline <= ?
            """,
            (today, week_end),
        ).fetchone()[0]

        # Per-course breakdown
        rows = conn.execute(
            """
            SELECT course,
                   COUNT(*)                          AS total,
                   SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) AS completed
              FROM tasks
             GROUP BY LOWER(course)
             ORDER BY course
            """
        ).fetchall()

    courses = []
    for r in rows:
        pct = round((r["completed"] / r["total"]) * 100) if r["total"] else 0
        courses.append(
            {
                "course": r["course"],
                "total": r["total"],
                "completed": r["completed"],
                "pct": pct,
            }
        )

    return {
        "total": total,
        "completed": completed,
        "overdue": overdue,
        "due_soon": due_soon,
        "courses": courses,
    }


def get_distinct_courses(db_path: str = DB_PATH) -> list[str]:
    """Return a sorted list of unique course names for filter dropdowns."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT course FROM tasks ORDER BY course"
        ).fetchall()
    return [r["course"] for r in rows]
