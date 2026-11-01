# 📚 Study Planner

A clean, responsive web app for university students to manage coursework tasks,
track deadlines, and monitor study progress — built with Python/Flask and vanilla
HTML/CSS/JavaScript.

---

## Features

| Feature | Detail |
|---|---|
| **Task CRUD** | Add, edit, delete, and mark tasks as done/pending |
| **Dashboard** | Total, completed, overdue, and due-in-7-days counters |
| **Course progress** | Per-course progress bar showing % tasks completed |
| **Filter & sort** | Filter by course, priority, status; sort by deadline/priority/course/title |
| **Visual indicators** | Overdue → red border, due soon → orange border, done → strikethrough |
| **Input validation** | Server-side validation with friendly flash error messages |
| **Seed data** | Six sample tasks are inserted on the first run so the app isn't empty |
| **🤖 Study Assistant** | AI-powered chat panel — ask questions about your tasks and get a study schedule |

---

## 🤖 Study Assistant

The Study Assistant is an AI chat panel embedded in the dashboard. It reads your
real task data from the database and answers questions like:

- *"What should I work on first today?"*
- *"Make a study schedule for this week."*
- *"How many tasks are overdue?"*
- *"Which course needs the most attention?"*

### Two modes

| Mode | When it activates | What it does |
|---|---|---|
| **AI (LLM)** | `OPENAI_API_KEY` env var is set | Calls `gpt-4o-mini` (or the model you configure) with your task list as context |
| **Rule-based fallback** | No API key set | Ranks tasks by deadline + priority and generates a schedule / summary locally — no internet required |

The app **always works** regardless of whether an API key is present.

### Setting the API key (PowerShell)

```powershell
# Current session only
$env:OPENAI_API_KEY = "sk-..."

# Then start the app in the same terminal
python app.py
```

To make it permanent, add it to your PowerShell profile or Windows environment variables.

### Overriding the model

```powershell
$env:STUDY_PLANNER_LLM_MODEL = "gpt-4o"
```

Defaults to `gpt-4o-mini` if not set.

---

## Project Structure

```
study-planner/
├── app.py              # Flask entry point, all routes (including /api/agent)
├── agent.py            # Study Assistant: LLM caller + rule-based fallback
├── database.py         # SQLite schema, CRUD helpers, seed data, stats
├── templates/
│   ├── base.html       # Shared layout (nav, flash messages, footer)
│   ├── index.html      # Dashboard + task list + Study Assistant chat panel
│   ├── task_form.html  # Add / Edit task form
│   └── 404.html        # Custom 404 page
├── static/
│   ├── css/style.css   # Responsive CSS, colour-coded states, chat UI
│   └── js/app.js       # Confirm-delete, auto-submit filters, chat fetch logic
├── tests/
│   ├── test_app.py     # pytest: CRUD, validation, dashboard, edge cases (14 tests)
│   └── test_agent.py   # pytest: agent logic, fallback answers, API endpoint (11 tests)
├── requirements.txt
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.11+
- pip

### Steps

```powershell
# 1. Enter the project directory
cd study-planner

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

> **Note:** The `openai` package is **not** required. The app runs fully offline
> with the rule-based fallback. If you want LLM responses, install it manually:
> ```powershell
> pip install openai==1.35.0
> ```

---

## Running the App

```powershell
# (Optional) set your OpenAI API key for AI-powered responses
$env:OPENAI_API_KEY = "sk-..."

python app.py
```

Open **http://127.0.0.1:5000** in your browser.

Six sample tasks are seeded automatically on the first launch.

---

## Running the Tests

```powershell
pytest tests/ -v
```

All tests use temporary databases — no API key needed, no side effects on your
development database.

---

## Screenshots

> _Add screenshots here after first run._
>
> Suggested screenshots:
> 1. Dashboard with stats cards and progress bars
> 2. Task list with overdue (red) and due-soon (orange) indicators
> 3. Add Task form
> 4. Study Assistant chat panel in action

---

## Architecture Notes

- **`database.py`** owns all SQLite interactions; neither `app.py` nor `agent.py` calls `sqlite3` directly.
- **`agent.py`** uses only stdlib (`urllib`, `json`, `datetime`) — no extra runtime dependency for the fallback path.
- The LLM is called via raw `urllib.request` so the `openai` SDK is optional.
- The app factory pattern (`create_app(db_path=...)`) keeps both test suites isolated without monkey-patching.
- Server-side filtering/sorting via SQL keeps the frontend simple.

---

## Ideas for Future Improvements

1. **Conversation memory** — store the chat history in the session or a `chat_messages` table so the assistant remembers earlier messages in the conversation.
2. **Pomodoro timer** — add a built-in focus timer on the task detail view so students can time-box their study sessions.
3. **Calendar export** — generate an `.ics` file from the task list so students can import their deadlines into Google Calendar or Outlook.

---

## License

MIT — free to use and modify.
