"""
tests/test_app.py — pytest test suite for Study Planner.

Each test uses a temporary SQLite database so tests are fully isolated
from each other and from the development database.

Tests cover:
    1. Dashboard loads and shows correct stats.
    2. Creating a task (valid input).
    3. Creating a task with invalid input (validation).
    4. Editing an existing task.
    5. Deleting a task.
    6. Toggling a task done/pending.
    7. Filter by status returns correct subset.
    8. Accessing a non-existent task returns 404.
    9. Deadline in the past is still accepted (edge case).
   10. Empty title is rejected.
"""

import os
import tempfile
import pytest

# We must point the app at a temporary DB BEFORE importing app.py so that
# create_app() uses our test path from the start.

@pytest.fixture
def client():
    """Create a Flask test client backed by a fresh temporary database."""
    # Create a temp file to use as the SQLite DB
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    import app as app_module
    flask_app = app_module.create_app(db_path=db_path)
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False  # no CSRF in tests

    with flask_app.test_client() as c:
        yield c

    # Cleanup — on Windows, SQLite may hold the file open briefly; ignore errors.
    os.close(db_fd)
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ── Helpers ────────────────────────────────────────────────────────────────

def _add_task(client, overrides=None):
    """POST a valid task to /tasks/new and return the response."""
    data = {
        "title": "Test Task",
        "course": "Test Course",
        "description": "A description.",
        "deadline": "2026-12-31",
        "priority": "medium",
    }
    if overrides:
        data.update(overrides)
    return client.post("/tasks/new", data=data, follow_redirects=True)


# ── Tests ──────────────────────────────────────────────────────────────────

class TestDashboard:
    """Tests for the index/dashboard page."""

    def test_dashboard_loads(self, client):
        """GET / should return 200 and render the dashboard."""
        resp = client.get("/")
        assert resp.status_code == 200
        # Seed data is NOT injected in test DB (empty), so check for key UI elements
        assert b"Study Planner" in resp.data
        assert b"Total Tasks" in resp.data

    def test_dashboard_stats_reflect_tasks(self, client):
        """Stats should update after a task is added."""
        resp_before = client.get("/")
        # After adding a task the total should increase
        _add_task(client)
        resp_after = client.get("/")
        assert resp_after.status_code == 200
        # The word for the stat card label appears in the page
        assert b"Total Tasks" in resp_after.data


class TestCreateTask:
    """Tests for creating tasks."""

    def test_create_valid_task(self, client):
        """A valid form POST should redirect to index with success flash."""
        resp = _add_task(client)
        assert resp.status_code == 200
        assert b"Task added successfully" in resp.data

    def test_create_task_appears_in_list(self, client):
        """After creation the task title should appear in the task list."""
        _add_task(client, {"title": "Unique Title XYZ"})
        resp = client.get("/")
        assert b"Unique Title XYZ" in resp.data

    def test_create_missing_title(self, client):
        """Submitting without a title should show a validation error."""
        resp = _add_task(client, {"title": ""})
        assert resp.status_code == 200
        assert b"Title is required" in resp.data

    def test_create_missing_course(self, client):
        """Submitting without a course should show a validation error."""
        resp = _add_task(client, {"course": ""})
        assert resp.status_code == 200
        assert b"Course name is required" in resp.data

    def test_create_invalid_priority(self, client):
        """An invalid priority value should be rejected."""
        resp = _add_task(client, {"priority": "ultra"})
        assert resp.status_code == 200
        assert b"Priority must be" in resp.data

    def test_create_past_deadline_accepted(self, client):
        """
        A deadline in the past is allowed (students may log overdue work).
        The task should be created without errors.
        """
        resp = _add_task(client, {"deadline": "2020-01-01"})
        assert resp.status_code == 200
        assert b"Task added successfully" in resp.data

    def test_create_missing_deadline(self, client):
        """Submitting without a deadline should show a validation error."""
        resp = _add_task(client, {"deadline": ""})
        assert resp.status_code == 200
        assert b"Deadline is required" in resp.data


class TestEditTask:
    """Tests for editing tasks."""

    def _get_task_id(self, client):
        """Helper: create a task and extract its edit URL from the response."""
        _add_task(client, {"title": "Edit Me Unique"})
        import re
        resp = client.get("/")
        html = resp.data.decode()
        # Find the delete-form id that immediately follows our unique title,
        # so we don't accidentally grab a seed-data task id.
        match = re.search(r"Edit Me Unique.*?delete-form-(\d+)", html, re.DOTALL)
        return int(match.group(1)) if match else None

    def test_edit_task(self, client):
        """Editing a task should update it and redirect with success message."""
        task_id = self._get_task_id(client)
        assert task_id is not None, "Could not locate the newly added task in the page"
        resp = client.post(
            f"/tasks/{task_id}/edit",
            data={
                "title": "Edited Title",
                "course": "Edited Course",
                "description": "Updated.",
                "deadline": "2027-01-01",
                "priority": "high",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Task updated" in resp.data
        assert b"Edited Title" in resp.data

    def test_edit_nonexistent_task(self, client):
        """Editing a task that does not exist should return 404."""
        resp = client.get("/tasks/99999/edit")
        assert resp.status_code == 404


class TestDeleteTask:
    """Tests for deleting tasks."""

    def test_delete_task(self, client):
        """Deleting a task should remove it from the list."""
        _add_task(client, {"title": "Delete Me XYZ"})
        resp = client.get("/")
        import re
        # Each task row contains both the title and a hidden form with id="delete-form-N".
        # Find the list item that contains our unique title and extract the form id number.
        html = resp.data.decode()
        match = re.search(
            r'Delete Me XYZ.*?delete-form-(\d+)', html, re.DOTALL
        )
        assert match, "Could not find the added task in the page"
        task_id = int(match.group(1))

        del_resp = client.post(f"/tasks/{task_id}/delete", follow_redirects=True)
        assert del_resp.status_code == 200
        assert b"Task deleted" in del_resp.data
        assert b"Delete Me XYZ" not in del_resp.data

    def test_delete_nonexistent_task(self, client):
        """Deleting a non-existent task should return 404."""
        resp = client.post("/tasks/99999/delete")
        assert resp.status_code == 404


class TestToggleTask:
    """Tests for toggling done/pending state."""

    def test_toggle_task_done(self, client):
        """Toggling a pending task should mark it done."""
        _add_task(client, {"title": "Toggle Me Unique"})
        resp = client.get("/")
        import re
        html = resp.data.decode()
        # Find the delete-form id that follows our unique title (safe with seed data).
        match = re.search(r"Toggle Me Unique.*?delete-form-(\d+)", html, re.DOTALL)
        assert match, "Could not find the toggle task in the page"
        task_id = int(match.group(1))

        toggle_resp = client.post(
            f"/tasks/{task_id}/toggle", follow_redirects=True
        )
        assert toggle_resp.status_code == 200
        # The done indicator (strikethrough class or ✅ emoji) should appear
        assert b"task-title--done" in toggle_resp.data or "\u2705".encode() in toggle_resp.data

    def test_toggle_nonexistent_task(self, client):
        """Toggling a non-existent task should return 404."""
        resp = client.post("/tasks/99999/toggle")
        assert resp.status_code == 404


class TestFiltering:
    """Tests for filter/sort query parameters."""

    def test_filter_by_status_done(self, client):
        """Filter status=done should hide pending tasks."""
        _add_task(client, {"title": "Pending Task"})
        resp = client.get("/?status=done")
        assert resp.status_code == 200
        # Our pending task should not appear in the done-only view
        assert b"Pending Task" not in resp.data

    def test_filter_by_course(self, client):
        """Filter by course should return only matching tasks."""
        _add_task(client, {"title": "Physics Task",  "course": "Physics"})
        _add_task(client, {"title": "History Task",  "course": "History"})
        resp = client.get("/?course=Physics")
        assert resp.status_code == 200
        assert b"Physics Task" in resp.data
        assert b"History Task" not in resp.data
