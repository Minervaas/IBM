"""
agent.py — Study Assistant AI agent for Study Planner.

Architecture
------------
1. build_task_context()  — converts DB rows into a structured text block
   the LLM (or rule engine) can reason about.

2. run_agent()           — public entry point called by the Flask route.
   * If OPENAI_API_KEY is set → calls the OpenAI Chat Completions API
     (model gpt-4o-mini by default; override with STUDY_PLANNER_LLM_MODEL).
   * Otherwise              → falls back to rule_based_answer(), which ranks
     tasks by urgency and priority and generates a plain-text reply.

The fallback guarantees the app is fully functional with zero API key,
and is also what the pytest suite exercises so no real API calls are made
in CI.

Environment variables
---------------------
OPENAI_API_KEY          — your OpenAI secret key (optional)
STUDY_PLANNER_LLM_MODEL — override the default model (optional,
                           default: gpt-4o-mini)
"""

import os
import json
import textwrap
from datetime import date, timedelta

import database as db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_MODEL_DEFAULT = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_task_context(tasks: list) -> str:
    """
    Serialise a list of sqlite3.Row (or plain dicts) task objects into a
    human-readable numbered list that can be embedded in an LLM prompt.

    Returns an empty-state message when there are no tasks.
    """
    if not tasks:
        return "The student currently has no tasks in their planner."

    today = date.today()
    lines = []

    for i, t in enumerate(tasks, start=1):
        # sqlite3.Row supports dict-style access; plain dicts also work.
        title    = t["title"]
        course   = t["course"]
        deadline = t["deadline"]
        priority = t["priority"]
        done     = bool(t["done"])

        try:
            deadline_date = date.fromisoformat(deadline)
            days_left = (deadline_date - today).days
            if done:
                urgency = "✅ done"
            elif days_left < 0:
                urgency = f"⚠ OVERDUE by {abs(days_left)} day(s)"
            elif days_left == 0:
                urgency = "⚠ due TODAY"
            elif days_left <= 7:
                urgency = f"due in {days_left} day(s)"
            else:
                urgency = f"due in {days_left} day(s)"
        except ValueError:
            urgency = "unknown deadline"

        status_str = "done" if done else "pending"
        lines.append(
            f"{i}. [{priority.upper()}] \"{title}\" ({course}) — "
            f"deadline {deadline} ({urgency}), status: {status_str}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------

def _urgency_score(task) -> tuple:
    """
    Return a sort key (days_until_deadline, priority_rank) used to rank
    pending tasks by urgency.  Overdue tasks get a negative days value so
    they sort to the top.
    """
    today = date.today()
    try:
        deadline_date = date.fromisoformat(task["deadline"])
        days_left = (deadline_date - today).days
    except (ValueError, TypeError):
        days_left = 9999  # unknown deadline → treat as far future

    priority_rank = _PRIORITY_RANK.get(task["priority"], 1)
    return (days_left, priority_rank)


def rule_based_answer(question: str, tasks: list) -> str:
    """
    Generate a helpful plain-text answer without calling any external API.

    Handles three intent families:
      - Priority / what to work on  → ranked pending task list
      - Schedule (daily/weekly)     → day-by-day schedule for next 7 days
      - General / count / status    → summary stats
    """
    q = question.lower()

    # Separate pending and done tasks
    pending = [t for t in tasks if not t["done"]]
    done    = [t for t in tasks if t["done"]]

    # Sort pending by urgency
    ranked = sorted(pending, key=_urgency_score)

    today = date.today()

    # ── Intent: priority / what to work on ─────────────────────────────
    if any(kw in q for kw in ("first", "priority", "start", "work on",
                               "important", "urgent", "should i")):
        if not pending:
            return (
                "Great news — you have no pending tasks right now! "
                "Take a well-earned break or get ahead on upcoming coursework."
            )

        lines = ["Here are your pending tasks ranked by urgency:\n"]
        for rank, t in enumerate(ranked, start=1):
            try:
                dl = date.fromisoformat(t["deadline"])
                days = (dl - today).days
                if days < 0:
                    time_note = f"OVERDUE by {abs(days)} day(s)"
                elif days == 0:
                    time_note = "due TODAY"
                else:
                    time_note = f"{days} day(s) remaining"
            except ValueError:
                time_note = "unknown deadline"

            lines.append(
                f"  {rank}. [{t['priority'].upper()}] \"{t['title']}\" "
                f"({t['course']}) — {time_note}"
            )

        lines.append(
            "\nFocus on overdue tasks first, then high-priority items "
            "with the closest deadlines."
        )
        return "\n".join(lines)

    # ── Intent: schedule ────────────────────────────────────────────────
    if any(kw in q for kw in ("schedule", "plan", "week", "today", "daily",
                               "calendar", "timetable")):
        if not pending:
            return (
                "You have no pending tasks to schedule. "
                "Add some tasks first, then ask me for a schedule!"
            )

        # Build a 7-day window
        week_end = today + timedelta(days=6)
        lines = [f"📅 Study Schedule  ({today} → {week_end})\n"]
        lines.append(
            "Suggested plan based on your deadlines and priorities:\n"
        )

        # Assign each pending task to a day slot
        assigned: dict[str, list] = {}
        for t in ranked:
            try:
                dl = date.fromisoformat(t["deadline"])
                days_left = (dl - today).days
            except ValueError:
                days_left = 7

            # Overdue → work on it today
            if days_left <= 0:
                slot = today
            # Due within 7 days → spread over days available
            elif days_left <= 7:
                slot = today + timedelta(days=max(0, days_left - 1))
            else:
                # Spread longer tasks later in the week
                slot = today + timedelta(days=min(6, days_left // 2))

            key = slot.isoformat()
            assigned.setdefault(key, []).append(t)

        for day_offset in range(7):
            day = today + timedelta(days=day_offset)
            key = day.isoformat()
            day_label = day.strftime("%A, %d %b")
            day_tasks = assigned.get(key, [])
            if day_tasks:
                lines.append(f"  {day_label}:")
                for t in day_tasks:
                    lines.append(
                        f"    • [{t['priority'].upper()}] \"{t['title']}\" ({t['course']})"
                    )
            else:
                lines.append(f"  {day_label}: — free day / review notes")

        lines.append(
            "\nTip: Review and adjust this schedule as you complete tasks."
        )
        return "\n".join(lines)

    # ── Intent: status / summary / general ─────────────────────────────
    overdue_tasks = [
        t for t in pending
        if (date.fromisoformat(t["deadline"]) - today).days < 0
    ]
    due_today = [
        t for t in pending
        if (date.fromisoformat(t["deadline"]) - today).days == 0
    ]
    due_this_week = [
        t for t in pending
        if 1 <= (date.fromisoformat(t["deadline"]) - today).days <= 7
    ]

    lines = [
        f"Here's a summary of your study workload:\n",
        f"  • Total tasks: {len(tasks)}",
        f"  • Completed:   {len(done)}",
        f"  • Pending:     {len(pending)}",
        f"  • Overdue:     {len(overdue_tasks)}",
        f"  • Due today:   {len(due_today)}",
        f"  • Due this week: {len(due_this_week)}",
    ]

    if overdue_tasks:
        lines.append("\n⚠ Overdue tasks need immediate attention:")
        for t in overdue_tasks:
            lines.append(f"   – \"{t['title']}\" ({t['course']})")

    if due_today:
        lines.append("\n📌 Due today:")
        for t in due_today:
            lines.append(f"   – \"{t['title']}\" ({t['course']})")

    if not overdue_tasks and not due_today and not due_this_week:
        lines.append("\nYou're on top of things — no urgent deadlines this week! 🎉")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM caller (OpenAI)
# ---------------------------------------------------------------------------

def _call_openai(question: str, context: str, api_key: str) -> str:
    """
    Call the OpenAI Chat Completions API and return the assistant's reply.

    Uses the stdlib urllib so we don't require the openai SDK package —
    the only required install is already included via requests (optional)
    or plain urllib.  We use urllib to avoid adding an extra dependency.
    """
    import urllib.request
    import urllib.error

    model = os.environ.get("STUDY_PLANNER_LLM_MODEL", _MODEL_DEFAULT)

    system_prompt = textwrap.dedent(f"""\
        You are a helpful Study Assistant for a university student.
        Your job is to help them manage their coursework tasks, prioritise
        their workload, and create practical study schedules.

        Today's date is {date.today().isoformat()}.

        The student's current task list is:
        {context}

        Keep your answers concise, practical, and encouraging.
        When listing tasks, use a numbered or bulleted format.
        If the task list is empty, gently prompt them to add tasks first.
    """)

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": question},
        ],
        "max_tokens": 800,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"OpenAI API error {exc.code}: {error_body}"
        ) from exc


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_agent(question: str, db_path: str = db.DB_PATH) -> dict:
    """
    Answer a student's question using their task data as context.

    Returns a dict:
        {
            "answer":  str,          # the reply text
            "mode":    "llm" | "fallback",
            "model":   str | None,   # model name if LLM was used
        }

    Never raises — errors are caught and returned as a user-friendly message
    so the Flask route can always return a 200 JSON response.
    """
    question = (question or "").strip()
    if not question:
        return {
            "answer": "Please ask me a question about your tasks or study schedule!",
            "mode": "fallback",
            "model": None,
        }

    # Load tasks from the database
    try:
        tasks = db.get_all_tasks(db_path=db_path)
    except Exception as exc:  # pragma: no cover
        return {
            "answer": f"Sorry, I couldn't load your tasks: {exc}",
            "mode": "fallback",
            "model": None,
        }

    context = build_task_context(tasks)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if api_key:
        try:
            answer = _call_openai(question, context, api_key)
            return {
                "answer": answer,
                "mode": "llm",
                "model": os.environ.get("STUDY_PLANNER_LLM_MODEL", _MODEL_DEFAULT),
            }
        except Exception as exc:
            # Fall back gracefully if the API call fails
            fallback_note = (
                f"\n\n_(AI service unavailable: {exc}. "
                "Showing rule-based answer instead.)_"
            )
            answer = rule_based_answer(question, tasks) + fallback_note
            return {"answer": answer, "mode": "fallback", "model": None}
    else:
        answer = rule_based_answer(question, tasks)
        return {"answer": answer, "mode": "fallback", "model": None}
