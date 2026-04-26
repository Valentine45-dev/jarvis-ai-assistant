# JARVIS Project Handoff
**Developer:** Malakai V. Weah  
**Project path:** `C:\Users\Dell Latitude Touch\Desktop\jarvis-project`  
**Stack:** Python 3.14, PyQt5, Claude API (Sonnet 4), ElevenLabs TTS, Google STT, Playwright  
**Package manager:** `uv`  
**Run command:** `uv run python main.py`

**Brain prompt:** `CLAUDE.md` (or `Claude.md` on case-insensitive systems) — loaded by `core/brain.py`

### Session 2026-04-27 — Architecture hardening, background threads, live telemetry, workflow UI

**Changes shipped in this session — quick reference:**

| File | What changed |
|------|--------------|
| `main.py` | Phase 1: `_PendingConfirmation` dataclass, history `status` field, `_HISTORY_MAX`, `_TTS_MAX_CHARS`, amber auto-confirm banner, history persistence startup/save/clear, `import threading` |
| `main.py` | Phase 2: `_exec_done` signal, `_execute_result` forks multi-step workflows to daemon thread, `_on_exec_done`, `_finish_execute` split |
| `main.py` | Phase 3: `Win+J` global hotkey → `_summon_window()` |
| `core/brain.py` | Token guard: `_infer_max_output_tokens` requires both creation verb AND file extension for 16k |
| `core/browser.py` | `_not_ready()` auto-restarts once via `_recover()` before returning an error |
| `core/executor.py` | `_PendingConfirmation` dataclass (typed, UUID id), replaces bare `_PENDING` dict |
| `core/history_store.py` | **New** — SQLite history persistence (`data/session_history.db`, WAL, thread-safe) |
| `ui/dashboard.py` | `_UplinkCard`: live TX/RX via `psutil.net_io_counters()` every 2 s, feeds sparkline |
| `ui/automation.py` | `+ NEW` button in library header, `_NewWorkflowDialog`, `_create_workflow()` method |
| `ui/history.py` | `history_cleared = pyqtSignal()`, emitted from `_on_clear()` |
| `.gitignore` | Added `data/session_history.db`, `data/session_history.json` |

---

## How to Test — Session 2026-04-27 Changes

Run JARVIS first: `uv run python main.py`

---

### 1 — History persists across restarts

**What it tests:** `core/history_store.py` + SQLite at `data/session_history.db`.

```
1. Run JARVIS. Issue any command (e.g. "What time is it?").
2. Close JARVIS normally (X button or "Close JARVIS").
3. Re-launch with `uv run python main.py`.
4. Open the History view (sidebar → HISTORY).
5. Your previous command should appear in the list.
```

Expected: history survives across restarts. The DB file `data/session_history.db` will be created on first run (gitignored).

---

### 2 — Auto-confirm banner (amber warning)

**What it tests:** persistent visual warning when auto-confirm is active.

```
1. Click the sliders icon in the TopBar (Quick Settings popover).
2. Toggle AUTO-CONFIRM on.
3. An amber banner should appear between the TopBar and the content area:
   "⚠  AUTO-CONFIRM ACTIVE — DESTRUCTIVE ACTIONS WILL EXECUTE WITHOUT PROMPT"
4. Toggle AUTO-CONFIRM off → banner disappears.
```

---

### 3 — Background workflow execution (UI stays responsive)

**What it tests:** `_execute_result` forks `automation_task`+`run_workflow`+`steps` to a daemon thread.

```
1. Type a multi-step command, e.g.:
   "Open Notepad and take a screenshot"
   — or —
   "Search YouTube for Iron Man and search Google for Python"
2. While JARVIS processes:
   - The status label should read "Running workflow — please wait…"
   - The window should NOT freeze — you can still click the sidebar, scroll, etc.
3. After execution, the HUD, transcript, and history should update normally.
```

If you had the old code, multi-step workflows would lock the Qt event loop (the window would be unresponsive until done). With this change, everything stays live.

---

### 4 — UPLINK real TX/RX throughput

**What it tests:** `_UplinkCard._tick_net()` via `psutil.net_io_counters()`.

```
1. On the Dashboard (default view), look at the bottom-right panel: UPLINK_STATUS.
2. TX (Mb/s) and RX (Mb/s) should show real numbers (initially near 0 if idle).
3. To see them change: say "Open YouTube" or start a download in any app.
4. Within 2 seconds, the RX number should spike and the sparkline should update.
```

Old value: hardcoded "452.1" / "1208.4" — frozen decorative. New value: real sampled throughput.

---

### 5 — Win+J global summon hotkey

**What it tests:** `Meta+J` QShortcut → `_summon_window()`.

```
1. Launch JARVIS.
2. Click on any other window (e.g. a browser, Notepad) so JARVIS loses focus.
3. Press Windows key + J.
4. JARVIS should come to the foreground and be activated.
```

Note: `Meta` = Windows key in Qt on Windows. This only works while JARVIS is running (it's an in-app shortcut, not a system-level hotkey daemon).

---

### 6 — Create Workflow UI

**What it tests:** `_NewWorkflowDialog` + `+ NEW` button in Automation view.

```
1. Navigate to Automation (sidebar → AUTOMATION).
2. In the WORKFLOW LIBRARY panel header, click "+ NEW".
3. A dialog appears with two fields:
   - WORKFLOW NAME  (e.g. "Morning Routine")
   - TRIGGER PHRASE (e.g. "run morning routine")
4. Fill them in and click OK.
5. The new workflow should appear immediately in the library list.
6. The execution log should show: "[SYSTEM] Workflow 'Morning Routine' created."
7. The workflow starts with 0 steps (skeleton). Run it via voice: "Run morning routine"
   — it will complete instantly with nothing to do (add steps via CLAUDE.md / voice later).
```

---

### 7 — History clear syncs to DB

**What it tests:** `history_cleared` signal + `main._on_history_cleared()`.

```
1. Run JARVIS and issue a few commands.
2. Navigate to History view → click "CLEAR HISTORY".
3. The list should empty.
4. Restart JARVIS — the history should still be empty (DB was cleared too).
```

---

### 8 — TTS truncation guard

**What it tests:** `_TTS_MAX_CHARS = 800` in main.py.

```
1. Say: "Read what's on this page" (while browser is open on a content-heavy page).
2. JARVIS should speak a truncated version of the page (ending with "…") rather than
   reading thousands of characters (which would timeout or burn ElevenLabs quota).
3. The transcript panel shows the FULL text; only the TTS clip is truncated.
```

---

### 9 — Claude token guard

**What it tests:** `_infer_max_output_tokens` in `brain.py` — only uses 16k when creating a file.

```
- "Create a Python file called utils.py" → uses 16k output tokens (content needed)
- "What is my utils.py file doing?" → uses standard 1024 tokens (read question, no content)
- "What file should I create?" → standard tokens (no creation verb + extension)
```

No UI indicator for this — just cost/speed. Verify in `core/brain.py` logs if needed.

---

### Session 2026-04-26 — Post-action follow-up (normal commands, not only timers)

- **Goal:** For **immediate** commands, the user hears **Claude’s `response` first** (primary line), then a **short JARVIS-style “done” line** after the first audio clip **finishes** — same *tone/pools* as timer completions (`ack_scheduled_action`), e.g. *“There you go — it’s open, sir.”* / *“…results are up, sir.”* **Multi-clause** workflows (e.g. *open Chrome and search X*) get the follow-up phrased for the **last successful step** when possible.
- **`core/personality.py`:** **`action_speech_pair(..., last_step=None)`** returns **`(primary: str, follow: str | None)`**. **Full listings / OCR / `read_page` / code output** use **`_NO_TRIM`** and stay **one TTS** (no chaser, so the body isn’t trailed by a redundant *“all set”*). **`build_response(...)`** joins **`primary` + `follow`** for display strings where a single field is still useful.
- **`core/executor.py`:** On successful **`automation_task` + `run_workflow`**, the result dict may include **`last_step_intent`** and **`last_step_action`** (from the last **successful** step) so the follow-up line matches that intent/action, not the generic automation label.
- **`core/voice.py`:** **`say(text, on_ready=…, on_done=…)`** — **`on_done`** after playback **ends** (stream + non-stream MCI paths, **pyttsx3** fallback). If **TTS is muted**, **`on_ready`** and **`on_done`** still fire in order so the UI does not hang.
- **`main.py`:** First clip: **`on_ready` → `_tts_ready` → `update_last_jarvis(primary)`** (unchanged). If **`follow`**: **`on_done`** (worker thread) **`emit`s `_action_followup_tts` → `Qt.QueuedConnection` → `_on_action_followup_tts`**, which **`append_jarvis_scheduled`**, merges **`jarvis` in `_history`**, refreshes the History card, and **`voice_engine.say(follow)`**. **`_transcript_update_token`** invalidates a pending follow-up if a **new** command runs first. **Action reminders** (`_on_reminder_action`) still call **`ack_scheduled_action`** for their **single** completion line.
- **`ui/voice.py`:** **`append_jarvis_continuation(...)`** appends a second JARVIS row on the Voice timeline without duplicating the user line.
- **Removed (superseded):** speaking **`run_workflow`** step text via **`_flatten_workflow_output_for_tts`** as the *only* TTS — the primary is again Claude’s short **`response`**; facts remain in executor **`output` / UI**, not a long flatten read aloud.

---

## What Was Built

JARVIS (Just A Rather Very Intelligent System) — an Iron Man-style voice AI desktop assistant with a full PyQt5 HUD, Claude API brain, ElevenLabs voice, and real OS/browser control.

### Session 2026-04-26 — Top bar battery + Wi‑Fi

- **File:** `ui/bars.py`
- **Battery:** Mobile-style **glyph** (rounded body, right terminal, fill level) plus **`NN%`** text immediately to the right, placed after **UPTIME** in the center stat strip. **Fill colour:** low (<20%) **amber/orange**; on **AC** **emerald**; otherwise **HUD cyan** (`CYAN` from `ui/theme.py`). When **AC / charging** (`power_plugged`), a small **white lightning bolt** is drawn **on top**, centered on the upper edge of the battery (overlaps the outline slightly), like phone status bars. **Source:** `psutil.sensors_battery()`. The whole block is **hidden** when the OS reports no battery (typical **desktop** tower).
- **Wi‑Fi:** Custom **3-arc + dot** icon in the same strip; **shown only** when a **data-capable** Wi‑Fi path is detected: **(1)** a wireless-like interface (name matches `wi-fi` / `wlan` / `wireless` / `wlp` / etc.) is **up** and has a **non–link-local IPv4**, or **(2)** on **Windows** `netsh wlan show interfaces` matches `State : connected` (covers naming quirks). **Hidden** on Ethernet-only or offline.
- **Update cadence:** same **1s** `QTimer` as MEM/UPTIME (`TopBar._tick`).

### Session 2026-04-26 — Dashboard directive field (height cap + scroll) + `press_key` aliases

- **`ui/widgets.py` (`_TagLineEdit`):** Multi-line directive field **stops growing** after a small cap (**`_H_MAX` = 108px**), then **overflow scrolls** (`ScrollBarAsNeeded` when content exceeds the cap). **`QTextEdit.WidgetWidth`** line wrap (was `NoWrap`). **`resizeEvent`** calls `_reflow_height` so wrapped line count updates when the field is resized. **`contentHeightChanged`** emits **`self.height()`** after layout.
- **`ui/dashboard.py` (`_InputBlock`):** Input card height **capped** (`min(..., 160)` for `INPUT_H`, down from 220) to match the editor behaviour. **Bug fix:** **`_CommandStrip`** only called `setFixedHeight` once in `__init__`; when the block grew, the strip stayed short and layout broke. **`_on_input_editor_height`** now sets **`parent().setFixedHeight(self.height())`** so the strip tracks the block whenever the editor height changes.
- **`core/computer_control.py`:** **`_normalize_key_token()`** maps natural names (e.g. **`windows` → `win`**, **`winkey` → `win`**, **`lwin`/`rwin` → `winleft`/`winright`**) before **`press_key`** calls PyAutoGUI **`hotkey`** / **`press`**, so STT/brain output like `windows+m` works. **Win+M** (minimise all) needs the brain to route **`type_text` + `press_key`** with a combo such as `win+m`, not **`control_mouse`**; phrasing *“click Win+M”* can mis-route to mouse — prefer *press* / *send* or **`@type`**.

### Session 2026-04-26 — Tooltips (readability) + bottom bar PING + NET speed

- **`ui/theme.py`:** **`tooltip_qss()`** — global **`QToolTip`** QSS: readable **`on_surface`** text on **`surface_container`** background, cyan border, 11px, padding. **`main.py`:** set **`QPalette.ToolTipBase` / `ToolTipText`**, then **`app.setStyleSheet(tooltip_qss())`** (Fusion’s defaults were nearly **black-on-black** for tooltips).
- **`ui/dashboard.py`:** Directive field tooltip shortened to **two lines** (`\n`): *Enter — send* / *Shift+Enter — new line* (narrower bubble).
- **`core/net_telemetry.py` (new):** **`icmp_ping_ms`**, **`tcp_connect_rtt_ms`**, **`probe_internet_rtt()`** (rotating ICMP hosts `1.1.1.1` / `8.8.8.8` / `1.0.0.1` / `9.9.9.9`, then **TCP `1.1.1.1:443`** if ICMP fails); **`smooth_rtt_ema`**, **`format_rate_bps`**, **`ThroughputSampler`** ( **`psutil.net_io_counters()`** delta → bytes/s up+down, all interfaces).
- **`ui/bars.py` (`BottomBar`):** **`PING NNms`** (EMA-smoothed; **`—`** after two consecutive failed probes to avoid flicker) via **`_RttWorkerThread`** ( **`QThread`**, does not block UI); refresh loop ~**2.5s**. **`NET ↑… ↓…`** (K/s or M/s) via **`QTimer` (1s)**. Tooltips describe ICMP/TCP and total interface throughput. **`_stop_rtt_thread()`** idempotent — **`QApplication.aboutToQuit`** + **`main.JarvisWindow.closeEvent`**.
- **`ui/theme.py`:** **`BOTBAR_H` 38 → 40** to fit the new labels.
- **`main.py`:** Calls **`_botbar._stop_rtt_thread()`** in **`closeEvent`** before **`browser.stop()`**.
- **`tests/test_net_telemetry.py`:** Non-network unit tests for **`format_rate_bps`**, **`smooth_rtt_ema`**, **`_parse_icmp_time_ms`**, **`ThroughputSampler`**.

### Session 2026-04-26 — Action reminders (`set_reminder` + `run`)

- **Goal:** Reminders are not only **notify** (toast / `REMINDER: …`); the model can attach **`parameters.run`** = one **`{ intent, action, parameters }`** step that **`dispatch()`** runs when the timer fires (Qt main thread via **`signals.reminder_action`**).
- **`core/executor.py`:** **`_is_schedulable_reminder_action`**, **`_validate_reminder_run`**, **`_format_run_summary`**. Registry **`_reminder_meta`** (message, run, schedule_confidence) + **`_active_reminders[id]`** timers; cancel by **message** (all matches); list shows IDs. **Blocked** from scheduling: `file_operation`, `code_execution`, `automation_task`, nested `reminder_task`, `close_app`, `type_text`, `control_mouse`, power/sleep/force-kill, etc. **Allowed** example families: `open_app`, `search_web`, safe `system_control`, `browser_automation` (navigate, read_page, …), `read_screen`, read-only `jarvis_meta`.
- **`core/signals.py`:** **`reminder_action.emit(dict)`** — **`main._on_reminder_action`** → **`dispatch(..., confirmed=True)`**, transcript **`append_jarvis_scheduled`**, TTS, history, toasts.
- **`ui/components/transcript.py`:** **`append_jarvis_scheduled`**, **`_render`** skips empty **`YOU:`** line.
- **`tests/test_reminder_scheduled.py`:** Unit tests for **`_validate_reminder_run`** (no network).
- **`CLAUDE.md`:** `set_reminder` + **`run`** + **`schedule_confidence`** documented in **`reminder_task`** section.

---

## What JARVIS can do (capability list)

This is the **authoritative “what it does now”** summary (executor + brain + UI). Destructive or sensitive actions go through **confirmation** where noted.

### Brain, memory, and routing
- **Claude** returns a **single JSON** command per user utterance: `intent`, `action`, `parameters`, `confidence`, `response`, `hud_status`, `requires_confirmation`.
- **“I'm unable to process that request.” (unknown, ~0%)** comes from **`core/brain._fallback`**, not from normal **`intent: "unknown"`** routing. Typical causes: **invalid JSON** from the model (e.g. **unescaped newlines** or quotes inside `create_file`’s `content` string), **JSON truncated** (former **`max_tokens=1024`** was too small for long `content`), prose before/without a parseable object, or **API errors** (auth, rate limit). **Fixes in code:** `brain.py` uses higher **`max_tokens`** for file-like prompts, **extracts the first balanced `{...}`** if the model prefaces with text, and **`CLAUDE.md`** instructs strict JSON escaping for **`create_file`**. **Restart the app** after changing **`CLAUDE.md`** (system prompt is cached in-process).
- **`@tags`** in the command bar (e.g. `@browser`, `@files`, `@system`) override intent; see `CLAUDE.md` for the full map.
- **Conversation memory** (`core/memory.py`) — rolling window (~8k tokens est.), pairs trimmed together.
- **STT** normalisation (whitespace / punctuation) before routing.

### Voice and UI shell
- **Voice:** Google STT (mic) → command; **ElevenLabs TTS** (with **pyttsx3** fallback), streaming + transcript **typewriter** sync; mic/TTS **mute** toggles; **`Thinking...`** state while work is in progress.
- **HUD:** Dashboard (transcript, arc reactor, telemetry, gauge), **Voice**, **Automation**, **History**, **Settings**; **TopBar** (CPU / MEM / UPTIME, **battery** + **Wi‑Fi** when available, Quick Settings, **Command palette** / **Ctrl+K**, System Status); **toasts**; **inline confirm card** (cyan CONFIRM / red CANCEL).
- **Command palette** — text commands + `@` tags, recent history.
- **Main directive field (bottom bar):** **Enter** sends the command (same as the ↵ control); **Shift+Enter** inserts a **newline** for multi-line text. The editor is `QTextEdit` subclass `_TagLineEdit` in `ui/widgets.py` (emits `contentHeightChanged` for layout); the dashboard input card resizes with line count in `_InputBlock` (`ui/dashboard.py`). **Tooltip (two lines):** *Enter — send* / *Shift+Enter — new line*; app-wide **QToolTip** contrast via `tooltip_qss()` + palette in `main.py`.
- **Bottom status bar `BottomBar`:** **`SYSTEM ONLINE`**, **`PING …ms`**, **`NET ↑… ↓…`** (live throughput), command count, current view. See `core/net_telemetry.py` + `ui/bars.py`.
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
- **Google**, **YouTube**, **GitHub**, **Stack Overflow**, **Wikipedia**, or generic **web search** — builds the right query URL; if the **Playwright** session is up, uses **`browser.navigate(url)`** (same Chrome JARVIS controls), otherwise falls back to **`webbrowser.open(url)`** (default browser). *Note: Google may show the `google.com/sorry` interstitial on automated Chrome; use `search_web` vs workflows that only `navigate` the Playwright window accordingly.*

### Input automation (`type_text`, `control_mouse`)
- **Type** text, **paste**-style, or **press keys** (including combos, e.g. `ctrl+c`). Implementation: `executor` → `_handle_type_text` → **`press_key`** in `core/computer_control.py` (PyAutoGUI). Natural language like *press Enter*, *Ctrl+V*, *tab* should route to `type_text` with **`action`: `press_key`** and **`parameters.key`** (see `CLAUDE.md` for allowed key names). **Clicks** on screen pixels or UI are **`control_mouse`** (e.g. `click`); that path does **not** replace keyboard input — ask the brain to use the right intent so STT/NL does not conflate *click* (mouse) with *press a key* (keyboard).
- **Mouse:** move, click, double-click, right-click, **scroll**, **drag** (coordinates per `computer_control` / PyAutoGUI).

### System control (`system_control`)
- **Volume** up / down / **mute**; optional **absolute level** (0–100) when the model supplies `level` (see `CLAUDE.md`).
- **Screenshot** to disk (path resolution, optional **region**); may ask to create a **missing folder** (executor confirmation).
- **Lock** screen.
- **Sleep**, **shut down**, **restart** — **confirmed**; Windows uses **`shutdown.exe`** from `%SystemRoot%\System32` for shutdown/restart, and the existing sleep path (e.g. `rundll32` + power profile on Windows).
- *Planned/extended in schema:* brightness, WiFi/BT toggles — only if implemented in `executor` / `computer_control` (check code before advertising beyond volume/lock/screenshot/sleep/restart/shutdown).

### File operations (`file_operation`)
- **Relative path resolution:** first segment is resolved as a **folder name** under **`Path.home()`**: fast checks (Documents, Desktop, etc.), then a **bounded `os.walk`** of the user profile (depth cap, prunes e.g. `node_modules`, `.git`, large AppData paths). If no folder matches, new paths are rooted under **`JARVIS_DEFAULT_CREATE_PARENT`** in `.env` (`documents` \| `desktop` \| `downloads` \| `home`; default **Documents**), **not** the JARVIS process CWD. Implementation: **`core/executor.py`** (`_find_folder`, `_resolve_file_operation_path`, etc.).
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
- Persistent **Chrome** session: **navigate**, **click** (selector / text / x,y, with **search** fallbacks including **Enter** on the search field when the submit button is stale), **fill_form**, **read_page** (see below), **extract** by selector, **screenshot** (page or element), **new_tab**, **close_tab** (optional **`url_contains` / `title_contains` / `match`** to close a **specific** tab, not only the active one).
- **`read_page`:** returns a **tab header** (document **title** + **URL**) and then **visible body text** (up to 4k chars of content). If no text is extractable (e.g. empty / blocked page), the header is still returned with a short note. **`personality._NO_TRIM`** includes **`read_page`** so the HUD/TTS is not hard-truncated to ~100 characters.

### Read screen / OCR (`read_screen`)
- **OCR** full screen, **region**, or as wired in `computer_control` (Tesseract must be on **PATH**).

### Reminders (`reminder_task`)
- **set_reminder** (delay floor **5s** in executor), **cancel_reminder**, **list_reminders** (threading **Timer** + metadata).
- **Action reminders:** optional **`parameters.run`** = one schedulable step; when the timer fires, **`reminder_action`** → **`main._on_reminder_action`** runs **`dispatch`** (see **`CLAUDE.md`** allowlist). Message-only timers still emit **`status_changed`**: `REMINDER: …`.

### JARVIS meta (`jarvis_meta`)
- **tell_time**, **tell_date**, **status_report** (CPU, memory, **battery** when `sensors_battery()` is available), **conversational** (can use page cache); other actions (theme, help, etc.) are defined in **`CLAUDE.md`** for the model — wire-up in `executor` may be partial; trust **`CLAUDE.md`** + `personality.say` for what is spoken.

### Automation (`automation_task`)
- **list_workflows**, **create_workflow**, **remove_workflow** (with confirmation), **rename_workflow**, **run_workflow** from JSON `data/workflows.json` via `WorkflowLibrary`. Dangerous step types are **blocked** in library validation (see `_DANGEROUS_STEPS` / `_BLOCKED_INTENTS`).
- **UI `+ NEW` button** in the Automation page WORKFLOW LIBRARY panel — opens a minimal dialog (name + trigger phrase) to create a skeleton workflow directly from the UI without a voice command.

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

## Session work — 2026-04-26 (path resolution, browser read, UI mocks, skills, product notes)

Handoff of **what was implemented and decided** in that session (may span multiple local commits). Use this when onboarding or avoiding repeated mistakes.

### File paths (`core/executor.py`)

- **`_find_folder(name)`** — Resolves a folder **by name** for the first segment of relative paths: shortcuts (`documents`, `desktop`, …), then one-level scan under common roots, then **profile-wide** exact directory-name match via **`_find_all_exact_name_in_profile`** (depth cap **`_HOME_WALK_MAX_DEPTH`**, prunes dir names and path fragments to skip huge trees).
- **Disambiguation:** **`_pick_best_of_matches`** — shallowest path wins; paths under **Documents** preferred among ties.
- **`_resolve_file_operation_path`** — If the first segment is not found, builds under **`_default_create_parent()`** from **`JARVIS_DEFAULT_CREATE_PARENT`** (see **`.env.example`**) instead of the project CWD.
- **Lint fix:** `_HOME_PRUNE_PATH_FRAGMENTS` — avoid invalid **raw** strings ending in `\` (use escaped normal strings).
- **Docs:** **`CLAUDE.md` / `Claude.md`** — path resolution and env var; **`search_web` execution** note was discussed (user may have **reverted** default-browser-only search; **verify `executor._handle_search_web`** in tree).

### Browser (`core/browser.py`)

- **`read_page`:** prepends **document title** and **URL** of the **Playwright** tab, then **page content**; succeeds with tab info even when body text is empty (instead of a hard error that triggered “couldn’t extract anything useful” for questions like *which page are you on?*).
- No separate `page_info` action in the **current** design — **check `executor` + `personality.py`** if that was added then removed.

### Personality (`core/personality.py`)

- **`_NO_TRIM`** extended with **`("browser_automation", "read_page")`** so long `read_page` output is not collapsed to a tiny snippet for TTS/HUD.

### UI — no mock seed (`main.py`, `ui/dashboard.py`, `ui/history.py`, `data/mock.py`)

- **SYS_LOG_BUFFER** starts **empty** (no fake boot log JSON / kernel lines in **`dashboard._SysLogPanel`**).
- **Session history** no longer pre-filled from **`MOCK_HISTORY`**; **History** view initial load uses **empty** list, not **`MOCK_HISTORY_FULL`**.
- **`data/mock.py`:** `MOCK_HISTORY` / `MOCK_HISTORY_FULL` as **empty** lists; optional **`MOCK_AUTOMATIONS`** kept as sample data only.

### Cursor: `/learn` skill (optional)

- **Path:** **`.cursor/skills/learn/SKILL.md`** (project). **Default `.gitignore` ignores `.cursor/`** — to version the skill, use **`git add -f .cursor/skills/learn/SKILL.md`** or a gitignore exception.
- **Intent:** user **`/learn <topic>`** → **deep research** (sources) → **write** `context/learnings/<slug>.md` for durable project memory.

### Architecture notes (conversation, not all code)

- **Claude API key** is used in **`core/brain.py`** only; **`core/executor.py`** and **`core/computer_control.py`** do **not** call Anthropic — they consume the **JSON** from the brain. **Strong JSON** = prompt + validation + allowlists, not “wire the API into every module.”
- **File / search in executor** uses **Python** (`pathlib`, `os.walk`, etc.); **shell** is only where **`code_execution` → `run_shell`** (or similar) is intentional.
- **Google `google.com/sorry`:** Playwright-driven **Google search** can hit “unusual traffic” — product fix discussed was **`webbrowser.open` + `google.com/search` for `search_web`**; confirm **`_handle_search_web`** in repo if that stuck after user revert.

### Git

- Example commit groupings for this batch were suggested in chat (core vs UI, optional `git add -f` for the learn skill). **Use `git status`** before committing.

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
│   ├── net_telemetry.py     # HUD: ICMP/TCP RTT, psutil throughput helpers
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
│   ├── mock.py              # Empty `MOCK_HISTORY` stubs; optional `MOCK_AUTOMATIONS` samples (not used by main)
│   ├── intents.py           # Intent definitions
│   └── workflows.json      # Named workflow library (user-editable / UI-backed)
└── tests/
    ├── test_computer_control.py   # 6 tests: clipboard, keyboard, screenshot, OCR, mouse, volume
    ├── test_executor.py           # 15 tests: open/close app, web search, file ops, mouse, meta, reminders
    ├── test_browser.py            # 15 tests: navigate, click, fill, read, screenshot, tabs
    ├── test_net_telemetry.py      # Unit: format_rate, EMA, ICMP parse, throughput sampler
    └── test_reminder_scheduled.py # Unit: _validate_reminder_run for action reminders
```

### Intent quick reference (14 categories)

| Intent | @Tag | What it does (short) |
|---|---|---|
| `open_app` | `@app` | Launch apps, open URLs (browser or Playwright) |
| `close_app` | — | Close app; force quit (with confirm) |
| `search_web` | `@search` | Query URLs — Playwright **navigate** if session up, else default browser (see capability text) |
| `type_text` | `@type` | Type text, paste, key combos |
| `control_mouse` | `@mouse` | Move, click, scroll, drag |
| `system_control` | `@system` | Screenshot, volume, lock, **sleep** / **shutdown** / **restart** (with confirm) |
| `file_operation` | `@files` | **Create** (path confirm in UI), read, delete (confirm), move, copy, list, search |
| `code_execution` | `@code` | Python, shell, script, **git** / **npm** commands |
| `browser_automation` | `@browser` | Playwright: navigate, click, fill, read, tabs, screenshots |
| `read_screen` | `@screen` | OCR (Tesseract) |
| `automation_task` | `@automate` | Workflows: list, run, create, remove, rename |
| `reminder_task` | `@remind` | Set / cancel / list reminders; optional **scheduled action** via `run` |
| `jarvis_meta` | `@jarvis` | Time, date, status, **conversational**; other meta in `CLAUDE.md` |
| `unknown` | — | No action; graceful fallback |

---

## Key Architecture Decisions

### Signal Flow
```
User input → _process_cmd() → ask_claude_async() → _brain_result_ready signal
→ _on_brain_result() → _execute_result()
    ├─ (single-intent or non-workflow) → dispatch(result) → _finish_execute(...)
    └─ (automation_task + run_workflow + steps) → daemon Thread → dispatch(result)
                                                   → _exec_done.emit(payload)
                                                   → _on_exec_done() → _finish_execute(...)

_finish_execute():
→ voice_engine.say(primary, on_ready=λ: _tts_ready.emit(), on_done=λ: _action_followup_tts.emit when follow)
→ ElevenLabs streams → on_ready() → _tts_ready → transcript.update_last_jarvis(primary)
→ (after first clip ends) on_done() → _action_followup_tts → append_jarvis_scheduled + say(follow)
```
When there is **no** follow-up line, behaviour matches the old single-clip path (`on_done` omitted).
For **multi-step workflows**, `dispatch()` runs in a daemon thread so the Qt event loop stays live.
The `_exec_done` signal (Qt signal, thread-safe) bridges the result back to the main thread.

### Thread Safety
- All worker→UI updates go through `pyqtSignal` — never direct widget access from threads
- `BrowserSession` uses `threading.RLock` to serialize all Playwright calls
- `ConversationMemory` uses `threading.Lock` on all mutations

### TTS/Transcript Sync
- `voice_engine.say(text, on_ready=…, on_done=…)` — event-driven; `on_done` when playback **finishes** (for chaining a **second** line)
- `on_ready()` fires when ElevenLabs first audio chunk is ready to play
- Transcript typewriter for **primary** still starts on `on_ready` — the **follow-up** is appended (scheduled-style row) when `on_done` runs, then spoken in a second clip

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
- **MEM_ALLOC** (`ui/dashboard.py` — class **`_MemCard`**) — label is HUD shorthand for **system RAM in use**, not a per-process malloc debug view. **Data:** `psutil.virtual_memory()` every **2s** — **used GB** (header), **%** of total, **used / total GB** (detail line), **8-segment bar** = `mem.percent`. Same thing you see in Task Manager “Memory” as overall utilisation: how much physical RAM is currently **used** by the OS and programs (vs sitting free or cached).
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
| `core/browser.py` Playwright thread hardening | 🔮 V2 — dedicated browser thread + queue (browser crash auto-restart now handled by `_not_ready()` → `_recover()`) |
| Phase 1 UX audit — confirm bar, history clear, auto-confirm banner | ✅ Shipped 2026-04-27 |
| History status field written on every dispatch | ✅ Shipped 2026-04-27 |
| History persistence (SQLite) | ✅ `core/history_store.py` shipped 2026-04-27 |
| Phase 2 — background workflow execution | ✅ `_exec_done` + daemon thread shipped 2026-04-27 |
| Phase 3 — UPLINK real TX/RX | ✅ `_UplinkCard._tick_net()` shipped 2026-04-27 |
| Phase 3 — Win+J summon hotkey | ✅ `Meta+J` QShortcut shipped 2026-04-27 |
| Phase 3 — Create Workflow UI | ✅ `+ NEW` button + `_NewWorkflowDialog` shipped 2026-04-27 |
| Phase 3 — Settings “Test Connection” per-API | ⏳ Not built — single APPLY button; no per-key test |
| Phase 4 — Voice page stat card (cmd count, avg confidence) | ⏳ Not built |
| Phase 4 — Keyboard navigation (sidebar, history rows) | ⏳ Accessibility debt |
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

## Session 2026-04-26 (Cursor agent chat) — Windows apps, paths, multi-step, browser

This section records **this chat** so future sessions can rely on it without re-reading the thread.

### Windows app resolution & launch (`core/executor.py`)

- Tighter **stem/alias** rules so product names (e.g. **VS Code** vs **Codex**) are not conflated; **`Get-StartApps`** and **`shell:AppsFolder` (COM/Shell.Application)** are merged in **`_get_all_startapp_rows()`** for broader UWP coverage. **PATH** resolution runs **after** those GUI-oriented sources so a CLI on PATH (e.g. `claude`) does not win over a real desktop entry.
- **UWP AUMID** via **`_WIN_APPID_PREFIX`** and **`os.startfile` / `explorer`** for `shell:AppsFolder\` + AppUserModelId. **Registered `ms-*` URL protocols** via **`_WIN_PROTO_PREFIX`**: **HKCR** enumeration with **`winreg`**, not PowerShell (unreliable multiline `‑Command`); the **`URL Protocol` string is a value on the progid key**, not a `URL Protocol\` subkey — we use **`QueryValueEx`**. Protocol launch + **fallback to `ms-…:`** if AppId launch fails. **`_score_query_vs_url_protocol`** improved for e.g. **Microsoft Store**; cache TTL for protocol list.
- Voice alias **`adams` → `male-american`**.

### Path expansion & file ops (`core/executor.py`)

- **`_expand_path_string()`** — **`os.path.expandvars`** then **`Path.expanduser`** so model paths with **`%USERNAME%` / `%USERPROFILE%`** resolve. Used in **`_resolve_screenshot_path`**, **`_safe_path`**, **`_resolve_file_operation_path`**.
- **`move_file`:** if destination is a **single segment** and **`_find_folder("downloads")`** (etc.) **resolves**, do **not** replace resolved **`dest`** with **`path.parent / "Downloads"`**; only when **`_find_folder` is `None`** treat the string as a **new filename in the same folder** as the source.

### JARVIS meta & automation UX (`core/executor.py`, `core/personality.py`, `CLAUDE.md`)

- **`status_report`:** appends **battery** via **`psutil.sensors_battery()`** when a sensor exists (laptops), alongside **CPU and memory** (see `tests/test_executor.py` help text if updated).
- **`automation_task` + TTS (updated since this note was written):** see **“Post-action follow-up”** at the top of this file — primary line is **Claude’s `response`**, follow-up is **`ack_scheduled_action`-style** using **`last_step_intent` / `last_step_action`** from the executor. The old **flatten step output into one long spoken line** approach was **removed** in favour of that two-beat flow.
- **`CLAUDE.md`:** new **absolute rule** and **§7** routing: **two requests in one message** → **`automation_task` + `run_workflow` + `steps`**, not **`unknown`**. **Example** (voice + file search, voice + status). **Addendum v2.2** aligned. **`close_tab` / `url_contains` / `match` params** in browser section.

### Playwright browser (`core/browser.py`)

- **`_SEARCH_INPUT_SELECTORS`** (shared) for search **inputs**; **`_SEARCH_SUBMIT_SELECTORS`**, **`_try_search_role_buttons()`**, **`_try_submit_search_by_enter()`** (focus search field, **Enter**) when CSS selectors (e.g. **`button#search-icon-legacy`**) go stale. **`_click_by_visible_text`**, and if a **selector** fails but **`text`** is also in params, try **text** path.
- **`close_tab`:** optional **`title_contains`**, **`url_contains`**, **`match`**; **`_find_page_to_close`**, **`_score_page_for_keywords`** (URL +10, title +5). With **no** filter, behaviour unchanged: **active tab** only. **`core/executor.py`** maps **`url_match`**, **`tab`**, **`target`**, etc.

### Files commonly edited in this chat

- `core/executor.py`, `core/browser.py`, `core/personality.py`, `CLAUDE.md`, `tests/test_executor.py` (minor).

### After changing `CLAUDE.md`

- **Restart** the app — the brain **caches** the system prompt for the process lifetime.

---

## Session 2026-04-26 (Cursor) — Onboarding read + directive UX + `press_key` hardening

This section records a single Cursor session: repo orientation (`CLAUDE.md`, `context.md`, core layout), a product question about **Win+M**, and the **code changes** that followed.

### Codebase orientation (no code changes)

- **Flow:** `main.py` → `ask_claude_async` (`core/brain.py`, loads **`CLAUDE.md` / `Claude.md`**) → parsed JSON → `dispatch` (`core/executor.py`) → per-intent handlers, **`core/browser.py`**, **`core/computer_control.py`**, etc.
- **Handoff doc:** this file; brain contract is **`CLAUDE.md`**.

### Win+M — will JARVIS do it?

- **Execution path:** `type_text` → **`press_key`** → **`core/computer_control.press_key`**, which uses **PyAutoGUI** `hotkey(...)` for `+`-separated combos. The **Windows** key is present in PyAutoGUI as **`win`**.
- **Caveat:** If the user says *“click the Windows key + M”*, the model may return **`control_mouse` / `click`** instead of **`press_key`**. Chords should be described as *press* / *send* or use **`@type`**, and **`CLAUDE.md`** already steers **keys** to **`type_text`**, **clicks** to **`control_mouse`**.

### Implemented changes (files + behaviour)

| Area | File | What changed |
|------|------|----------------|
| Directive field | `ui/widgets.py` | `_TagLineEdit`: cap height ~108px; vertical **scrollbar when needed**; `WidgetWidth` wrap; `resizeEvent` → `_reflow_height`. |
| Input strip | `ui/dashboard.py` | `_InputBlock._on_input_editor_height`: tighter **INPUT_H** cap; **sync `_CommandStrip` height** to the block. |
| Keyboard | `core/computer_control.py` | **`_normalize_key_token`**: aliases for Windows-key wording before **`hotkey`/`press`**. |

### UX issue addressed

- **Problem:** **Shift+Enter** added many newlines; the bottom directive area **grew without bound** and could push the UI out of the window; **`_CommandStrip` did not grow** with **`_InputBlock`**, so layout was inconsistent.
- **Intent:** The field should **grow only a little**, then **scroll**; the **strip** should **always match** the input block height.

### Follow-ups (optional, not done here)

- If **`CLAUDE.md`** should explicitly call out **Win+…** / “do not use click for key chords”, add a one-line **routing** note and restart the app so the cached system prompt reloads.

---

## Session 2026-04-26 (Cursor) — QToolTip contrast + bottom bar PING & network throughput

### Tooltips (earlier in same iteration)

- **Problem:** `QToolTip` text was **very low contrast** (dark on black) and the directive **hint was one long line**.
- **Changes:** `ui/theme.py` — **`tooltip_qss()`**; **`main.py`** — `QPalette.ToolTipBase` / `ToolTipText` + **`app.setStyleSheet(tooltip_qss())`**. `ui/dashboard.py` — `setToolTip` for `_TagLineEdit` uses a **line break** so the box is not overly wide.

### Bottom bar: PING + NET

- **Where:** `ui/bars.py` — class **`BottomBar`** (between stretch and `N COMMANDS`), styled with shared **`_BOT_TELEM`**.
- **PING:** **`core/net_telemetry.probe_internet_rtt()`** per background cycle: one **ICMP** attempt to a **rotating** public host (avoids per-host cache bias), then **TCP connect** to **`1.1.1.1:443`** if ICMP fails. **UI thread never blocks** — work runs in **`_RttWorkerThread`** ( **`QThread`** ), result delivered via **`pyqtSignal`**. Display: **`smooth_rtt_ema(..., alpha=0.35)`**; after **2** failed probes in a row, show **`PING —`**. ~**2.5s** between samples (sleep in thread loop).
- **NET speed:** Not a “speed test” to the internet — it is **aggregate interface throughput**: **`ThroughputSampler`** uses **`psutil.net_io_counters()`** deltas / **1s** `QTimer` for **total bytes sent and received** (all NICs, includes loopback). Shown as **`NET ↑<rate> ↓<rate>`** with **`format_rate_bps`** (B/s, K/s, M/s).
- **Lifecycle:** `BottomBar` registers **`QApplication.instance().aboutToQuit → _stop_rtt_thread`**, and **`main.JarvisWindow.closeEvent`** also calls **`_botbar._stop_rtt_thread()`** (idempotent with **`_rtt_stopped`**) before **`browser.stop()`**.
- **Layout:** `ui/theme.BOTBAR_H` increased from **38** to **40** pixels.

### Files

| File | Role |
|------|------|
| `core/net_telemetry.py` | ICMP parse + subprocess ping (Windows/macOS/Linux flags), TCP RTT, EMA, throughput, formatting |
| `ui/bars.py` | `BottomBar` labels, `_RttWorkerThread`, timers, shutdown |
| `ui/theme.py` | `tooltip_qss()`, `BOTBAR_H` |
| `main.py` | Tool palette + tooltip QSS; `closeEvent` → stop RTT thread |
| `ui/dashboard.py` | Two-line directive tooltip text |
| `tests/test_net_telemetry.py` | Fast unit tests (no live network) |

---

## CV/Portfolio Description

> **JARVIS** — Iron Man-style voice AI desktop assistant (Python, PyQt5)  
> Built a full-stack desktop AI assistant featuring a custom HUD with arc reactor orb, real-time telemetry, and SYS_LOG_BUFFER transcript with typewriter animation. Integrated Claude API (Sonnet 4) for natural language intent routing across 14 intent categories (e.g. apps, files, system, browser, automation, reminders). Implemented ElevenLabs streaming TTS with event-driven audio/transcript synchronisation, Google STT for voice input, and a Playwright Chrome session for browser automation (navigate, click, fill forms, read page content). Architecture uses PyQt5 signal bridge for thread-safe worker→UI communication, rolling conversation memory (8k token window), and a modular executor pattern separating intent routing from OS execution.  
> **Stack:** Python · PyQt5 · Claude API · ElevenLabs · Playwright · PyAutoGUI · Pytesseract · Google STT · Vapi