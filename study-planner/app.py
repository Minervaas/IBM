"""
app.py — Flask entry point and route definitions for Study Planner.

Routes
------
GET  /                          Dashboard + task list (filter/sort via query params)
GET  /tasks/new                 Render the add-task form
POST /tasks/new                 Create a new task
GET  /tasks/<id>/edit           Render the edit-task form pre-filled
POST /tasks/<id>/edit           Save edits to an existing task
POST /tasks/<id>/delete         Delete a task
POST /tasks/<id>/toggle         Toggle the done/pending state
POST /api/agent                 Study Assistant — accepts {question} JSON, returns {answer, mode, model}
"""

import os
from datetime import date, timedelta
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    jsonify,
)
import database as db
import agent as agent_module

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(db_path: str | None = None) -> Flask:
    """
    Application factory — makes it straightforward to swap databases in tests.
    """
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-in-prod")

    # Allow tests to inject a custom database path
    _db_path = db_path or db.DB_PATH

    # Initialise schema and seed on first run
    db.init_db(_db_path)
    db.seed_db(_db_path)

    # ------------------------------------------------------------------
    # Custom Jinja2 filters
    # ------------------------------------------------------------------

    @app.template_filter("add_days")
    def add_days_filter(date_str: str, days: int) -> str:
        """
        Jinja2 filter: add *days* to an ISO-8601 date string and return a new
        ISO-8601 date string.  Used in index.html to compute the due-soon window.
        Example: {{ today | add_days(7) }}
        """
        try:
            d = date.fromisoformat(date_str)
            return (d + timedelta(days=days)).isoformat()
        except (ValueError, TypeError):
            return date_str

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    def _validate_task_form(form) -> list[str]:
        """
        Validate the task form fields.  Returns a (possibly empty) list of
        human-readable error messages.
        """
        errors = []
        title = form.get("title", "").strip()
        course = form.get("course", "").strip()
        deadline = form.get("deadline", "").strip()
        priority = form.get("priority", "").strip()

        if not title:
            errors.append("Title is required.")
        elif len(title) > 200:
            errors.append("Title must be 200 characters or fewer.")

        if not course:
            errors.append("Course name is required.")
        elif len(course) > 100:
            errors.append("Course name must be 100 characters or fewer.")

        if not deadline:
            errors.append("Deadline is required.")
        else:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                errors.append("Deadline must be a valid date (YYYY-MM-DD).")

        if priority not in db.VALID_PRIORITIES:
            errors.append("Priority must be low, medium, or high.")

        return errors

    # ------------------------------------------------------------------
    # Dashboard / task list
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        course_filter = request.args.get("course", "").strip()
        priority_filter = request.args.get("priority", "").strip()
        status_filter = request.args.get("status", "").strip()
        sort_by = request.args.get("sort", "deadline").strip()

        tasks = db.get_all_tasks(
            db_path=_db_path,
            course=course_filter,
            priority=priority_filter,
            status=status_filter,
            sort=sort_by,
        )
        stats = db.get_stats(_db_path)
        courses = db.get_distinct_courses(_db_path)
        today = date.today().isoformat()

        return render_template(
            "index.html",
            tasks=tasks,
            stats=stats,
            courses=courses,
            today=today,
            course_filter=course_filter,
            priority_filter=priority_filter,
            status_filter=status_filter,
            sort_by=sort_by,
        )

    # ------------------------------------------------------------------
    # Create task
    # ------------------------------------------------------------------

    @app.route("/tasks/new", methods=["GET", "POST"])
    def new_task():
        if request.method == "POST":
            errors = _validate_task_form(request.form)
            if errors:
                for err in errors:
                    flash(err, "error")
                # Re-render the form with the submitted values so the user
                # doesn't lose their input.
                return render_template(
                    "task_form.html",
                    task=request.form,
                    action_url=url_for("new_task"),
                    form_title="Add New Task",
                )

            db.create_task(
                {
                    "title": request.form["title"].strip(),
                    "course": request.form["course"].strip(),
                    "description": request.form.get("description", "").strip(),
                    "deadline": request.form["deadline"].strip(),
                    "priority": request.form["priority"].strip(),
                },
                _db_path,
            )
            flash("Task added successfully.", "success")
            return redirect(url_for("index"))

        return render_template(
            "task_form.html",
            task=None,
            action_url=url_for("new_task"),
            form_title="Add New Task",
        )

    # ------------------------------------------------------------------
    # Edit task
    # ------------------------------------------------------------------

    @app.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
    def edit_task(task_id: int):
        task = db.get_task(task_id, _db_path)
        if task is None:
            abort(404)

        if request.method == "POST":
            errors = _validate_task_form(request.form)
            if errors:
                for err in errors:
                    flash(err, "error")
                # Merge submitted form data with the original task so the
                # template can render both id and the edited values.
                merged = dict(task)
                merged.update(request.form)
                return render_template(
                    "task_form.html",
                    task=merged,
                    action_url=url_for("edit_task", task_id=task_id),
                    form_title="Edit Task",
                )

            updated = db.update_task(
                task_id,
                {
                    "title": request.form["title"].strip(),
                    "course": request.form["course"].strip(),
                    "description": request.form.get("description", "").strip(),
                    "deadline": request.form["deadline"].strip(),
                    "priority": request.form["priority"].strip(),
                },
                _db_path,
            )
            if not updated:
                abort(404)

            flash("Task updated.", "success")
            return redirect(url_for("index"))

        return render_template(
            "task_form.html",
            task=task,
            action_url=url_for("edit_task", task_id=task_id),
            form_title="Edit Task",
        )

    # ------------------------------------------------------------------
    # Delete task
    # ------------------------------------------------------------------

    @app.route("/tasks/<int:task_id>/delete", methods=["POST"])
    def delete_task(task_id: int):
        deleted = db.delete_task(task_id, _db_path)
        if not deleted:
            abort(404)
        flash("Task deleted.", "success")
        return redirect(url_for("index"))

    # ------------------------------------------------------------------
    # Toggle done/pending
    # ------------------------------------------------------------------

    @app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
    def toggle_task(task_id: int):
        found = db.toggle_done(task_id, _db_path)
        if not found:
            abort(404)
        return redirect(request.referrer or url_for("index"))

    # ------------------------------------------------------------------
    # Study Assistant agent endpoint
    # ------------------------------------------------------------------

    @app.route("/api/agent", methods=["POST"])
    def agent_chat():
        """
        POST /api/agent
        Request body (JSON): {"question": "What should I work on first?"}
        Response (JSON):     {"answer": "...", "mode": "llm|fallback", "model": "..."}

        Returns HTTP 400 when the request body is missing or malformed.
        """
        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()

        if not question:
            return jsonify({"error": "Field 'question' is required."}), 400

        result = agent_module.run_agent(question, db_path=_db_path)
        return jsonify(result)

    # ------------------------------------------------------------------
    # 404 error handler
    # ------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
