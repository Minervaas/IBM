/**
 * app.js — Study Planner client-side enhancements.
 *
 * Responsibilities:
 *   1. Confirm-before-delete: intercept delete buttons and show a native
 *      confirm dialog before submitting the hidden DELETE form.
 *   2. Auto-submit filter form when any <select> changes (saves a click).
 *   3. Populate the course <datalist> for the task-form autocomplete by
 *      collecting existing course names from the task list badges.
 *   4. Client-side deadline warning: if the chosen deadline is in the past,
 *      show an inline warning (but still allow submission — past deadlines
 *      are valid for tracking purposes).
 *   5. Flash message auto-dismiss after 5 seconds.
 */

"use strict";

/* ── 1. Confirm-before-delete ──────────────────────────── */
document.addEventListener("click", function (event) {
  const btn = event.target.closest(".js-confirm-delete");
  if (!btn) return;

  const confirmed = window.confirm(
    "Are you sure you want to delete this task? This cannot be undone."
  );
  if (!confirmed) {
    event.preventDefault();
    return;
  }

  // Submit the associated hidden form
  const formId = btn.dataset.form;
  const form = document.getElementById(formId);
  if (form) form.submit();
});

/* ── 2. Auto-submit filter form on select change ────────── */
(function () {
  const filterForm = document.getElementById("filterForm");
  if (!filterForm) return;

  filterForm.querySelectorAll("select").forEach(function (sel) {
    sel.addEventListener("change", function () {
      filterForm.submit();
    });
  });
})();

/* ── 3. Datalist autocomplete for the course field ──────── */
(function () {
  const datalist = document.getElementById("course-suggestions");
  if (!datalist) return;

  // Collect unique course names from the task list on the index page
  // (not present on the form page itself, so nothing happens if absent)
  const courses = new Set();
  document.querySelectorAll(".badge--course").forEach(function (el) {
    const name = el.textContent.trim();
    if (name) courses.add(name);
  });

  courses.forEach(function (name) {
    const option = document.createElement("option");
    option.value = name;
    datalist.appendChild(option);
  });
})();

/* ── 4. Client-side past-deadline warning ───────────────── */
(function () {
  const deadlineInput = document.getElementById("deadline");
  if (!deadlineInput) return;

  // Create a small warning element we can show/hide
  const warning = document.createElement("span");
  warning.className = "form-hint";
  warning.style.color = "#f59e0b";
  warning.style.fontWeight = "600";
  warning.textContent = "⚠ This date is in the past.";
  warning.hidden = true;
  deadlineInput.parentNode.appendChild(warning);

  function checkDeadline() {
    const val = deadlineInput.value;
    if (!val) { warning.hidden = true; return; }
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const chosen = new Date(val + "T00:00:00");
    warning.hidden = chosen >= today;
  }

  deadlineInput.addEventListener("change", checkDeadline);
  deadlineInput.addEventListener("input", checkDeadline);
  // Run once on page load (for the edit form pre-filled with a past date)
  checkDeadline();
})();

/* ── 5. Auto-dismiss flash messages ─────────────────────── */
(function () {
  const flashes = document.querySelectorAll(".flash");
  if (!flashes.length) return;

  setTimeout(function () {
    flashes.forEach(function (el) {
      el.style.transition = "opacity .5s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 500);
    });
  }, 5000); // dismiss after 5 s
})();

/* ── 6. Study Assistant chat panel ──────────────────────── */
(function () {
  "use strict";

  const form        = document.getElementById("chatForm");
  const input       = document.getElementById("chatInput");
  const history     = document.getElementById("chatHistory");
  const sendBtn     = document.getElementById("chatSendBtn");
  const modeBadge   = document.getElementById("chatModeBadge");
  const suggestions = document.getElementById("chatSuggestions");

  if (!form) return; // chat panel not present on this page

  // ── Helpers ──────────────────────────────────────────────

  /** Format HH:MM timestamp. */
  function _now() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  /**
   * Append a message bubble to the history pane.
   * role: "user" | "agent"
   * Returns the bubble element so the caller can update it (e.g. loading →answer).
   */
  function appendMessage(text, role, isLoading) {
    const wrapper = document.createElement("div");
    wrapper.className = "chat-msg chat-msg--" + role +
      (isLoading ? " chat-msg--loading" : "");

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = text;

    const ts = document.createElement("span");
    ts.className = "chat-timestamp";
    ts.textContent = _now();

    wrapper.appendChild(bubble);
    wrapper.appendChild(ts);
    history.appendChild(wrapper);
    // Scroll to bottom
    history.scrollTop = history.scrollHeight;
    return bubble;
  }

  /** Update the mode badge after receiving a response. */
  function updateModeBadge(mode, model) {
    if (!modeBadge) return;
    if (mode === "llm") {
      modeBadge.textContent = "AI · " + (model || "LLM");
      modeBadge.dataset.mode = "llm";
    } else {
      modeBadge.textContent = "Rule-based";
      modeBadge.dataset.mode = "fallback";
    }
  }

  /** Set loading state on the send button. */
  function setLoading(loading) {
    if (sendBtn) {
      sendBtn.disabled = loading;
      sendBtn.textContent = loading ? "Thinking…" : "Send";
    }
    if (input) input.disabled = loading;
  }

  // ── Send a message ────────────────────────────────────────

  async function sendMessage(question) {
    question = (question || "").trim();
    if (!question) return;

    // Show user bubble
    appendMessage(question, "user");
    input.value = "";

    // Hide suggestion chips after first use
    if (suggestions) suggestions.style.display = "none";

    // Show loading placeholder
    const loadingBubble = appendMessage("Thinking…", "agent", true);
    setLoading(true);

    try {
      const resp = await fetch("/api/agent", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ question: question }),
      });

      const data = await resp.json();

      if (!resp.ok) {
        loadingBubble.textContent =
          "⚠ " + (data.error || "Something went wrong. Please try again.");
        loadingBubble.parentElement.classList.remove("chat-msg--loading");
      } else {
        loadingBubble.textContent = data.answer || "(no response)";
        loadingBubble.parentElement.classList.remove("chat-msg--loading");
        updateModeBadge(data.mode, data.model);
      }
    } catch (err) {
      loadingBubble.textContent =
        "⚠ Network error — please check your connection and try again.";
      loadingBubble.parentElement.classList.remove("chat-msg--loading");
    } finally {
      setLoading(false);
      history.scrollTop = history.scrollHeight;
      input.focus();
    }
  }

  // ── Event listeners ───────────────────────────────────────

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    sendMessage(input.value);
  });

  // Suggestion chips
  if (suggestions) {
    suggestions.addEventListener("click", function (e) {
      const chip = e.target.closest(".suggestion-chip");
      if (!chip) return;
      sendMessage(chip.dataset.prompt);
    });
  }
})();
