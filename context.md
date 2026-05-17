# JARVIS — Project Context

**Developer:** Malakai V. Weah
**Workspace:** `c:\Users\Lenovo\Documents\jarvis-project`
**Stack:** Python 3.11+, PyQt5 HUD, Anthropic Claude (intent router), ElevenLabs (TTS), Google SpeechRecognition (STT), Playwright (browser), Tesseract (OCR), psutil/pycaw (system), SQLite (history), Vapi (optional cloud assistant binding)
**Package manager:** `uv` (lockfile in `uv.lock`)
**Run:** `uv run python main.py`
**Brain prompt (canonical):** `Claude.md` — loaded verbatim by `core/brain.py`. Every routing rule, intent definition, confirmation policy, and @tag mapping in the prompt is also enforced in Python.
**Product/voice spec:** `PRODUCT.md` defines the brand personality ("Precise, Commanding, Inevitable"), target user, and anti-references.
**Design workflow:** `IMPECCABLE_SKILL_GUIDE.md` describes the `/impeccable …` design loop used to keep UI surfaces aligned with `PRODUCT.md`.

This document is the single source of truth for what is in the repo and what each module does. It replaces the older session-log style context.

---

## 1. High-level architecture

```
                ┌─────────────────────────────────────────┐
 user voice ──► │ wake_word ──► voice (STT) ──► main.py   │
 user text  ──► │                                          │
                │   ┌──────────────────────────────────┐  │
                │   │ brain.py  (Claude intent router) │  │
                │   └──────────────────────────────────┘  │
                │                  │                      │
                │                  ▼                      │
                │   ┌──────────────────────────────────┐  │
                │   │ executor.py + core/handlers/*    │  │
                │   │  → OS, browser, files, code,     │  │
                │   │    workflows, reminders, weather │  │
                │   └──────────────────────────────────┘  │
                │                  │                      │
                │                  ▼                      │
                │   ┌──────────────────────────────────┐  │
                │   │ responders/ + personality.py     │  │
                │   │  → spoken response + HUD updates │  │
                │   └──────────────────────────────────┘  │
                │                  │                      │
                │   voice (TTS) ◄──┘                      │
                │   PyQt HUD (ui/*) ◄── core/signals.py   │
                └─────────────────────────────────────────┘
```

Every cross-thread message flows through the single `JarvisSignals` instance in `core/signals.py`. Blocking work (Claude API, ElevenLabs streaming, RTT probes, mic capture, code execution, wake-word listener) runs off the GUI thread.

---

## 2. Top-level files

| File | Purpose |
|---|---|
| `main.py` | Application entry point. Builds the `QMainWindow`, `HudSidebar`, `TopBar`/`BottomBar`, six pages (`Dashboard`, `Voice`, `Automation`, `History`, `Settings`, `Terminal`) inside a `QStackedWidget`, command palette, popovers, global hotkeys, and wires `voice_engine` ↔ `brain` ↔ `executor` ↔ UI. Owns the master state machine (`idle`/`listening`/`thinking`/`speaking`), the confirmation flow, the in-memory session history, and the SQLite-backed `history_store`. |
| `Claude.md` | Canonical brain system prompt — full intent definitions, action lists, parameter schemas, confidence rules, response style, HUD label conventions, @tag overrides, executor safeguards. **Treated as a contract**; changes here must be mirrored in `core/brain.py` and the relevant handler(s). |
| `README.md` | Quickstart, feature overview, requirements, setup instructions. |
| `PRODUCT.md` | Brand personality, target persona (power user), anti-references (Cortana, generic chatbots), core design principles. Drives the UI voice and look. |
| `IMPECCABLE_SKILL_GUIDE.md` | Internal design workflow: `/impeccable shape`, `craft`, `critique`, `audit`, `polish`. |
| `context.md` | **This file.** Project-wide context document. |
| `pyproject.toml` | Project metadata + primary dependencies (anthropic, elevenlabs, PyQt5, playwright, pyautogui, pytesseract, sounddevice, speechrecognition, vapi-server-sdk). |
| `requirements.txt` | Categorised dependency list with optional extras (livekit-agents for streaming voice, PyAudio fallback for STT, etc.). |
| `uv.lock` | Pinned dependency tree for `uv`. |
| `.python-version` | Python version pin for tooling (pyenv / uv). |
| `.env.example` | Template for `.env`. Documents `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `VAPI_API_KEY`, `OPENWEATHER_API_KEY`, `CLAUDE_MODEL`, `WAKE_WORD`, `USER_NAME`, `OPENWEATHER_DEFAULT_CITY`, `JARVIS_DEFAULT_CREATE_PARENT`, debug flags. |
| `.env` | **Local secrets — never committed.** API keys + model overrides. |
| `.gitignore` | Standard Python + project ignores. |

---

## 3. `config/` — runtime configuration

| File | Function |
|---|---|
| `config/settings.py` | `AppConfig` dataclass + module-level `config` singleton. Loaded from `config/jarvis.json` (created on save) with `.env` always overlayed on top so API keys cannot leak into JSON. Fields: API keys, `claude_model`, `wake_word`, `user_name` (default `"Valentine"`), `tts_voice`/`tts_speed`, `mic_sensitivity`/`noise_gate`/`mic_device`, session flags (`mic_muted`, `tts_muted`, `auto_confirm`, `dim_mode`, `wake_word_enabled`), `theme`, `weather_default_city`. Provides `from_env()`, `load()`, `save()` (omits sensitive keys). |
| `config/jarvis.json` | Generated at runtime when Settings → APPLY_CFG is pressed. Not committed. |

---

## 4. `data/` — persisted runtime data and seed constants

| File | Function |
|---|---|
| `data/intents.py` | Legacy intent name + quick-action seed constants (`INTENTS`, `QUICK_ACTIONS`, `RESPONSES`). Mostly used for UI iconography. |
| `data/mock.py` | Placeholder mock data (`MOCK_HISTORY`, `MOCK_AUTOMATIONS`) for offline UI experiments. The live HUD does **not** seed transcripts from this. |
| `data/workflows.json` | User-defined workflows persisted by `core/automation.workflow_library`. Each record: `id`, `name`, `trigger`, `enabled`, `last_run`, `steps[]` (list of natural-language strings or structured `{intent, action, parameters}` dicts). |
| `data/session_history.db` | SQLite database created on first run by `core/history_store.py`. Stores command/response/intent/confidence per turn. |

---

## 5. `core/` — backend brain, executor, and infrastructure

### 5.1 Brain + memory

| File | Function |
|---|---|
| `core/brain.py` | Wraps the Anthropic Claude Messages API. (1) Normalises the user input and strips leading `@tags`, mapping each to a canonical intent via `TAG_INTENT_MAP`. (2) Builds the `context` block (`os`, `user_name`, `active_window`, `clipboard`, `previous_command`, `tag_override`). (3) Sends `Claude.md` as the system prompt. (4) Parses the strict JSON reply (`intent`, `action`, `parameters`, `confidence`, `response`, `hud_status`, `requires_confirmation`). (5) Enforces tag overrides (override wins, +0.05 confidence cap 1.0). (6) Produces post-execution narration via `core/personality.py`. (7) Falls back to `{"intent": "unknown"}` on parse/API errors so the rest of the app keeps running. |
| `core/memory.py` | Rolling conversation window for Claude. Trims oldest entries to stay under the token budget. `inject_outcome(...)` records the executor result back into the transcript so follow-ups have context. |
| `core/workflow_nlu.py` | Deterministic NLU bypass for "create a routine/workflow that does X, Y, Z" phrasing. Extracts name + step list and returns a fully formed `automation_task → create_workflow` dict, so unambiguous multi-line creates do not depend on Claude. |
| `core/personality.py` | Maps `(intent, action, outcome)` to randomised, on-brand JARVIS phrasings (British butler tone, varied vocabulary, `"sir"` cadence). Generates confirmation questions and shortens output for speech. |

### 5.2 Executor and shared helpers

| File | Function |
|---|---|
| `core/executor.py` | Central dispatcher. Takes the parsed dict from `brain.py`, applies the confirmation guard (or `_auto_confirm` bypass), routes to the appropriate handler, exposes `resolve_confirmation(answer)` for the UI confirm flow, registers/clears reminders, validates reminder-scheduled actions (`_validate_reminder_run`, `_format_run_summary`), and re-exports every handler so other modules can `from core.executor import dispatch, resolve_confirmation, _active_reminders`. |
| `core/signals.py` | Module-level `JarvisSignals` `QObject` singleton (`signals`). All cross-thread communication channels (`status_changed`, `error_occurred`, `terminal_line_ready`, `terminal_done`, `workflow_library_changed`, reminder events, etc.) live here so non-Qt code can emit safely. |
| `core/history_store.py` | Thin SQLite wrapper around `data/session_history.db`. Persists session history across restarts and exposes load/append/clear helpers consumed by `main.py` and `ui/history.py`. |
| `core/net_telemetry.py` | Network metrics utilities used by the bottom bar. `probe_internet_rtt()` (ICMP with TCP-:443 fallback, rotating resolvers, platform-aware `ping` flags), `_parse_icmp_time_ms()`, `smooth_rtt_ema()`, `ThroughputSampler` (psutil-based ↑↓ B/s), `format_rate_bps()`. |
| `core/vapi_client.py` | Optional Vapi integration. Registers/syncs a JARVIS assistant configuration (LLM = Claude, TTS = ElevenLabs voice, STT) so the same brain can be reached over web/phone if desired. |

### 5.3 Voice pipeline (`audio_pipeline.py` + `voice.py` facade)

| File | Function |
|---|---|
| `core/audio_pipeline.py` | Low-level audio engine. `AudioCapture` (sounddevice mic stream with VAD + ambient noise calibration + guaranteed `try/finally` cleanup), `SttEngine` (Google SpeechRecognition, returns typed `SttError` enum: `NO_SPEECH`/`NETWORK`/`TIMEOUT`/`DEVICE`), `TtsEngine` (ElevenLabs streaming with pyttsx3 fallback, `is_speaking` threading.Event), `TtsProviderError` + `TtsProviderErrorKind` (`QUOTA`/`AUTH`/`NETWORK`/`UNKNOWN`), `_classify_elevenlabs_error()`, `_EL_VOICES` registry. |
| `core/voice.py` | Thin `VoiceEngine` facade over the audio pipeline. Public API: `say(text)`, `listen()`, `switch_tts_voice(voice, validate_provider=True, persist=True)` (probes ElevenLabs first, rolls back on quota/auth errors), `set_mic_muted()`, `set_tts_muted()`, `is_speaking` property. Owns the overlap guard — `listen()` refuses to open the mic while TTS is speaking. Uses `VoiceBridge` (Qt object) so worker threads can emit signals safely. |
| `core/tts_elevenlabs.py` | ElevenLabs-specific helpers: streaming MP3 playback through Windows MCI (`mciSendString`) for low-latency speech, voice probing for `switch_tts_voice`, and provider error classification. |
| `core/wake_word.py` | Always-on background listener. Uses sounddevice + SpeechRecognition (or the lightweight CMU sphinx fallback) to detect the configured wake word ("jarvis"). On detection, emits a signal that triggers `voice_engine.listen()` in `main.py`. |

### 5.4 OS control + browser

| File | Function |
|---|---|
| `core/computer_control.py` | Cross-platform OS primitives consumed by the handlers. `type_text`, `press_key`, mouse `move`/`click`/`right_click`/`scroll`/`drag` (pyautogui), `screenshot`, `ocr_screen` (Tesseract via pytesseract), `set_volume` (pycaw on Windows), `set_clipboard`/`get_clipboard`, `lock_screen` (Windows `LockWorkStation` via ctypes; OS-specific equivalents elsewhere). Every function returns the standard `{success, output, error}` envelope. |
| `core/browser.py` | Persistent Playwright Chrome session. Singleton `browser` with `start()`/`stop()` (lifetime = JARVIS lifetime), `navigate(url)`, `click_element(selector | text | x,y)`, `fill_form({selector_or_label_or_placeholder: value})`, `read_page()` (title + URL + body up to 4 kB), `extract_content(selector)`, `screenshot_page()`/`screenshot_element(selector)`, `new_tab(url=None)`, `close_tab(match | url_contains | title_contains)`. Also owns advanced browsing: `snapshot()` builds a numbered Playwright accessibility snapshot, `find_and_act(goal, action, value)` asks Haiku (`claude-haiku-4-5-20251001`) to choose a `ref_N`, validates it against `_ref_map`, then acts by `get_by_role(role, name=raw_name)`. Smart-picker failure always falls back to the legacy click/fill chain. |
| `core/automation.py` | `workflow_library` reads/writes `data/workflows.json`. Methods: `add`, `remove`, `rename`, `get`, `list_all`, `set_enabled`, `mark_run`. Emits `signals.workflow_library_changed` so `AutomationView` refreshes automatically. |

#### Advanced Browser Automation

The browser layer now supports an accessibility-tree + LLM picker for vague web actions:

1. `browser.snapshot()` calls Playwright `aria_snapshot()` (or `locator("body").aria_snapshot()` on older versions) and flattens the YAML-ish tree into prompt-safe lines like `button "Sign in" [ref_12]`.
2. Interactive roles (`button`, `link`, `textbox`, `combobox`, `checkbox`, `radio`, `tab`, `switch`, etc.) are emitted before passive nodes. Output is capped by `_MAX_SNAPSHOT_NODES` and accessible names are truncated by `_NAME_TRUNCATE` to reduce prompt size and prompt-injection surface.
3. `self._ref_map` stores both `"name"` (truncated prompt display) and `"raw_name"` (full accessible name for locator attempts), plus `"role"`.
4. `browser.find_and_act(goal, action, value="")` wraps the snapshot in `<accessibility_tree>...</accessibility_tree>` and asks Haiku (`claude-haiku-4-5-20251001`) to return strict JSON: `{"ref": <integer>, "reason": "<short reason>"}`.
5. `_parse_haiku_ref()` accepts integer `12`, string `"12"`, and string `"ref_12"`, then `find_and_act()` validates the number exists in `_ref_map`.
6. Actions use Playwright `get_by_role(role, name=raw_name)` exact then loose matching. Fill actions share `_fill_locator()` (`click` -> `Ctrl+A` -> `Delete` -> `press_sequentially`) so SPA input handlers fire reliably.
7. Every failure path (empty snapshot, missing Anthropic key, timeout/rate limit/API error, malformed JSON, unknown ref, locator miss) falls back to the legacy text/selector fill/click chain rather than failing the command outright.

### 5.5 `core/handlers/` — intent implementations

Each handler matches one or more intent names from `Claude.md`. All return `{success, output, error, needs_confirmation?}` (see `shared._ok`/`_err`).

| File | Intents / actions handled |
|---|---|
| `core/handlers/__init__.py` | Package marker (empty). |
| `core/handlers/shared.py` | Common helpers: `_ok(...)`/`_err(...)` envelopes, `_PendingConfirmation` dataclass + `request_confirmation(label, action, payload)`/`resolve_confirmation(answer)` for the "ask the user first" flow, an in-process cache for the last `browser.read_page()` output (so follow-up "summarise" queries can hit the cache). |
| `core/handlers/paths.py` | Filesystem path resolver. For relative paths it first searches under `Path.home()` (common locations, then a bounded walk pruning `node_modules`/`.git`/etc., shallowest match wins, Documents preferred). For new paths it roots under `JARVIS_DEFAULT_CREATE_PARENT` (`documents` \| `desktop` \| `downloads` \| `home`, default Documents). Also generates suggested save paths for screenshots and stripped-trailing-`.keep` fallbacks. |
| `core/handlers/app_launcher.py` | `open_app` (`open_browser`, `open_vscode`, `open_terminal`, `open_file_manager`, `open_spotify`, `open_url`, `open_app_generic`), `close_app`/`force_quit`. Supports Windows aliases/AppIds/protocols, `subprocess`, `webbrowser`, and delegation to `core.browser` when the persistent Chrome session is preferred. |
| `core/handlers/input_control.py` | `type_text` (`type_text`, `type_paste`, `press_key`) and `control_mouse` (`move_mouse`, `click`, `double_click`, `right_click`, `scroll`, `drag`). Thin pass-through to `core/computer_control.py`. |
| `core/handlers/system.py` | `system_control` — `volume_up`/`down`/`mute` (step or absolute via `level`), `brightness_up`/`down`, `screenshot`, `lock_screen`, `wifi_toggle`/`bluetooth_toggle` (Windows PowerShell), `shutdown`/`restart`/`sleep` (each goes through `request_confirmation`). Distinguishes `sleep` (suspend) from `shutdown` (power-off) per `Claude.md`. |
| `core/handlers/file_ops.py` | `file_operation` — `create_file`/`create_directory`, `read_file`, `delete_file` (confirmed), `rename_file` (`path` + `new_name`), `move_file`, `copy_file`, `list_directory`, `search_files` (recursive when `pattern="*"`). Streams progress to the terminal via `signals.terminal_line_ready`. Path-resolves via `paths.py`. UI-level confirmation is used for create_file/create_directory (one prompt, not two). |
| `core/handlers/code_exec.py` | `code_execution` — `run_python`, `run_shell`, `run_powershell` (`powershell.exe`), `run_cmd` (`cmd.exe /c`), `run_script`, `git_command`, `npm_command`, `install_package` (pip/npm/uv), `run_background` (detached PID-returning launch), `kill_process` (by PID or partial name; confirmed). Detects dangerous shell patterns and asks before running. Uses Claude Haiku for natural-language → command translation and error explanation. Holds command output blocks (`_BLOCK_STORE`) so multi-step plans can reference earlier results. |
| `core/handlers/browser_handler.py` | `browser_automation` — `navigate`, `click_element`, `fill_form`, `read_page`, `extract_text`, `screenshot`, `new_tab`, `close_tab`. Starts the persistent browser on demand. `click_element` routes explicit `goal` to `browser.find_and_act(goal, "click")`; vague selector + text uses the smart picker first, then legacy fallback. `fill_form` routes `goal` + `value` to `find_and_act(goal, "fill", value)`; normal `fields` dict behavior remains unchanged. |
| `core/handlers/screen_handler.py` | `read_screen` — `ocr_full`, `ocr_region`, `ocr_active_window`, `find_element`. Delegates to `core.computer_control.ocr_screen`. |
| `core/handlers/automation_handler.py` | `automation_task` — `run_workflow` (resolves a saved `task_name` from `workflow_library` **or** runs inline `steps[]`), `create_workflow`, `list_workflows`, `remove_workflow` (confirmed), `rename_workflow`. Multi-step execution yields back to the UI between steps (`_yield_ui`) and resumes automatically after each in-step confirmation card is answered. Safety filter blocks dangerous nested steps. |
| `core/handlers/reminders.py` | `reminder_task` — `set_reminder` (`message`, `delay_seconds` ≥ 5, `repeat`, optional scheduled action validated against an allow-list), `cancel_reminder`, `list_reminders`. `threading.Timer`-based registry exposed as `executor._active_reminders` for the status popover. Fires `signals.status_changed` when a reminder triggers. |
| `core/handlers/weather.py` | `weather` → `get_current_weather`. Formats the snapshot returned by `core/integrations/weather.py`. |
| `core/handlers/meta.py` | `jarvis_meta` — `tell_time`, `tell_date`, `status_report` (CPU/RAM via psutil + battery when sensor present), `list_voices`, `change_voice` (calls `voice_engine.switch_tts_voice`), `who_are_you`, `tell_joke`, `conversational`, `help`, `quit_application`/`close_jarvis` (graceful TTS-then-exit). |

### 5.6 `core/controllers/` — UI-facing coordination

| File | Function |
|---|---|
| `core/controllers/__init__.py` | Re-exports the controller classes used by `main.py`. |
| `core/controllers/command_controller.py` | Parses incoming command strings, detects repeat phrases (`"do that again"`), and recognises the internal `__run_workflow_id__:<id>` token emitted by `AutomationView` ▶ buttons so it can bypass Claude and call the workflow directly. |
| `core/controllers/confirmation_controller.py` | Standardised confirm/cancel prompts, display response strings, and HUD status labels for the confirmation flow. |
| `core/controllers/response_composer.py` | Composes the final spoken response by combining Claude's `response` field with optional executor follow-ups (success summary, error explanation) produced by `ResponseAssembler`. |
| `core/controllers/runtime_context.py` | Tracks recent runtime context (previous command, last Python file path, last working directory) and packs it into the `context` block sent to Claude so follow-up commands like *"run it"* resolve correctly. |
| `core/controllers/session_flags.py` | Syncs and persists session toggle state (mic mute, TTS mute, auto-confirm, dim mode, wake word enabled) across the topbar popover, the settings page, and `config/jarvis.json`. |

### 5.7 `core/responders/` — spoken response assembly

| File | Function |
|---|---|
| `core/responders/__init__.py` | Re-exports `ResponseAssembler`. |
| `core/responders/assembler.py` | `ResponseAssembler` turns each executor result into a structured `{primary_tts, follow_tts}` pair, branching on intent/action and success/failure. Pulls phrasings from `core/personality.py` and uses `utils.py` for compaction. |
| `core/responders/utils.py` | Speech-formatting helpers: `filename`, `domain`, `count_ok_steps`, `first_sentence`, `compact_path_for_speech`, `compact_url_for_speech`, `speech_compact`, `tts_safe_output`, `traceback_summary`, plus tag-sets `_OUTPUT_IS_RESPONSE` / `_SUPPRESS_FOLLOW` that mark intents where the raw output already is the spoken reply (e.g. `tell_time`) or where a follow-up would be redundant. |

### 5.8 `core/integrations/` — external services

| File | Function |
|---|---|
| `core/integrations/__init__.py` | Package marker. |
| `core/integrations/weather.py` | OpenWeather client. Reads `config.openweather_api_key` + `config.weather_default_city`, calls the current-weather endpoint via `urlopen`, parses the payload, and returns a `{location, country, description, condition, temp_c, feels_like_c, humidity, wind_mps}` snapshot. |

---

## 6. `ui/` — PyQt5 HUD

### 6.1 Theme and shared widgets

| File | Function |
|---|---|
| `ui/__init__.py` | Package marker. |
| `ui/theme.py` | Single source of truth for colour tokens (Mark-LXXXV cyan `#00E5FF` over `#080A0A`), font role registry (Space Grotesk / Inter / Roboto Mono), sidebar/topbar/bottombar widths, semantic tokens (`TEXT_MUTED`, `IDLE_CYAN`, `BG_PANEL`), global QSS (`app_stylesheet`, `tooltip_qss`), font loader (`load_jarvis_fonts`), logo helpers (`jarvis_logo_pixmap`, `jarvis_logo_icon`). |
| `ui/helpers.py` | Reusable layout factories: `PanelFrame`, `MetricCard`, `MetricCell`, `QuickActionBtn` with hover-glow animations. |
| `ui/widgets.py` | The big shared-widget toolbox. `_mono()` font helper, `_panel_header()` factory, `GlassPanel` re-export, `ModuleIDLabel`, `StatusPip` (active/standby/error pulse), `SegmentedBar`, `ScanLineOverlay`, `LineChartWidget`, `ArcReactorWidget` (Mark-LXXXV reactor: dashed outer ring, armor band, spokes, glowing core with state-coloured pulse), compat aliases (`OrbWidget`, `SparklineWidget`), `AnimatedLabel`, `WaveformStrip`, `ConfidenceGauge`, `ToggleSwitch`, `MicButton`, `GreetingCard`, `TypingIndicator`, `_TagHighlighter` + `_TagLineEdit` (`@tag` highlight + autocomplete popup, Enter = submit, Shift+Enter = newline), `CommandBar`, `HudStatusLabel`, `LastActionStrip`, `ToastNotification`, `ConfirmationBar`. |

### 6.2 Chrome (sidebar + bars + popovers + palette)

| File | Function |
|---|---|
| `ui/sidebar.py` | `HudSidebar` — fixed 128-px column with `STARK_OS / MARK_LXXXV` brand, six nav items (`SYSTEM`, `VOICE`, `AUTOMATE`, `HISTORY`, `CONFIG`, `TERMINAL`) using Phosphor icons (`qtawesome ph.*`), and a `DIAGNOSTICS` footer. Emits `nav_changed(int)` mapped to `QStackedWidget` indices. Paints its own right-edge glow so it lines up pixel-for-pixel with the topbar's bottom glow underline. |
| `ui/bars.py` | `TopBar` (logo + `HUD_STATUS_V4.2` brand, live `CPU` / `MEM` / `UPTIME`, Wi-Fi arcs, phone-style battery glyph with charge bolt, three trailing icon buttons that emit `settings_clicked` / `terminal_clicked` / `broadcast_clicked`, `battery_alert(message, kind)` signal at 20 % and full charge). `BottomBar` (`SYSTEM ONLINE` pill, `PING …ms` via `_RttWorkerThread` + EMA smoothing, `NET ↑/↓` via `ThroughputSampler`, command counter, current view name). Also exposes `draw_glow_underline` / `draw_glow_right_edge` reused by the sidebar. |
| `ui/popovers.py` | Two anchored `Qt.Popup` dropdowns. `QuickSettingsPopover` (toggle rows for `MUTE_MIC`, `MUTE_TTS`, `AUTO_CONFIRM` (warned), `DIM_MODE`, `WAKE_WORD`; `OPEN FULL SETTINGS →` footer) with `sync_state(...)` and `show_below(anchor)`. `SystemStatusPopover` (read-only live health: Claude API, ElevenLabs TTS, Google STT, Browser session, Active reminders, Wake word) — refreshes on every open. |
| `ui/command_palette.py` | `CommandPalette` — full-window modal overlay opened via Ctrl+K or the topbar terminal icon. Centered glass frame with `_TagLineEdit`, recent-command chips (`_RecentChip`, click to refill), Esc/click-outside to dismiss, dim backdrop. |

### 6.3 Views (one per stacked page)

| File | Function |
|---|---|
| `ui/dashboard.py` | `DashboardView` (stack index 0). Three columns: `_SysLogPanel` (live `TranscriptPanel` rendered through `_TypewriterProxy` for animated user/JARVIS typing), `_CenterPanel` (`ArcReactorWidget` + `StateLabel` reflecting `idle`/`listening`/`thinking`/`speaking`/`error`/`wake`), `_RightTelemetry` (`_CpuCard` with live psutil chart + threshold, `_MemCard`, `_UplinkCard` with TX/RX), plus a centered `_CommandStrip` containing the mic button, voice waveform, and `CommandBar`. Paints its own dotted grid + radial halo background and re-positions the toast notification on resize. |
| `ui/voice.py` | `VoiceView` (stack index 1). VOICE_CORE: page header, `_StatusStrip` (mic state, router, pipeline, last confidence), main body splits into `_TranscriptTimeline` (HTML rich-text history with SYS/USER/JARVIS lines) and `_CommandInspector` (`StateLabel`, `WaveformStrip`, large `_PageMicButton` with pulse ring, intent/action/confidence/status fields). Bottom `EXECUTION LOG` (`TerminalLog`). Exposes `set_state`, `update_transcript`, `set_execution`, `set_pending`/`clear_pending`. |
| `ui/views/automation/view.py` | `AutomationView` (stack index 2). AUTOMATION_CORE: workflow library list (left) + step breakdown (right) + execution log (bottom). Add/edit/delete dialogs, ▶ run buttons emit `__run_workflow_id__:<id>` tokens for `command_controller`. Re-renders on `signals.workflow_library_changed`. |
| `ui/views/automation/components.py` | `WorkflowRow` (pip + name + trigger + step count + ON/OFF toggle + ▶ run + ✕ delete), `StepBreakdown` (right panel showing meta + numbered step list), `step_label()` helper. |
| `ui/views/automation/dialogs.py` | `GlassDialog` base (frameless draggable JARVIS-themed modal), `NewWorkflowDialog` (used for both new + edit — name, trigger, multi-line steps editor with live counter), `ConfirmDeleteDialog` (amber warning). |
| `ui/views/automation/__init__.py` | Re-exports the automation view package. |
| `ui/automation.py` / `ui/automation_components.py` / `ui/automation_dialogs.py` | **Compatibility shims** that re-export the symbols from `ui/views/automation/*`. Kept so older imports do not break. |
| `ui/history.py` | `HistoryView` (stack index 3). COMMAND_LOG: three `_StatCard`s (`TOTAL COMMANDS`, `AVG CONFIDENCE`, `SESSION UPTIME` — uptime ticks independently), `_FilterBar` with debounced search, `_LogTable` (scrollable `_LogRow` list with intent + confidence colouring), `_IntentBreakdown` (top intents by frequency via `Counter`). `CLEAR HISTORY` emits `history_cleared`. |
| `ui/settings.py` | `SettingsView` (stack index 4). SYSTEM_CONFIG: `_HealthStrip` (Anthropic/ElevenLabs/Browser pills with live refresh), API key inputs (masked, `.env` only), model + voice + theme combos, debug toggle, session flags (mic/TTS/auto-confirm/dim/wake-word), mic sensitivity slider, TTS speed slider, noise-gate toggle, mic input device picker (from sounddevice). `APPLY_CFG` calls `config.save()` and triggers `voice_engine.switch_tts_voice(...)` with rollback on provider failure. Emits per-flag signals so `main.py` and `QuickSettingsPopover` stay in sync. |
| `ui/views/__init__.py` | Package marker for the view subpackages. |

### 6.4 Components (reusable surfaces)

| File | Function |
|---|---|
| `ui/components/__init__.py` | Package marker. |
| `ui/components/panels.py` | `GlassPanel` — semi-transparent rectangle with cyan corner brackets, hand-painted border, swap-able fill colour. Base for every card/panel in the app. |
| `ui/components/transcript.py` | `InlineConfirmCard` (pulsing dashed border, `[CONFIRM]` + `[CANCEL]` HUD buttons, random wait line for TTS), `TerminalLog` (read-only QTextEdit with blinking block cursor), `TranscriptPanel` (the conversation view — rows of `[time] YOU:` / `[time] JARVIS:` with intent/conf tag, "load more / show less" for long responses, embedded `InlineConfirmCard`). |
| `ui/components/terminal.py` | `TerminalPanel` (stack index 5). JARVIS Shell v2 — header, output `QTextEdit` with colour-coded lines (stdout cyan, errors red, success green, system warning amber, command echo white), `❯` prompt input with Up/Down history navigation, Ctrl+L to clear, emits `command_submitted("@code <text>")` so input flows through the standard code-execution intent. Consumes `signals.terminal_line_ready` + `signals.terminal_done`. |
| `ui/components/typewriter.py` | `_TypewriterProxy` — wraps `TranscriptPanel` so user speech types at 20 ms/char, JARVIS responses at 25 ms/char, with animated `Thinking.../../../` placeholder while the brain is working. Forwards every other attribute to the underlying panel. |

---

## 7. `tests/` — verification harness

A mix of pytest-style unit tests and interactive runners. Run individual tests via `uv run python tests/<file>.py` or `uv run pytest tests/`.

| File | Style | What it verifies |
|---|---|---|
| `tests/test_browser.py` | Interactive menu | Manual smoke tests for every `core.browser` method: start, navigate (with/without scheme, bad URL), read_page, extract_content, click by selector/text, fill_form, screenshot_page, new_tab, close_tab, stop. |
| `tests/test_executor.py` | Interactive menu | Live executor calls for every major intent: open_app/close_app, search_web (Google + YouTube), file CRUD (with confirm flow), mouse right-click/scroll/drag, jarvis_meta tell_time / tell_date / status_report, reminder_task with a 10 s sleep. |
| `tests/test_computer_control.py` | Interactive menu | Clipboard, keyboard, screenshot, OCR, mouse move, volume up/down. |
| `tests/test_net_telemetry.py` | pytest unit | `format_rate_bps`, `smooth_rtt_ema`, `_parse_icmp_time_ms`, `ThroughputSampler` first-sample sentinel. |
| `tests/test_reminder_scheduled.py` | pytest unit | `_validate_reminder_run` allow-list + `_format_run_summary` text. |
| `tests/test_voice_switch.py` | unittest | `_classify_elevenlabs_error` quota detection + `voice_engine.switch_tts_voice` rollback when the provider probe raises. |
| `tests/test_workflow_nlu.py` | unittest | `parse_create_workflow_command` for multi-line routines, non-creation rejection, and Windows-path + after-clause handling. |
| `tests/test_weather.py` | pytest + monkeypatch | `get_current_weather` payload parsing, `_handle_weather` success + unknown-action + missing-key cases. |

---

## 8. `assets/` — visual references and brand mark

| Path | Function |
|---|---|
| `assets/jarvis_logo.svg` | Hex reactor mark; used by `jarvis_logo_pixmap()` for the window icon and topbar logo. |
| `assets/reference/jarvis_main_hud.html` | Reference design for the Dashboard. |
| `assets/reference/jarvis_execute_command_center.html` | Reference design for the Voice page. |
| `assets/reference/jarvis_network_telemetry.html` | Reference design for telemetry surfaces. |
| `assets/reference/jarvis_system_diagnostics.html` | Reference design for diagnostics. |
| `assets/reference/system_telemetry_settings.html` | Reference design for Settings. |

Use these HTML mocks as the visual ground truth when running the `/impeccable …` workflow from `IMPECCABLE_SKILL_GUIDE.md`.

---

## 9. Runtime flow (one command, end to end)

1. **Input arrives.** Wake-word listener (`core/wake_word.py`) → `voice_engine.listen()` (STT) **or** the user types in `CommandBar`/`CommandPalette`/`TerminalPanel`.
2. **Pre-routing.** `command_controller` checks for repeat phrases or `__run_workflow_id__:` tokens. `workflow_nlu.parse_create_workflow_command` short-circuits unambiguous routine creation.
3. **Brain.** `core/brain.py` strips `@tags` → builds the context block → sends to Claude with `Claude.md` as the system prompt → parses the strict JSON → applies tag override → returns the routed intent dict.
4. **State → "thinking".** `main.py` updates HUD via `signals.status_changed` so the reactor pulses, the Voice page shows `PROCESSING`, and the topbar logs the directive.
5. **Confirmation gate.** If `requires_confirmation` and not `auto_confirm`, `ConfirmationBar` / `InlineConfirmCard` is shown; `executor.resolve_confirmation(answer)` resumes or cancels.
6. **Executor.** `core/executor.dispatch(...)` routes to the matching `core/handlers/*` function. Handlers may stream output lines through `signals.terminal_line_ready` and exit codes through `signals.terminal_done`.
7. **Advanced browser action (only for browser clicks/fills).** `core/handlers/browser_handler.py` may route vague `click_element` / `fill_form` requests into `browser.find_and_act(...)`: snapshot accessibility tree -> Haiku picks a validated `ref_N` -> Playwright acts by role/name -> legacy click/fill fallback if anything fails.
8. **Response composition.** `ResponseAssembler` (`core/responders/assembler.py`) + `core/personality.py` build a structured `{primary_tts, follow_tts}` reply, compacted for speech by `core/responders/utils.py`.
9. **State → "speaking".** `voice_engine.say(...)` streams ElevenLabs MP3 through MCI (with pyttsx3 fallback). The overlap guard prevents the mic from re-opening mid-speech.
10. **Persist.** Entry appended to in-memory history and `core/history_store.py` (SQLite). `HistoryView` refreshes; `BottomBar.increment_commands()` ticks.
11. **State → "idle".** Reactor settles, status pill returns to `STANDBY`.

---

## 10. Cross-cutting patterns

- **One source of truth for prompt.** `Claude.md` defines every intent, action, parameter, confirmation rule, and HUD label. Python guards in handlers enforce the same rules so a misbehaving model cannot bypass safety (e.g. reminder allow-list, danger detection in `code_exec`, confirmation gates for destructive ops).
- **Two-tier confirmation.** Some actions (`shutdown`, `restart`, `sleep`, `delete_file`, `force_quit`, `kill_process`, `remove_workflow`) set `requires_confirmation: true` in the JSON; others (`create_file`, `create_directory`) confirm in-app via `request_confirmation` only. `auto_confirm` short-circuits both paths.
- **Threading discipline.** All blocking work lives off the GUI thread. Cross-thread communication uses **only** the `signals` singleton in `core/signals.py`. Worker threads never touch QWidgets directly.
- **Single state machine.** `main.py._set_state("idle"|"listening"|"thinking"|"speaking")` fans out to `DashboardView`, `VoiceView`, `BottomBar`, and `ArcReactorWidget.set_state`. Every UI surface reads the same state.
- **Style discipline.** `ui/theme.py` is the only place colours/fonts/sizing are defined. `ui/widgets._mono()` and `_panel_header()` are the only sanctioned font/header factories. The topbar glow underline + sidebar right-edge glow are painted with identical parameters so they read as one continuous border.
- **Brand fidelity.** `PRODUCT.md` rules out chat-bubble UI, generic-assistant phrasing, and rounded corners. The arc reactor, hex logo, segmented armor band, and `STARK_OS / MARK_LXXXV` brand are non-negotiable visual anchors. Spoken responses follow the British-butler tone from `Claude.md`.
- **Path resolution discipline.** Relative paths always resolve under the user's profile, never the JARVIS process CWD. Default create parent is configurable via `JARVIS_DEFAULT_CREATE_PARENT`. Path resolver is centralised in `core/handlers/paths.py`.
- **Advanced browsing is fail-soft.** The accessibility-tree/Haiku picker is an enhancement for vague browser clicks/fills, not a replacement for selectors. It treats page text as untrusted, validates returned refs against `_ref_map`, uses `raw_name` for locator attempts, and falls back to legacy selector/text logic on any failure.
- **Fail-soft everywhere.** Every handler returns `{success, output, error}`; brain failures fall back to `{"intent": "unknown"}`; voice provider failures roll back to the previous voice; browser failures surface to the Settings health strip without crashing the app; status popover wraps every subsystem probe so one failure cannot stop the others rendering.

---

## 11. Where to make common changes

| You want to… | Edit |
|---|---|
| Add a new intent | (1) Append to `Claude.md` definitions. (2) Add a handler in `core/handlers/<name>.py`. (3) Register it in `core/executor.py` `dispatch`. (4) Add response templates in `core/personality.py` and (if needed) `core/responders/assembler.py`. (5) Add a `tests/test_<name>.py` case. |
| Add a new `@tag` | Update `TAG_INTENT_MAP` in `core/brain.py` **and** the `@Tag → Intent Reference` table in `Claude.md`. |
| Change the HUD colour palette | `ui/theme.py` `COLORS` + the semantic aliases (`PRIMARY`, `CYAN`, `IDLE_CYAN`, …). |
| Add a new page to the stack | Build a `QWidget` view in `ui/`, add a sidebar entry in `ui/sidebar.NAV_ITEMS`, extend `_NAV_TO_STACK`, append it to the `QStackedWidget` in `main.py`. |
| Add a new system status pill | `ui/popovers.py` `SystemStatusPopover._row_*` + a probe in `refresh()`. |
| Persist a new user preference | Add a field to `AppConfig` in `config/settings.py`, expose a control in `ui/settings.py`, mirror through `core/controllers/session_flags.py`, and (if relevant) `ui/popovers.QuickSettingsPopover`. |
| Change voice behaviour | `core/voice.py` + `core/audio_pipeline.py` + `core/tts_elevenlabs.py`. Voice registry lives in `_EL_VOICES`. |
| Change advanced browser element picking | `core/browser.py` (`snapshot`, `_parse_haiku_ref`, `find_and_act`, `_exec_click_by_role`, `_exec_fill_by_role`) and `core/handlers/browser_handler.py` (routing heuristics for `goal`, vague selectors, and fill values). Keep legacy fallback intact. |
| Add a workflow safety rule | `core/handlers/automation_handler.py` (dangerous step filter) + `core/handlers/reminders._validate_reminder_run` (scheduled action allow-list). |

---

## 12. Glossary

- **HUD** — Heads-Up Display; the PyQt window itself.
- **Reactor** — The Mark-LXXXV arc reactor widget at the center of the Dashboard. Its colour reflects the current state.
- **Intent / action / parameters** — The three-part contract Claude returns. Intent = category (`open_app`), action = specific behaviour (`open_browser`), parameters = action-specific kwargs.
- **Pending confirmation** — A handler that returned `needs_confirmation=True`. Resolved by `core/handlers/shared.resolve_confirmation("yes"|"no")` driven from the UI confirm card.
- **`@tag`** — User-typed prefix (e.g. `@browser do X`) that forces a specific intent regardless of NLP inference. Stripped before reaching Claude; intent override carried in `context.tag_override`.
- **`__run_workflow_id__:<id>`** — Internal token emitted by the automation ▶ button so the command_controller can dispatch the workflow directly without re-running Claude.
- **Glass panel** — The standard cyan-bracketed semi-transparent rectangle used for every card and modal.
- **STARK_OS / MARK_LXXXV** — Brand strings in the sidebar identifying this iteration of the system.

---

*Maintained by Malakai V. Weah. Keep this file in sync with `Claude.md`, `PRODUCT.md`, and the actual file tree — it is the orientation document every new contributor (human or agent) reads first.*
