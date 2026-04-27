# J.A.R.V.I.S.

J.A.R.V.I.S. is a desktop voice AI assistant built with Python, PyQt5, Anthropic Claude, and ElevenLabs. It presents a cinematic HUD and routes natural language into structured JSON commands for apps, files, system control, browser automation, reminders, code execution, and voice feedback.

**Full capability list (kept in sync with the code):** see [`context.md`](context.md) — section **"What JARVIS can do (capability list)"**.

---

## Features (summary)

### Core loop
- **Claude** reads `CLAUDE.md` as the system prompt and returns **one JSON command** per request: intent, action, parameters, TTS line, HUD label, and whether **user confirmation** is required.
- **`@tags`** (e.g. `@browser`, `@files`, `@system`) force intent routing; see the brain prompt for the map.
- **`core/executor.py`** dispatches to OS handlers; maintains registries for **confirmation** and **dangerous** workflow steps.

### Voice pipeline
- **`core/audio_pipeline.py`** — self-contained STT/TTS engines: `AudioCapture`, `SttEngine`, `TtsEngine`.
  - **Dynamic noise calibration** before each capture — samples ambient RMS and adapts the VAD threshold in real time, compensating for Windows AGC gain changes after TTS playback.
  - Configurable **noise gate** (4× multiplier when on, 2× off) and **mic sensitivity**.
  - Configurable **mic input device** — select any system input from Settings (`-1` = system default).
- **`core/voice.py`** — thin facade over `audio_pipeline.py`; public API unchanged from callers' perspective.
- **Google STT** (sounddevice mic capture → SpeechRecognition) and **ElevenLabs TTS** (streaming + pyttsx3 fallback).
- **Typewriter** transcript animation aligned with audio; **Thinking…** placeholder while work is in flight.

### HUD and UI
- PyQt5 HUD: **Dashboard** (transcript, arc reactor, telemetry), **Voice**, **Automation**, **History**, **Settings**.
- **Arc reactor orb**: dashed ring, cardinal triangle markers, 12-segment armor panel ring — reference-faithful cinematic styling.
- Near-black `#080A0A` background across all surfaces.
- **Command palette** (**Ctrl+K**), **Quick Settings** (mic/TTS mute, session **auto-confirm**), **System Status** popover.
- **Inline confirmation card** (dashed cyan border with pulse animation) — cyan **CONFIRM** / red **CANCEL** — for model-driven and executor prompts.
- **Battery toasts**: warning at ≤20% (unplugged) and notification at 100% when fully charged.
- **Session history** persisted in SQLite (`data/session_history.db`), surfaced in the History view.
- **Live telemetry**: CPU, RAM, network I/O on the dashboard.
- **Background workflows**: named multi-step automations run without blocking the UI.

### What you can ask it to do (by area)
- **Apps:** open browser, VS Code, terminal, file manager, Spotify, generic apps, URLs; close apps; **force quit** (confirmed).
- **Web:** Google, YouTube, GitHub, Stack Overflow, Wikipedia, generic search.
- **Input:** type text, paste, hotkeys; mouse move, click, scroll, drag.
- **System:** volume (step or absolute level), screenshot, lock; **sleep**, **shut down**, **restart** — each confirmed; sleep vs shutdown are distinct actions.
- **Files:** create file/folder (executor path confirmation before writing), read, delete (confirmed), rename, move, copy, list, **smart search** (resolves relative paths by scanning under the user profile).
- **Code:** run Python, shell commands (`shell=False`), scripts, git and npm invocations.
- **Browser (Playwright):** persistent Chrome — navigate, click, fill forms, read page, extract text, screenshots, new/close tab (with URL/title filter).
- **Screen:** OCR via Tesseract (`read_screen`).
- **Reminders:** set, cancel, list (timer-based, minimum 5 s).
- **Meta:** time, date, system status (CPU/memory/battery), conversational replies, voice list/switch, theme change, quit.
- **Automation:** named workflows in `data/workflows.json` — list, run, create, remove (confirmed), rename; dangerous steps are restricted when saving.

---

## Project structure

```text
.
├── main.py                   # PyQt application entry point
├── CLAUDE.md                 # System prompt and JSON routing schema
├── core/
│   ├── audio_pipeline.py     # AudioCapture, SttEngine, TtsEngine (voice internals)
│   ├── voice.py              # Thin facade over audio_pipeline — public voice API
│   ├── brain.py              # Claude API call + @tag routing
│   ├── executor.py           # Intent dispatcher and OS handlers
│   ├── automation.py         # Workflow engine (background multi-step tasks)
│   ├── browser.py            # Playwright browser session
│   ├── computer_control.py   # Mouse, keyboard, screen capture
│   ├── history_store.py      # SQLite session history persistence
│   ├── net_telemetry.py      # Live network I/O telemetry
│   ├── personality.py        # Response templates and confirmation text
│   ├── signals.py            # Cross-component PyQt signals
│   ├── memory.py             # Persistent key-value memory
│   └── vapi_client.py        # Vapi assistant platform client
├── ui/
│   ├── dashboard.py          # Main dashboard view (transcript, orb, telemetry)
│   ├── sidebar.py            # HUD sidebar with nav buttons
│   ├── bars.py               # TopBar and BottomBar (clock, battery, status)
│   ├── widgets.py            # ArcReactorWidget and supporting widgets
│   ├── settings.py           # Settings view (API keys, voice, mic device, etc.)
│   ├── history.py            # Session history view
│   ├── voice.py              # Voice interface view
│   ├── automation.py         # Automation workflow view
│   ├── command_palette.py    # Ctrl+K command palette
│   ├── popovers.py           # Status and quick-settings popovers
│   ├── theme.py              # Design tokens, fonts, QSS
│   ├── helpers.py            # Shared UI utilities
│   └── components/
│       └── transcript.py     # TranscriptPanel + InlineConfirmCard
├── config/
│   └── settings.py           # Runtime config dataclass (mic device, sensitivity, etc.)
├── data/                     # workflows.json, session_history.db (gitignored)
├── assets/                   # Logo and reference assets
├── fonts/                    # Bundled UI fonts
├── context.md                # Architecture detail and full feature matrix
└── pyproject.toml            # Dependencies and metadata
```

---

## Requirements

- **Windows** is the primary target for this version.
- Python 3.11+ matching **`pyproject.toml`**.
- **`uv`** recommended for dependency management.
- **Anthropic API key** for Claude intent routing.
- **ElevenLabs API key** for premium TTS (optional fallback: local pyttsx3).
- Optional **Vapi** API key for assistant platform sync.
- **Playwright + Chrome** for browser automation (`playwright install chromium`).
- **Tesseract** on `PATH` for OCR (`read_screen`).
- **sounddevice** + PortAudio for mic capture (bundled via pyproject).

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

User input goes to **`core/brain.py`**, which loads **`CLAUDE.md`** and asks Claude for a single valid JSON command. That object is passed to **`core/executor.py` → `dispatch()`**, which runs the matching handler (apps, files, shell, browser, etc.).

Two confirmation paths exist: **before execute** (Claude `requires_confirmation` + executor registry) and **during execute** (`request_confirmation` → user confirms in UI → deferred callback runs). **Create file** uses the second path so the full resolved path is shown on the confirm card before anything is written.

Voice output uses the **`core/audio_pipeline.py`** TTS engine (ElevenLabs when configured, pyttsx3 otherwise). Before each STT capture, **`AudioCapture.calibrate_threshold()`** samples the current ambient noise floor and sets a dynamic VAD threshold — this compensates for Windows AGC reducing mic gain after TTS playback, which caused reliable first-try capture but failures on subsequent attempts.

Background workflows run via **`core/automation.py`** without blocking the UI thread; all worker→UI updates cross the PyQt signal bridge.

---

## Safety notes

JARVIS can run commands that affect the local machine: files, processes, shell, power state, and browser. Treat it as a **trusted local** assistant.

- Keep secrets in **`.env`**, not in git.
- Session data (`data/session_history.db*`) is gitignored — never committed.
- Review **confirmation** behaviour before enabling **auto-confirm** or broad automation.
- Prefer stricter policies for **shell** and **code** execution if exposed to untrusted input.

---

## Status

Active development — HUD, command pipeline, and voice are functional. Battery telemetry, mic device selection, dynamic VAD calibration, and session history persistence are in place. Hardening, tests, and wake-word support are planned next. See **`context.md`** for architecture detail and the full feature matrix.
