# J.A.R.V.I.S.

J.A.R.V.I.S. is a desktop voice AI assistant built with Python, PyQt5, Anthropic Claude, and ElevenLabs. It presents a cinematic HUD and routes natural language into structured JSON commands for apps, files, system control, browser automation, reminders, code execution, and voice feedback.

**Full capability list (kept in sync with the code):** see [`context.md`](context.md) — section **“What JARVIS can do (capability list)”**.

---

## Features (summary)

### Core loop
- **Claude** reads `CLAUDE.md` (or `Claude.md`) as the system prompt and returns **one JSON command** per request: intent, action, parameters, TTS line, HUD label, and whether **user confirmation** is required.
- **`@tags`** (e.g. `@browser`, `@files`, `@system`) force intent routing; see the brain prompt for the map.
- **`core/executor.py`** dispatches to OS handlers; maintains registries for **confirmation** and **dangerous** workflow steps.

### Voice and HUD
- PyQt5 HUD: **Dashboard** (transcript, arc reactor, telemetry), **Voice**, **Automation**, **History**, **Settings**.
- **Google STT** (mic) and **ElevenLabs TTS** (with local fallback); **typewriter** transcript aligned with audio; **Thinking…** placeholder while work is in flight.
- **Command palette** (**Ctrl+K**), **Quick Settings** (mic/TTS mute, session **auto-confirm**), **System Status** popover.
- **Inline confirmation** in the transcript (cyan **CONFIRM** / red **CANCEL**) for both model-driven (`requires_confirmation`) and **executor** prompts (`needs_confirmation`).

### What you can ask it to do (by area)
- **Apps:** open browser, VS Code, terminal, file manager, Spotify, generic apps, URLs; close apps; **force quit** (with confirmation).
- **Web:** Google, YouTube, GitHub, Stack Overflow, Wikipedia, generic search.
- **Input:** type text, paste, hotkeys; mouse move, click, scroll, drag.
- **System:** volume (incl. absolute level), screenshot (optional **region**), lock; **sleep**, **shut down**, **restart** — each **confirmed**; **sleep** vs **shut down** are distinct actions in the prompt and executor.
- **Files:** create (with **executor confirmation** showing **file + folder** path; creates parent folders on confirm), read, delete (**confirmed**), move, copy, list, search.
- **Code:** run Python, shell commands (`shell=False`), scripts, **git** and **npm**-style invocations.
- **Browser (Playwright):** persistent Chrome — navigate, click, fill forms, read page, extract, screenshots, new/close tab.
- **Screen:** OCR via Tesseract (`read_screen`).
- **Reminders:** set, cancel, list (timer-based).
- **Meta:** time, date, system status (CPU/memory), conversational / cache-backed answers; additional `jarvis_meta` actions are defined in **`CLAUDE.md`**.
- **Automation:** named workflows in `data/workflows.json` — list, run, create, remove (**confirmed**), rename; dangerous steps are restricted when saving workflows.

---

## Project structure

```text
.
├── main.py                 # PyQt application entry point
├── CLAUDE.md               # System prompt and JSON routing (try both cases on Windows)
├── core/                   # Brain, executor, voice, browser, automation, computer control
├── ui/                     # HUD, command palette, popovers, components (transcript / confirm card)
├── config/                 # Runtime configuration
├── data/                   # Mock history, intents, workflows.json
├── assets/                 # Logo and reference assets
├── fonts/                  # Bundled UI fonts
├── context.md              # Handoff doc + full capability list
└── pyproject.toml          # Dependencies and metadata
```

---

## Requirements

- **Windows** is the primary target for this version.
- Python matching **`pyproject.toml`** (e.g. 3.11+).
- **`uv`** recommended for dependency management.
- **Anthropic API key** for Claude intent routing.
- **ElevenLabs API key** for premium TTS (optional fallback: local TTS).
- Optional **Vapi** API key for assistant platform sync.
- **Playwright + Chrome** for browser automation; **Tesseract** on `PATH` for OCR.

---

## Setup

Clone the repository and install dependencies:

```powershell
uv sync
```

Create a `.env` file from the example:

```powershell
copy .env.example .env
```

Fill in the keys you want to use:

```env
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
VAPI_API_KEY=...
CLAUDE_MODEL=claude-sonnet-4-6
WAKE_WORD=jarvis
DEBUG=false
```

Run the app:

```powershell
uv run python main.py
```

---

## How it works

User input goes to **`core/brain.py`**, which loads **`CLAUDE.md`** and asks Claude for a single valid JSON command. That object is passed to **`core/executor.py`** → **`dispatch()`**, which runs the matching handler (apps, files, shell, browser, etc.).

Two confirmation paths exist: **before execute** (Claude `requires_confirmation` + executor registry) and **during execute** (`request_confirmation` → user confirms in UI → deferred callback runs). **Create file** uses the second path so the **full path** is shown on the card.

Voice output uses **`core/voice.py`** (ElevenLabs when configured). The dashboard transcript uses a **Thinking…** line, then typewriter output when audio is ready.

---

## Safety notes

JARVIS can run commands that affect the local machine: files, processes, shell, power state, and browser. Treat it as a **trusted local** assistant.

- Keep secrets in **`.env`**, not in git.
- Review **confirmation** behaviour before enabling **auto-confirm** or broad automation.
- Prefer stricter policies for **shell** and **code** execution if exposed to untrusted input.

---

## Status

Early desktop build: HUD and command pipeline are functional. Hardening, tests, and safety policy can be tightened for production use. See **`context.md`** for architecture detail, audit notes, and the full feature matrix.
