"""
tests/test_agent.py — pytest tests for the Study Assistant agent.

All tests exercise the rule-based fallback path; no API key is needed.
Each test uses an isolated temporary SQLite database so they are fully
independent of each other and of the development database.
"""

import os
import tempfile
import pytest

# Ensure no API key leaks in from the environment during tests.
os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    """Provide a fresh temporary database path, pre-initialised with schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import database as db_module
    db_module.init_db(path)
    yield path

    # On Windows, SQLite may hold the file briefly after tests; swallow the error.
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def db_with_tasks(db_path):
    """Database pre-populated with a small set of known tasks."""
    import database as db_module
    from datetime import date, timedelta

    today = date.today()

    tasks = [
        {
            "title": "High priority overdue task",
            "course": "Maths",
            "description": "",
            "deadline": (today - timedelta(days=3)).isoformat(),  # overdue
            "priority": "high",
        },
        {
            "title": "Medium priority due soon",
            "course": "Physics",
            "description": "",
            "deadline": (today + timedelta(days=2)).isoformat(),  # due soon
            "priority": "medium",
        },
        {
            "title": "Low priority far future",
            "course": "History",
            "description": "",
            "deadline": (today + timedelta(days=30)).isoformat(),
            "priority": "low",
        },
        {
            "title": "Already completed task",
            "course": "Maths",
            "description": "",
            "deadline": (today + timedelta(days=5)).isoformat(),
            "priority": "medium",
        },
    ]

    for t in tasks:
        task_id = db_module.create_task(t, db_path)
        # Mark the last task as done (create_task always inserts done=0,
        # so we use toggle_done to flip it for the "completed" test task).
        if t["title"] == "Already completed task":
            db_module.toggle_done(task_id, db_path)

    return db_path


@pytest.fixture
def flask_client(db_path):
    """Flask test client wired to a temporary database."""
    import app as app_module
    flask_app = app_module.create_app(db_path=db_path)
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Tests: build_task_context
# ---------------------------------------------------------------------------

class TestBuildTaskContext:
    def test_empty_task_list(self):
        """build_task_context with no tasks returns the empty-state message."""
        from agent import build_task_context
        result = build_task_context([])
        assert "no tasks" in result.lower()

    def test_context_contains_task_info(self, db_with_tasks):
        """Context should include task titles, courses, and priorities."""
        import database as db_module
        from agent import build_task_context

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        context = build_task_context(tasks)

        assert "High priority overdue task" in context
        assert "Maths" in context
        assert "HIGH" in context
        assert "OVERDUE" in context

    def test_done_tasks_labelled(self, db_with_tasks):
        """Completed tasks should be labelled 'done' in the context string."""
        import database as db_module
        from agent import build_task_context

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        context = build_task_context(tasks)
        # The completed task should appear as "status: done" in the context
        assert "status: done" in context.lower()


# ---------------------------------------------------------------------------
# Tests: rule_based_answer — priority intent
# ---------------------------------------------------------------------------

class TestRuleBasedPriority:
    def test_priority_answer_ranks_overdue_first(self, db_with_tasks):
        """The priority answer should mention the overdue task before others."""
        import database as db_module
        from agent import rule_based_answer

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        answer = rule_based_answer("What should I work on first?", tasks)

        assert "High priority overdue task" in answer
        # Overdue task should appear earlier in the answer than the far-future one
        pos_overdue = answer.index("High priority overdue task")
        pos_future  = answer.index("Low priority far future")
        assert pos_overdue < pos_future

    def test_priority_answer_no_pending_tasks(self):
        """With only completed tasks the answer should be encouraging."""
        from agent import rule_based_answer

        done_tasks = [
            {"title": "Done", "course": "X", "deadline": "2026-12-01",
             "priority": "low", "done": 1},
        ]
        answer = rule_based_answer("What should I work on first?", done_tasks)
        assert "no pending" in answer.lower() or "great" in answer.lower() \
               or "break" in answer.lower()

    def test_priority_answer_empty_list(self):
        """With no tasks at all the fallback should still return a string."""
        from agent import rule_based_answer
        answer = rule_based_answer("What should I work on first?", [])
        assert isinstance(answer, str)
        assert len(answer) > 0


# ---------------------------------------------------------------------------
# Tests: rule_based_answer — schedule intent
# ---------------------------------------------------------------------------

class TestRuleBasedSchedule:
    def test_schedule_contains_day_names(self, db_with_tasks):
        """A schedule answer should contain day-of-week names."""
        import database as db_module
        from agent import rule_based_answer

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        answer = rule_based_answer("Make a study schedule for this week", tasks)

        # At least one weekday name should appear
        days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
        assert any(day in answer for day in days)

    def test_schedule_empty_tasks(self):
        """Schedule with no tasks should prompt the user to add tasks."""
        from agent import rule_based_answer
        answer = rule_based_answer("Give me a weekly schedule", [])
        assert "no pending" in answer.lower() or "add" in answer.lower()


# ---------------------------------------------------------------------------
# Tests: rule_based_answer — general / summary intent
# ---------------------------------------------------------------------------

class TestRuleBasedSummary:
    def test_summary_counts(self, db_with_tasks):
        """General query should mention total and pending counts."""
        import database as db_module
        from agent import rule_based_answer

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        answer = rule_based_answer("How are my tasks looking?", tasks)

        assert "Total tasks" in answer or "total" in answer.lower()
        assert "Pending" in answer or "pending" in answer.lower()


# ---------------------------------------------------------------------------
# Tests: run_agent (integration, fallback mode)
# ---------------------------------------------------------------------------

class TestRunAgent:
    def test_run_agent_returns_answer(self, db_with_tasks):
        """run_agent should always return a dict with 'answer' and 'mode'."""
        from agent import run_agent

        result = run_agent("What should I study first?", db_path=db_with_tasks)

        assert isinstance(result, dict)
        assert "answer" in result
        assert "mode" in result
        assert result["mode"] == "fallback"  # no API key in tests
        assert len(result["answer"]) > 0

    def test_run_agent_empty_question(self, db_with_tasks):
        """An empty question should return a prompt-for-input message."""
        from agent import run_agent

        result = run_agent("", db_path=db_with_tasks)
        assert "answer" in result
        assert "question" in result["answer"].lower() \
               or "ask" in result["answer"].lower()

    def test_run_agent_schedule_query(self, db_with_tasks):
        """A schedule query should include day-of-week names in the answer."""
        from agent import rule_based_answer
        import database as db_module

        tasks = db_module.get_all_tasks(db_path=db_with_tasks)
        answer = rule_based_answer("plan my week", tasks)
        days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
        assert any(d in answer for d in days)


# ---------------------------------------------------------------------------
# Tests: /api/agent Flask endpoint
# ---------------------------------------------------------------------------

class TestAgentEndpoint:
    def test_endpoint_returns_200(self, flask_client):
        """POST /api/agent with a valid question should return 200."""
        resp = flask_client.post(
            "/api/agent",
            json={"question": "What should I work on first?"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "answer" in data
        assert "mode" in data

    def test_endpoint_empty_question_returns_400(self, flask_client):
        """POST /api/agent with no question should return 400."""
        resp = flask_client.post("/api/agent", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_endpoint_non_json_returns_400(self, flask_client):
        """POST /api/agent with no body should return 400."""
        resp = flask_client.post(
            "/api/agent",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_endpoint_schedule_response(self, flask_client):
        """A schedule question should return a non-empty answer."""
        resp = flask_client.post(
            "/api/agent",
            json={"question": "Give me a study schedule for this week"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data.get("answer", "")) > 10
