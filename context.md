# JARVIS Project Handoff
**Developer:** Malakai V. Weah  
**Project path:** `C:\Users\Dell Latitude Touch\Desktop\jarvis-project`  
**Stack:** Python 3.14, PyQt5, Claude API (Sonnet 4), ElevenLabs TTS, Google STT, Playwright  
**Package manager:** `uv`  
**Run command:** `uv run python main.py`

**Brain prompt:** `CLAUDE.md` (or `Claude.md` on case-insensitive systems) — loaded by `core/brain.py`

---

## What Was Built

JARVIS (Just A Rather Very Intelligent System) — an Iron Man-style voice AI desktop assistant with a full PyQt5 HUD, Claude API brain, ElevenLabs voice, and real OS/browser control.

---

## What JARVIS can do (capability list)

This is the **authoritative “what it does now”** summary (executor + brain + UI). Destructive or sensitive actions go through **confirmation** where noted.

### Brain, memory, and routing
- **Claude** returns a **single JSON** command per user utterance: `intent`, `action`, `parameters`, `confidence`, `response`, `hud_status`, `requires_confirmation`.
- **`@tags`** in the command bar (e.g. `@browser`, `@files`, `@system`) override intent; see `CLAUDE.md` for the full map.
- **Conversation memory** (`core/memory.py`) — rolling window (~8k tokens est.), pairs trimmed together.
- **STT** normalisation (whitespace / punctuation) before routing.

### Voice and UI shell
- **Voice:** Google STT (mic) → command; **ElevenLabs TTS** (with **pyttsx3** fallback), streaming + transcript **typewriter** sync; mic/TTS **mute** toggles; **`Thinking...`** state while work is in progress.
- **HUD:** Dashboard (transcript, arc reactor, telemetry, gauge), **Voice**, **Automation**, **History**, **Settings**; **TopBar** (Quick Settings, **Command palette** / **Ctrl+K**, System Status); **toasts**; **inline confirm card** (cyan CONFIRM / red CANCEL).
- **Command palette** — text commands + `@` tags, recent history.
- **Quick Settings** — mic mute, TTS mute, **auto-confirm** (session-only: skips the *UI* hold; executor registries still apply for dangerous pairs).

### Confirmation model (two layers)
1. **Brain `requires_confirmation`** — used for high-risk intents (e.g. shutdown, delete file, `force_quit`, sleep, etc. per `CLAUDE.md` + `_CONFIRMATION_REQUIRED_ACTIONS` in `executor.py`).
2. **Executor `needs_confirmation`** — mid-flight prompts with a **stored callback** (`request_confirmation`), e.g. **create file** (shows resolved **file** and **folder** path), screenshot when save folder is missing, etc. User must **Confirm** in the transcript card (or answer yes/no in voice when a pending action exists).

**Sleep vs shutdown (routing):** natural language should map *sleep / suspend / standby / sleep mode* → `system_control` + **`sleep`**, and *shut down / power off* → **`shutdown`**. **Sleep, shutdown, and restart** all require **confirmation** before running.

**Create file:** always shows **“Are you sure you want to create this file in this folder, sir?”** (variants in `personality.py`) plus **File:** and **Folder:** lines; if the folder does not exist, the prompt notes that it will be created on confirm. Keep **`requires_confirmation`: `false` in JSON** for `create_file` so the model does not double-prompt; the **executor** owns the confirm UI.

### Open / close applications (`open_app`, `close_app`)
- Open **browser** (Chrome / Firefox / Edge), **VS Code**, **terminal**, **file manager**, **Spotify**, **URL** (default or Playwright session), or **generic** app by name.
- **Close** an app; **force quit** a process (with confirmation). Windows uses `taskkill` with correct flags when applicable.

### Web search (`search_web`)
- **Google**, **YouTube**, **GitHub**, **Stack Overflow**, **Wikipedia**, or generic **web search** — opens the default browser with the right query URL.

### Input automation (`type_text`, `control_mouse`)
- **Type** text, **paste**-style, or **press keys** (including combos, e.g. `ctrl+c`).
- **Mouse:** move, click, double-click, right-click, **scroll**, **drag** (coordinates per `computer_control` / PyAutoGUI).

### System control (`system_control`)
- **Volume** up / down / **mute**; optional **absolute level** (0–100) when the model supplies `level` (see `CLAUDE.md`).
- **Screenshot** to disk (path resolution, optional **region**); may ask to create a **missing folder** (executor confirmation).
- **Lock** screen.
- **Sleep**, **shut down**, **restart** — **confirmed**; Windows uses **`shutdown.exe`** from `%SystemRoot%\System32` for shutdown/restart, and the existing sleep path (e.g. `rundll32` + power profile on Windows).
- *Planned/extended in schema:* brightness, WiFi/BT toggles — only if implemented in `executor` / `computer_control` (check code before advertising beyond volume/lock/screenshot/sleep/restart/shutdown).

### File operations (`file_operation`)
- **create_file** — **path confirmation** in UI (file + folder + note if folder will be created), then write.
- **read_file** — read text (with optional fuzzy locate by filename).
- **delete_file** — **requires_confirmation** (brain or registry).
- **move_file** / **copy_file**
- **list_directory**
- **search_files** (glob under a base path)

### Code execution (`code_execution`)
- **run_python** — `python -c` (timeout bounded).
- **run_shell** — command via argument list, **`shell=False`** (no shell injection).
- **run_script** — run a script file.
- **git_command** / **npm_command** — same execution path as shell, parsed with `shlex`.

### Browser automation — Playwright (`browser_automation`)
- Persistent **Chrome** session: **navigate**, **click** (selector / text / x,y), **fill_form**, **read_page**, **extract** by selector, **screenshot** (page or element), **new_tab**, **close_tab**.

### Read screen / OCR (`read_screen`)
- **OCR** full screen, **region**, or as wired in `computer_control` (Tesseract must be on **PATH**).

### Reminders (`reminder_task`)
- **set_reminder** (delay floor enforced in executor), **cancel_reminder**, **list_reminders** (threading timer / background).

### JARVIS meta (`jarvis_meta`)
- **tell_time**, **tell_date**, **status_report** (CPU/memory via psutil), **conversational** (can use page cache); other actions (theme, help, etc.) are defined in **`CLAUDE.md`** for the model — wire-up in `executor` may be partial; trust **`CLAUDE.md`** + `personality.say` for what is spoken.

### Automation (`automation_task`)
- **list_workflows**, **create_workflow**, **remove_workflow** (with confirmation), **rename_workflow**, **run_workflow** from JSON `data/workflows.json` via `WorkflowLibrary`. Dangerous step types are **blocked** in library validation (see `_DANGEROUS_STEPS` / `_BLOCKED_INTENTS`).

### Unknown
- **unknown** — safe fallback; no action.

### Vapi
- **Optional** — `vapi_client.py` can sync assistant definition; desktop audio still uses local ElevenLabs.

---

## Session notes — docs sync (2026-04-26)

- **Sleep vs shutdown:** Prompt + executor treat **`sleep`** and **`shutdown`** as distinct `action`s; both require user **confirmation** before execution.
- **Create file:** **Executor-level** confirmation with **full path visibility** (file + folder); merged with “create missing folder” into one confirm step.
- This **`context.md`** section + **`README.md`** updated to list capabilities in one place.

---

## Project Structure

```
jarvis-project/
├── main.py                  # Entry point — JarvisWindow, Qt signal bridge, state machine
├── CLAUDE.md                # Brain config v2.1 — 14 intent categories, @TAG routing, JSON schema
├── .env                     # API keys (never committed)
├── pyproject.toml           # Dependencies (uv)
├── core/
│   ├── brain.py             # Claude API connector, @tag routing, STT normalisation
│   ├── memory.py            # Rolling conversation history (8k token window)
│   ├── automation.py        # WorkflowLibrary (JSON) — load/save workflows, step validation
│   ├── executor.py          # Intent dispatch — handlers, dispatch() + confirmation registry
│   ├── computer_control.py  # OS control — mouse, keyboard, OCR, clipboard, volume
│   ├── browser.py           # Playwright Chrome session — navigate, click, fill, read, tabs
│   ├── voice.py             # ElevenLabs TTS (streaming) + Google STT
│   ├── signals.py           # Qt signal hub
│   └── vapi_client.py       # Vapi assistant config sync
├── ui/
│   ├── dashboard.py         # Main HUD — SYS_LOG_BUFFER, arc reactor, telemetry
│   ├── bars.py              # TopBar, BottomBar
│   ├── sidebar.py           # Nav sidebar
│   ├── voice.py             # Voice view
│   ├── history.py           # History view
│   ├── settings.py          # Settings view
│   ├── automation.py        # Automation / workflow library view
│   ├── command_palette.py  # Global modal — Ctrl+K, @tags, recent commands
│   ├── popovers.py          # QuickSettingsPopover, SystemStatusPopover (TopBar)
│   ├── components/          # transcript (incl. inline confirm), typewriter, panels
│   ├── widgets.py           # Shared widgets
│   └── theme.py             # Colors, fonts
├── config/
│   └── settings.py          # AppConfig — loads .env, never writes API keys to disk
├── data/
│   ├── mock.py              # Mock history for startup
│   ├── intents.py           # Intent definitions
│   └── workflows.json      # Named workflow library (user-editable / UI-backed)
└── tests/
    ├── test_computer_control.py   # 6 tests: clipboard, keyboard, screenshot, OCR, mouse, volume
    ├── test_executor.py           # 15 tests: open/close app, web search, file ops, mouse, meta, reminders
    └── test_browser.py            # 15 tests: navigate, click, fill, read, screenshot, tabs
```

### Intent quick reference (14 categories)

| Intent | @Tag | What it does (short) |
|---|---|---|
| `open_app` | `@app` | Launch apps, open URLs (browser or Playwright) |
| `close_app` | — | Close app; force quit (with confirm) |
| `search_web` | `@search` | Google, YouTube, GitHub, Stack Overflow, Wikipedia |
| `type_text` | `@type` | Type text, paste, key combos |
| `control_mouse` | `@mouse` | Move, click, scroll, drag |
| `system_control` | `@system` | Screenshot, volume, lock, **sleep** / **shutdown** / **restart** (with confirm) |
| `file_operation` | `@files` | **Create** (path confirm in UI), read, delete (confirm), move, copy, list, search |
| `code_execution` | `@code` | Python, shell, script, **git** / **npm** commands |
| `browser_automation` | `@browser` | Playwright: navigate, click, fill, read, tabs, screenshots |
| `read_screen` | `@screen` | OCR (Tesseract) |
| `automation_task` | `@automate` | Workflows: list, run, create, remove, rename |
| `reminder_task` | `@remind` | Set, cancel, list timed reminders |
| `jarvis_meta` | `@jarvis` | Time, date, status, **conversational**; other meta in `CLAUDE.md` |
| `unknown` | — | No action; graceful fallback |

---

## Key Architecture Decisions

### Signal Flow
```
User input → _process_cmd() → ask_claude_async() → _brain_result_ready signal
→ _on_brain_result() → _execute_result() → dispatch(result)
→ voice_engine.say(text, on_ready=λ: _tts_ready.emit())
→ ElevenLabs streams → on_ready() → _tts_ready signal → Qt main thread
→ transcript.update_last_jarvis() → typewriter animation starts
```

### Thread Safety
- All worker→UI updates go through `pyqtSignal` — never direct widget access from threads
- `BrowserSession` uses `threading.RLock` to serialize all Playwright calls
- `ConversationMemory` uses `threading.Lock` on all mutations

### TTS/Transcript Sync
- `voice_engine.say(text, on_ready=callback)` — event-driven, not timer-based
- `on_ready()` fires when ElevenLabs first audio chunk is ready to play
- Transcript typewriter animation starts exactly when audio begins — zero guesswork

### Conversation Memory
- `core/memory.py` — `ConversationMemory` class
- Rolling 8,000 token window (estimated as `len(text) // 4`)
- Trims oldest (user, assistant) pairs together — never splits a pair
- Only stores `cleaned_text` — no stale per-call metadata (clipboard, active_window)
- `add_exchange()` only called on successful Claude parse — no orphaned messages

---

## UI Features

### SYS_LOG_BUFFER (Transcript)
- `_TypewriterProxy` wraps `TranscriptPanel` — JARVIS responses type character by character at 25ms/char
- **"Thinking..." animation** — dots cycle `Thinking.` → `Thinking..` → `Thinking...` every 500ms while waiting for ElevenLabs
- Mock history guard — existing entries don't animate
- Cancel-on-new-message — stale animations stop immediately
- Intent/confidence suffix `(intent, X%)` appended after full text finishes

### Arc Reactor Orb States
| State | Meaning |
|---|---|
| `idle` | STANDBY |
| `listening` | Mic active, capturing voice |
| `thinking` | Claude API call in flight |
| `responding` | ElevenLabs fetching audio |
| `speaking` | Audio playing + typewriter running |

### HUD Telemetry
- CPU — live chart + segmented bar (1s poll, psutil)
- MEM — percentage + GB readout (2s poll, psutil)
- UPLINK — TX/RX display + sparkline
- Session uptime — fills over 4-hour session

---

## Browser Automation (Playwright)

`core/browser.py` — `BrowserSession` singleton

- **Persistent Chrome session** — one window, one tab reference, lives for JARVIS lifetime
- `browser.start()` called on JARVIS startup (background daemon thread)
- `browser.stop()` called on `closeEvent` + `SIGINT`/`SIGTERM`
- All methods return `{success: bool, output: str, error: str}`

### Methods
```python
browser.navigate(url)                          # goto URL, wait domcontentloaded
browser.click_element(selector, text, x, y)   # CSS selector → text → coordinates
browser.fill_form(fields)                      # CSS selector → label → placeholder
browser.read_page()                            # extracts main/article/body text (4k cap)
browser.extract_content(selector)             # inner text of specific element
browser.screenshot_page(path)                 # full page screenshot
browser.screenshot_element(selector, path)    # element screenshot
browser.new_tab(url)                           # open new tab, navigate
browser.close_tab()                            # close active tab, switch to previous
browser.is_ready                              # public property (not _ready)
```

### Install Requirements
```bash
uv add playwright
python -m playwright install chrome
```

---

## OS Control (computer_control.py)

All functions return `{success, output, error}`. All deps lazy-imported.

```python
# Keyboard
type_text(text, delay=0.02)
press_key("ctrl+c")           # hotkey combos supported

# Mouse  
move(x, y)
click(x, y, button="left")
double_click(x, y)
right_click(x, y)
scroll(direction, amount)
drag(from_x, from_y, to_x, to_y)

# Screen
screenshot(path, region)
ocr_screen(region)            # requires Tesseract binary in PATH

# System
set_volume("volume_up")       # volume_up / volume_down / volume_mute
lock_screen()                 # Windows ctypes

# Clipboard
get_clipboard()
set_clipboard(text)
```

### Tesseract (for OCR)
```bash
# Download and install from:
# https://github.com/UB-Mannheim/tesseract/releases
# v5.4.0.20240606.exe — check "Add to PATH" during install
tesseract --version           # verify
```

---

## Voice Pipeline

### TTS (ElevenLabs)
- Streams MP3 chunks via `client.text_to_speech.stream()`
- Plays via Windows MCI (`mciSendStringW`) — no extra audio deps
- Free tier: `mp3_44100_128` format, `eleven_multilingual_v2` model
- Fallback: `pyttsx3` (Windows SAPI) if ElevenLabs fails

**Voice IDs:**
- `male-british` → George (`JBFqnCBsd6RMkjVDRZzb`)
- `male-american` → Adam (`pNInz6obpgDQGcFmaJgB`)
- `female-british` → Rachel (`21m00Tcm4TlvDq8ikWAM`)

### STT (Google)
- `sounddevice` mic capture → WAV frames
- `SpeechRecognition` → Google STT free tier
- RMS silence detection to auto-stop recording
- `audioop` replacement with `struct.unpack` (Python 3.14 compatibility)

---

## Security Fixes Applied

| Fix | Detail |
|---|---|
| `shell=False` | `executor.py` — `shlex.split()` always runs, no Windows shell injection |
| `.gitignore` | `config/jarvis.json`, `.env`, `data/session_history.json` protected |
| `config.save()` strips keys | `anthropic_api_key`, `vapi_api_key`, `elevenlabs_api_key` never written to disk |
| `requires-python = ">=3.11"` | Better wheel compatibility |
| `taskkill /F /IM` | Force quit correctly uses `/F /IM` not just `/F` |
| `browser.is_ready` | Public property instead of `browser._ready` direct access |

---

## .env Required Keys

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
VAPI_API_KEY=...              # optional — Vapi assistant config sync
CLAUDE_MODEL=claude-sonnet-4-20250514
```

---

## Dependencies

```bash
uv add anthropic elevenlabs playwright pyautogui pytesseract pyperclip pyttsx3 \
       sounddevice SpeechRecognition numpy psutil PyQt5
```

---

## Vapi Integration

`core/vapi_client.py` — registers JARVIS assistant on Vapi's platform on startup.

- Configures: Claude Sonnet LLM, ElevenLabs George voice, Deepgram nova-2 STT
- Persists `vapi_assistant_id` in `config/jarvis.json` — reuses on next startup
- Desktop audio uses ElevenLabs directly (Vapi WebRTC is browser-only)
- Vapi role: portable assistant definition for future web/phone deployments

---

## What's Remaining

| Item | Status |
|---|---|
| `ANTHROPIC_API_KEY` in `.env` | ⚠️ Required for brain routing to work |
| `core/automation.py` + `data/workflows.json` | ✅ Workflow library, executor + Automation UI |
| End-to-end voice test | ⏳ Pending API key (when keys missing) |
| GitHub push | ⏳ Pending — repo: `github.com/Valentine45-dev/jarvis-ai-assistant` |
| `core/browser.py` Playwright thread hardening | 🔮 V2 — dedicated browser thread + queue |
| Phase 1 UX audit fixes (confirm bar, history clear, auto-confirm hardening) | ⏳ See `context.md` — planned, not all implemented here |
| Wake-word / continuous listen loop | ⏳ Not built — System Status popover shows “coming soon” |

---

## End-to-End Test (do this after adding API key)

```
1. "What time is it?"          → jarvis_meta → tell_time
2. "Open github.com"           → browser_automation → navigate (Playwright Chrome)
3. "Search YouTube for Iron Man" → search_web → youtube
4. "Take a screenshot"         → system_control → screenshot (saved to Desktop)
5. "Remind me in 30 seconds to push to GitHub" → reminder_task → set_reminder
```

All 5 passing = JARVIS fully operational. 🤖

---

## What we did — UI/UX audit session (2026-04-26)

This section records work from a Cursor session: understanding the app, then a structured **architect-first** review of **bad or risky UI/UX** across all HUD pages. No code was required for that phase; the output was a blueprint and a phased fix list.

### How the app is structured (condensed)

- **Entry:** `main.py` — `JarvisWindow` with `QStackedWidget` for five views: Dashboard, Voice, Automation, History, Settings.
- **Shell:** `HudSidebar` (nav indices 0–4) + `TopBar` + `BottomBar`; global toasts on `DashboardView.toast`.
- **Flow:** User command → `ask_claude_async` → `_on_brain_result` → if `requires_confirmation`, hold in `_pending_result` and wait for `ConfirmationBar` signals; else `_execute_result` → `dispatch` → TTS + HUD updates.
- **Output users see:** Dark HUD (`#0d1516`), cyan accent, Roboto Mono + Space Grotesk, glass panels, arc reactor, telemetry, transcripts, toasts. Secondary pages (Voice, Automation, History, Settings) share grid backgrounds and large `*_CORE` titles.

### What the audit was

- **Method:** Follow the **architect-first** skill (modification mode): intercept what exists, classify complexity, decompose by surface, failure audit, phase ordering with Phase 1 = non-breaking safety foundation.
- **Scope:** All primary surfaces — global chrome, Dashboard, Voice, Automation, History, Settings, sidebar, top/bottom bars, quick settings popover.
- **Not in scope for that pass:** implementing fixes (user approval / separate task).

### Highest-severity issues identified

| Area | Issue |
|------|--------|
| **Confirm flow** | `ConfirmationBar` on the dashboard was not surfaced in the layout (compat widgets `setVisible(False)`), while `main.py` still wired confirm/cancel. Destructive flows expecting confirmation could be unusable; Voice page text referred to “confirm on dashboard” inconsistently. |
| **Auto-confirm** | Quick Settings “auto-confirm” bypasses confirmation for destructive actions — needs stronger UX (e.g. two-step, persistent indicator) if kept. |
| **History** | History rows could show success styling even when executor failed, if `status` was never written from `exec_out`. “Clear history” only cleared the view, not the backing list in `main`. |
| **Trust / telemetry** | Some labels read as live (uplink TX/RX, “ROUTER/PIPELINE”, “SYSTEM ONLINE”) but were static or not wired to real health — risk of false confidence when debugging. |
| **Accessibility** | Small caps text, low-contrast secondaries, tiny hit targets, no keyboard path on custom sidebar/rows — document as debt if shipping beyond personal use. |

The full audit also listed per-page items (e.g. Automation: no “create workflow” UI, cramped controls; Settings: single APPLY for all sections, no test connection; etc.) and proposed **phases** — Phase 1 safety/truth, Phase 2 feedback, Phase 3 findability, Phase 4 a11y/polish.

### If you continue this work

- Treat **Phase 1** in that blueprint as the first implementation pass: confirm bar visibility + wiring, auto-confirm safety, real `status` in history, clear-history ↔ `main` sync, and either remove or wire “decorative” status labels.
- Re-read `main.py` and `ui/dashboard.py` for `confirm_bar` / `LeftColumn` before changing layout — APIs may have shifted after this handoff was written.

### Note on “what GPT said”

If a separate model was asked the same “bad UI/UX” question, the structured answer above is the one aligned to **this** repo and the **architect-first** steps. Use this file as the project record; reconcile any third-party summary against the code.

---

## What we did — features & UI (2026-04-26)

This section records **implementation work** from the same iteration: workflow library, safety hardening, Voice/TopBar UX, and supporting modules. It complements the audit section above (audit = analysis; this = what shipped in code). The subsections below include the **step-by-step Voice build**, **TopBar before/after**, **Quick Settings / Command Palette / System Status** tables, the **architect-first meta-audit** cross-reference, and **git** notes so the narrative is not only in chat history.

### Automation — JSON workflow library & executor

- **`data/workflows.json`** — Named workflows persisted on disk; edited by the app and/or by hand (valid structure expected).
- **`core/automation.py` — `WorkflowLibrary`** — Load/save, list workflows, add/update/delete/rename, toggle enabled, run by name. Step lists validated against blocked/dangerous patterns (phased rollout across “Phase 1–3” safety work).
- **`core/executor.py`** — `automation_task` runs library workflows; **`dispatch()`** is the **authoritative confirmation gate**: `_CONFIRMATION_REQUIRED_ACTIONS` (and related registries) so `requires_confirmation: false` in a bad payload cannot bypass destructive steps. Return semantics fixed so a failed step does not report overall success.
- **`ui/automation.py`** — Library UI: list rows, play/toggle/delete/rename, step breakdown, execution log; toasts and layout improvements (e.g. log size, non-overlapping toasts relative to CPU strip).

### Voice engine — mic / TTS mute (`core/voice.py`)

- **`set_mic_muted` / `set_tts_muted`** (and properties) on **`VoiceEngine`**.
- **`say()`** — If TTS muted, skips audio but still calls **`on_ready`** so transcript / typewriter / reveal paths do not stall.
- **`listen()`** — If mic muted, short-circuits with an error path suitable for the HUD.
- **Mic hot → mute** — `main.py` can reset the UI to **idle** if the user mutes while listening so the state does not stick on “LISTENING”.

### Voice page — detailed build & layout (`ui/voice.py` + `main.py`)

**Build order in code:** page mic + **“awaiting”** state maps → embed mic in **`_CommandInspector`** → Phase 2 **`set_last_result` / `set_action` / `set_status` / `reset`** on the inspector → **`VoiceView`**: `set_execution`, `set_pending`, `clear_pending` → wire **`main._on_brain_result` / `_execute_result` / cancel** to those APIs.

- **`_PageMicButton`** — ~**96px** circular **`QPushButton`** in the **inspector body** (between waveform and detail text); **`pressed_toggled`** custom signal (avoids shadowing **`QPushButton.clicked`** in subclasses). **`VoiceView`** re-emits **`mic_toggled`** for the same pipeline as the Dashboard mic.
- **“awaiting”** — Extra state in maps so **pending brain confirmation** uses **amber** / `StatusPip` **“standby”** instead of looking idle.
- **`_CommandInspector`** — **`set_last_result(intent, conf)`**, **`set_action`**, **`set_status(..., kind=)`** (ok / fail / pending / idle), **`reset`**. **`set_state()`** syncs the page mic + hint (e.g. “CLICK TO ACTIVATE”, “LISTENING — CLICK TO STOP”).
- **`VoiceView.set_execution(intent, action, conf, success, error=None)`** — On dispatch: success → green **EXECUTED**; failure → red **FAILED — …** (error truncated in the one-line status; full error in tooltip is still optional debt).
- **`VoiceView.set_pending(...)`** — When **`requires_confirmation`**: **AWAITING USER CONFIRMATION** on the inspector; forces **status strip** to **awaiting** so a preceding `_set_state("idle")` does not flash **STANDBY** during a real hold. Timeline can append a **[SYS] Confirmation required** system line for the intent/action.
- **`VoiceView.clear_pending()`** — On cancel: **CANCELLED**; restores from the view’s internal `_state` so you do not keep amber “awaiting” after **`_set_state("idle")`**.

**Wiring in `main.py` (illustrative)**

- Pending: `set_pending(intent, result.get("action", ""), conf, resp or "Awaiting confirmation, sir.")`
- After dispatch: `set_execution(intent, result.get("action", ""), conf, bool(exec_out.get("success")), exec_out.get("error"))`
- Cancel path: `clear_pending()`

**State table (Voice inspector)**

| Phase | What you see |
|--------|----------------|
| Idle | “AWAITING INPUT”; neutral mic; **CLICK TO ACTIVATE** |
| Listening | Cyan / pulse; **LISTENING — CLICK TO STOP** |
| `requires_confirmation` | Amber **AWAITING USER CONFIRMATION**; strip can show “paused”; [SYS] line possible |
| Executor success | Green **EXECUTED** |
| Executor failure | Red **FAILED —** \<short error\> |
| User cancels | Red **CANCELLED**; log can record cancel |

**Design decisions**

- **Mic in inspector** — Treated as the “command panel” control; header-only alternative rejected as cramped.
- **`pressed_toggled`** — Explicit name vs reusing `clicked` to avoid signal override bugs on subclasses.
- **`set_pending` overrides strip** — On purpose: global **idle** after brain result must not look like a clean standby while a confirmation is still pending.
- **`clear_pending` uses local `_state`** — Avoids stale “awaiting” after global idle.

**Not built in that voice batch (roadmap)**

- Session stat card (command count, avg confidence, session uptime on-page).
- Quick voice suggestion chips (Dashboard-style, voice-focused).

**Layout fix (execution log was too small)**

- **Before:** `setFixedHeight(110)` on the log (~5 lines) while the body took the rest.
- **After:** Remove fixed height; **`setMinimumHeight(170)`**; stretch **3 : 1** (body : log) so the log **grows** with the window. Transcript + “active command” still dominate, but the log is never ~5 lines only.

| Window (approx.) | Exec log (approx.) | Body column (approx.) |
|------------------|--------------------|------------------------|
| 1280×800 | ~170px (~10 lines) | ~457px |
| 1440×900 | ~180px | ~539px |
| 1920×1080 | ~225px | ~674px |
| 2560×1440 | ~315px | ~944px |

### TopBar — from decorative to functional

**Before** — The three right-hand icons in **`_TOPBAR_ICONS`** (Phosphor: sliders, terminal, broadcast) had **no** `clicked` wiring — tooltips only (ported from reference HTML as chrome).

**Agreed build order** — (1) **Quick Settings** popover, (2) **Command palette** + **Ctrl+K**, (3) **Broadcast** as **System Status** (Option C) — **not** a fake wake-word toggle and **not** a half-built continuous STT loop until ready.

| Icon | Shipped behavior |
|------|------------------|
| **Sliders** | **`QuickSettingsPopover`** — see table below. |
| **Terminal** | **`CommandPalette`** — full-window dim + centered input; see below. |
| **Broadcast** | **`SystemStatusPopover`** — live-ish rows, refresh on open; wake-word row = honest **“coming soon”**. |

**`QuickSettingsPopover` (`ui/popovers.py`)** — `Qt.Popup` + frameless; **`show_below(anchor)`**; **`sync_state(mic, tts, auto_confirm)`** on open.

| Toggle | Wired to | Notes |
|--------|-----------|--------|
| MUTE MIC | `voice_engine.set_mic_muted()` | Can force idle if was listening; toast |
| MUTE TTS | `voice_engine.set_tts_muted()` | No audio; **`on_ready` still runs** |
| AUTO-CONFIRM | `JarvisWindow._auto_confirm` | **Session-only**, not persisted. Skips **UI** confirmation hold; **`dispatch` / `_CONFIRMATION_REQUIRED_ACTIONS` still enforce backend rules.** |
| OPEN FULL SETTINGS | `sidebar.goto(4)` | Same as clicking Settings in the nav |

**`CommandPalette` (`ui/command_palette.py` + `main.py`)** — Child of main window, **`resizeEvent`** on **`JarvisWindow`** keeps overlay full-window. **Terminal** icon and **Ctrl+K**; **`command_submitted` → `_process_cmd`**; hide palette before dispatch. **Recents:** newest from **`self._history`**, deduped, cap **5**, refresh on each open. Reuses **`_TagLineEdit`** for `@` tags. **Deferred:** last-intent JSON panel, keyboard nav in recents, fuzzy catalog.

**`SystemStatusPopover` (`ui/popovers.py`)** — `_StatusRow` + **`StatusPip`**, defensive **try/except** per row, **“AS OF …”** timestamp. **Bug found in QA:** `browser.is_ready` is a **`@property`** — must be **`if browser.is_ready:`**, not `is_ready()` (else `'bool' object is not callable` on that row).

**Shared**

- **`ui/bars.py`** — **`settings_clicked` / `terminal_clicked` / `broadcast_clicked`**, **`icon_button("settings" \| "terminal" \| "broadcast")`** for anchors.
- **`ui/sidebar.py`** — **`goto(nav_idx)`** delegates to the same path as a real nav click.
- **`main.py`** — **`_show_quick_settings`**, **`_toggle_palette` + `_on_palette_command`**, **`_show_system_status`**; broadcast no longer a “coming next” **toast** for the icon (that text is **stale** in any old audit).

### Misc UX fixes in the same window of work

- **Toast position** — Adjusted so toasts do not sit on top of the CPU/telemetry readout (layout/order fix on the dashboard strip).
- **TopBar** — Terminal and broadcast are **no longer** dead “coming next” toasts; they open the palette and system status, respectively (align any external audit that still claims “2 of 3 stubs” — **stale**).

### Architect-first: Claude’s UI/UX audit + second-opinion meta-audit (same session, analysis only)

- **Claude** produced a long **JARVIS HUD — UI/UX Audit Blueprint**: global **G1–G10**, Dashboard **D1+**, Voice **V1+**, Automation, History, Settings, Sidebar, TopBar, Bottom Bar; **Step 4 failure audit**; **phased fix list** (F1+). Themes: **Dashboard `confirm_bar` / compat widgets** hidden while **`main.py`** still wires confirm/cancel; **auto-confirm** as a **footgun**; **History** “clear” and **success pip**; **decorative** uplink/ROUTER/bottom “SYSTEM ONLINE”; a11y and keyboard debt.
- **Meta-audit (code-verified)** — **S10** “API keys written plaintext by `config.save()`” is **false** — **`config.save()` strips** `anthropic_api_key`, `vapi_api_key`, `elevenlabs_api_key`; keys live in **`.env`**. **TB1** “two of three TopBar icons are stubs / coming-next toasts” is **stale** — **Command palette** and **System status** ship. **Additions** the first audit underplayed: long **`automation_task`** on the **UI thread** can **freeze** the HUD; no **running** spinner on workflow rows; error **toasts** vs info duration; unbounded in-memory `_history`.
- **Revised fix priority (summary)** — Phase 1: confirmation surfaces + **history** truth + **clear** + auto-confirm hardening + **honest** telemetry. Phase 2: **background workflow run**, settings test connection, **scanline** implement vs remove. **Not** a priority: responsive collapse below 1280 if the product stays desktop-only.

The full G/D/V/A/H/S/TB issue tables are **not** copied here — keep the original export in your issue tracker, and re-verify against `main.py` and the `ui/` tree before implementation.

### Git — example `git add` / `commit` (that session)

Example **`git status`**: modified `core/voice.py`, `main.py`, `ui/bars.py`, `ui/sidebar.py`, `ui/voice.py`, `ui/widgets.py`; new `ui/command_palette.py`, `ui/popovers.py`; `context.md` if tracked.

```powershell
cd "c:\Users\Dell Latitude Touch\Desktop\jarvis-project"
git add core/voice.py main.py ui/bars.py ui/sidebar.py ui/voice.py ui/widgets.py ui/command_palette.py ui/popovers.py
# optional: git add context.md
# optional: add core/executor.py, core/automation.py, ui/automation.py, ui/dashboard.py, data/workflows.json if bundled
```

Example message: `feat(ui): topbar popovers, command palette, voice inspector, mic/TTS mutes`

### Files most touched in this work (for git / review)

- `main.py`, `core/voice.py`, `core/executor.py`, `core/automation.py`, `ui/voice.py`, `ui/bars.py`, `ui/sidebar.py`, `ui/automation.py`, `ui/widgets.py` (and/or `ui/dashboard.py` for toast/telemetry), **`ui/popovers.py`**, **`ui/command_palette.py`**, `data/workflows.json` (as applicable).

### Keyboard shortcut

- **Ctrl+K** — Toggles the command palette on the main window via `QShortcut`.

---

## CV/Portfolio Description

> **JARVIS** — Iron Man-style voice AI desktop assistant (Python, PyQt5)  
> Built a full-stack desktop AI assistant featuring a custom HUD with arc reactor orb, real-time telemetry, and SYS_LOG_BUFFER transcript with typewriter animation. Integrated Claude API (Sonnet 4) for natural language intent routing across 14 intent categories (e.g. apps, files, system, browser, automation, reminders). Implemented ElevenLabs streaming TTS with event-driven audio/transcript synchronisation, Google STT for voice input, and a Playwright Chrome session for browser automation (navigate, click, fill forms, read page content). Architecture uses PyQt5 signal bridge for thread-safe worker→UI communication, rolling conversation memory (8k token window), and a modular executor pattern separating intent routing from OS execution.  
> **Stack:** Python · PyQt5 · Claude API · ElevenLabs · Playwright · PyAutoGUI · Pytesseract · Google STT · Vapi