# J.A.R.V.I.S.

J.A.R.V.I.S. is a desktop voice AI assistant built with Python, PyQt5, Anthropic Claude, ElevenLabs, Playwright, and local system-control tools. It presents a cinematic HUD and routes natural language into structured JSON commands for apps, files, system control, browser automation, reminders, code execution, workflows, weather, and voice feedback.

**Canonical project map:** see [`context.md`](context.md). It is the source of truth for architecture, file ownership, and the full capability matrix.

---

## Features (summary)

### Core loop
- **Claude** reads `Claude.md` as the brain prompt and returns **one JSON command** per request: `intent`, `action`, `parameters`, confidence, spoken response, HUD label, and confirmation requirement.
- **`@tags`** such as `@browser`, `@files`, `@system`, and `@code` force intent routing before the prompt reaches Claude.
- **`core/executor.py`** dispatches to focused handlers in `core/handlers/*`, applies confirmation guards, manages reminders, and streams terminal output through Qt signals.
- **Controllers/responders** split command parsing, runtime context, confirmation state, session flags, and final spoken response composition out of `main.py`.

### Voice pipeline
- **`core/audio_pipeline.py`** owns mic capture, VAD, ambient noise calibration, Google SpeechRecognition STT, ElevenLabs streaming TTS, and pyttsx3 fallback.
- **Dynamic noise calibration** samples ambient RMS before each capture and adapts the VAD threshold to recover from Windows AGC changes after TTS playback.
- **Settings-backed voice controls** include mic mute, TTS mute, mic sensitivity, noise gate, mic input device, TTS speed, and voice selection.
- **`core/wake_word.py`** provides an always-on wake-word listener that triggers the normal voice command flow.

### HUD and UI
- PyQt5 HUD pages: **Dashboard**, **Voice**, **Automation**, **History**, **Settings**, and **Terminal**.
- **Dashboard** combines transcript, typewriter animation, Mark-LXXXV arc reactor state, live CPU/RAM/network telemetry, command bar, and toast notifications.
- **Terminal page** (`TerminalPanel`) provides JARVIS Shell v2 with command history, Ctrl+L clear, coloured output, and `@code` submission through the normal executor path.
- **Command palette** (Ctrl+K), **Quick Settings** popover, and **System Status** popover expose fast controls and subsystem health.
- **Session flags** (`mic_muted`, `tts_muted`, `auto_confirm`, `dim_mode`, `wake_word_enabled`) sync across Settings, Quick Settings, and `config/jarvis.json`.
- **Inline confirmation cards** handle destructive actions and in-flight file/folder creation prompts before local side effects happen.
- **Session history** is persisted in SQLite (`data/session_history.db`) and surfaced in the History page.

### Browser automation
- **Persistent Playwright Chrome** handles navigation, clicks, fills, page reading, extraction, screenshots, tab creation, and filtered tab closing.
- **Advanced element picking** uses `browser.snapshot()` to build a numbered accessibility tree, then `browser.find_and_act(goal, action, value)` asks Haiku (`claude-haiku-4-5-20251001`) to select a validated `ref_N`.
- Click/fill actions use Playwright role/name locators with full accessible names, and every smart-picker failure falls back to the legacy selector/text chain.
- Set `JARVIS_BROWSER_USE_LLM_PICKER=false` in `.env` to disable the LLM picker for cost control, offline debugging, or rollback.

### Automation and workflows
- Named workflows live in `data/workflows.json` and can be listed, created, edited, renamed, removed, enabled/disabled, and run in the background.
- Inline multi-step automation is supported when the model returns `automation_task -> run_workflow` with `steps[]`.
- The Automation UI is now split into `ui/views/automation/view.py`, `components.py`, and `dialogs.py`; top-level `ui/automation*.py` files remain as compatibility shims.
- Dangerous nested steps are restricted when workflows are saved or scheduled, and workflows resume automatically after confirmation-required steps.

### What you can ask it to do (by area)
- **Apps:** open browsers, VS Code, terminal, file manager, Spotify, URLs, and generic apps; close apps; force quit with confirmation.
- **Web/search:** Google, YouTube, GitHub, Stack Overflow, Wikipedia, generic web search, and browser-controlled page actions.
- **Input:** type text, paste, press hotkeys, move/click/scroll/drag the mouse.
- **System:** volume, brightness, screenshot, lock screen, Wi-Fi/Bluetooth toggles, sleep, shutdown, and restart with confirmation where appropriate.
- **Files:** create files/folders with path confirmation, read, delete, rename, move, copy, list, and smart recursive search under the user profile.
- **Code:** run Python, shell, PowerShell, CMD, scripts, git, npm, package installs, background processes, and confirmed process kills.
- **Screen/OCR:** read the full screen, active window, regions, or find text with Tesseract.
- **Reminders/weather/meta:** set/list/cancel reminders, fetch current weather, tell time/date/status, switch voice/theme, answer identity questions, and quit the app.

---

## Project structure

```text
.
├── main.py                     # PyQt entry point, stacked pages, state machine, signal wiring
├── Claude.md                   # Canonical JSON routing prompt and intent contract
├── PRODUCT.md                  # Brand/personality and UI direction
├── IMPECCABLE_SKILL_GUIDE.md   # Design workflow notes
├── core/
│   ├── brain.py                # Claude API wrapper, @tag routing, JSON parsing
│   ├── executor.py             # Dispatcher, confirmation guard, reminders, handler exports
│   ├── browser.py              # Persistent Playwright session, snapshot(), find_and_act()
│   ├── audio_pipeline.py       # AudioCapture, SttEngine, TtsEngine
│   ├── voice.py                # VoiceEngine facade and overlap guard
│   ├── wake_word.py            # Background wake-word listener
│   ├── automation.py           # Workflow library persistence and change signals
│   ├── computer_control.py     # Mouse, keyboard, clipboard, screenshot, OCR, volume
│   ├── controllers/            # Command, confirmation, runtime context, session flags
│   ├── handlers/               # Intent implementations
│   ├── responders/             # Spoken response assembly and speech compaction
│   └── integrations/           # External service clients such as weather
├── ui/
│   ├── dashboard.py            # Main HUD page
│   ├── voice.py                # Voice command inspector page
│   ├── history.py              # SQLite-backed command history page
│   ├── settings.py             # API keys, model, voice, mic, theme, session flags
│   ├── sidebar.py              # Six-page HUD navigation
│   ├── bars.py                 # Top/bottom bars, telemetry, battery, network
│   ├── command_palette.py      # Ctrl+K modal input
│   ├── popovers.py             # Quick settings and system status
│   ├── components/
│   │   ├── terminal.py         # TerminalPanel / JARVIS Shell v2
│   │   ├── transcript.py       # TranscriptPanel + InlineConfirmCard
│   │   └── typewriter.py       # Animated transcript proxy
│   └── views/automation/       # Automation view package
├── config/settings.py          # AppConfig, .env overlay, config/jarvis.json persistence
├── data/                       # workflows.json, session_history.db (runtime/gitignored)
├── tests/                      # Unit and interactive verification harnesses
├── assets/                     # Logo and reference HUD assets
├── context.md                  # Full architecture and capability source of truth
├── pyproject.toml              # Project metadata and dependencies
└── uv.lock                     # Locked uv dependency graph
```

---

## Requirements

- **Windows** is the primary target for this version.
- Python 3.11+ matching `pyproject.toml` / `.python-version`.
- **`uv`** for dependency management and running commands.
- **Anthropic API key** for Claude intent routing and advanced browser element picking.
- **ElevenLabs API key** for premium TTS; local pyttsx3 is the fallback.
- Optional API keys for **Vapi** assistant sync and **OpenWeather** weather lookups.
- **Playwright Chromium** for browser automation.
- **Tesseract** on `PATH`, or `TESSERACT_CMD` set in `.env`, for OCR.
- Working microphone/audio devices for voice input and speech output.

---

## Setup

Install Python dependencies. **`uv sync` is the primary, canonical install path:**

```powershell
uv sync
```

`pyproject.toml` is the single source of truth for dependencies. `requirements.txt` is a generated lockfile snapshot (via `uv export --no-hashes`) provided only as a fallback for callers stuck on plain pip (`pip install -r requirements.txt`); do not edit it by hand — regenerate it whenever you change pyproject.

Install the Playwright browser runtime:

```powershell
uv run playwright install chromium
```

Create local environment settings:

```powershell
copy .env.example .env
```

Fill in only the keys and options you use:

```env
ANTHROPIC_API_KEY=your-anthropic-key
ELEVENLABS_API_KEY=your-elevenlabs-key
VAPI_API_KEY=optional
OPENWEATHER_API_KEY=optional
CLAUDE_MODEL=claude-sonnet-4-6
WAKE_WORD=jarvis
JARVIS_BROWSER_USE_LLM_PICKER=true
DEBUG=false
```

Run the app:

```powershell
uv run python main.py
```

Run tests or focused smoke checks:

```powershell
uv run pytest tests/
uv run python tests/test_browser.py
```

If antivirus software such as Avast flags browser, keyboard/mouse, audio, or shell-control behaviour, review the alert carefully and allow-list the project directory or `.venv` only if you trust this local checkout. Do not commit `.env`, `config/jarvis.json`, or runtime data.

---

## How it works

User input arrives from the wake-word listener, voice STT, command bar, command palette, or Terminal page. `core/controllers/command_controller.py` handles repeats and direct workflow tokens, then `core/brain.py` strips `@tags`, builds runtime context, loads `Claude.md`, and asks Claude for a strict JSON command.

`core/executor.dispatch()` applies confirmation policy and routes the command to `core/handlers/*`. Handlers return a standard `{success, output, error}` envelope and may stream output lines to the Terminal page through `core/signals.py`.

Browser clicks and fills can take the advanced path: `browser.snapshot()` captures a prompt-safe accessibility tree, Haiku chooses a valid reference, and Playwright acts by role/name. Empty snapshots, missing keys, malformed JSON, unknown refs, locator misses, API failures, or disabled picker settings all fall back to the legacy selector/text path.

Voice output is assembled by `core/responders/assembler.py` and `core/personality.py`, then spoken through ElevenLabs streaming or pyttsx3 fallback. The voice engine prevents mic capture while TTS is speaking.

All GUI updates cross the single `JarvisSignals` bridge; blocking work stays off the PyQt thread. Runtime settings are stored in `.env` for secrets and `config/jarvis.json` for non-secret UI/session preferences.

---

## Safety notes

JARVIS can affect the local machine: files, processes, shell commands, browser sessions, clipboard, keyboard/mouse input, audio devices, and power state. Treat it as a **trusted local assistant**.

- Keep secrets in `.env`, never in git.
- `config/jarvis.json`, `data/workflows.json`, and `data/session_history.db*` are runtime state; review before sharing.
- Destructive actions use confirmation gates unless session auto-confirm is enabled.
- Review workflow steps before enabling broad automation or scheduled actions.
- Use stricter policies around shell/code execution if exposing JARVIS to untrusted input.

---

## Status

Active development. The HUD, voice pipeline, command routing, Terminal page, workflow automation, advanced browser automation, settings/session flags, telemetry, SQLite history, and confirmation system are implemented. See `context.md` for the detailed module map, known patterns, and current test harnesses.
