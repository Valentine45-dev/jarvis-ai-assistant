# J.A.R.V.I.S.

J.A.R.V.I.S. is a desktop voice AI assistant built with Python, PyQt5, Anthropic Claude, and ElevenLabs. It presents a cinematic HUD interface and routes natural language commands into structured JSON actions for apps, files, system controls, automation, reminders, and voice feedback.

## Features

- PyQt5 HUD with dashboard, voice, automation, history, and settings views
- Claude-powered JSON intent routing using the project prompt in `Claude.md`
- Voice input through microphone capture and speech recognition
- ElevenLabs TTS with transcript sync and typewriter-style responses
- Animated `Thinking...` transcript placeholder while JARVIS prepares a response
- OS command dispatcher for app launching, browser actions, screenshots, file operations, shell commands, reminders, and automation steps
- Confirmation UI for destructive actions such as shutdown, restart, sleep, delete, force quit, deploy, and email send intents
- Local runtime configuration through `.env` and settings UI

## Project Structure

```text
.
├── main.py              # PyQt application entry point
├── Claude.md            # System prompt and JSON routing contract
├── core/                # Brain, executor, voice, Vapi, signals, automation
├── ui/                  # HUD views, widgets, theme, sidebar, dashboard
├── config/              # Runtime configuration loader
├── data/                # Mock history, intents, and automation examples
├── assets/              # Logo and reference HUD assets
├── fonts/               # Bundled UI fonts
└── pyproject.toml       # Python dependencies and project metadata
```

## Requirements

- Windows is the primary target for this version
- Python matching `pyproject.toml`
- `uv` recommended for dependency management
- Anthropic API key for Claude intent routing
- ElevenLabs API key for premium TTS
- Optional Vapi API key for assistant platform sync

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

## How It Works

User input is sent to `core/brain.py`, which loads `Claude.md` as the system prompt and asks Claude to return one valid JSON command object. That parsed command is passed to `core/executor.py`, which dispatches the intent to the matching OS or assistant handler.

For voice output, `core/voice.py` generates speech through ElevenLabs when configured, then falls back to local TTS if needed. The dashboard transcript starts with a live `Thinking...` placeholder and transitions into a typewriter animation when speech is ready.

## Safety Notes

JARVIS can route commands that affect the local system, including file operations, process control, shell execution, shutdown, restart, and sleep. Treat this as a trusted local assistant, not a sandbox.

Recommended hardening before daily use:

- Keep real secrets in `.env`, never committed files
- Review destructive command confirmation behavior before enabling broad automation
- Avoid running arbitrary shell commands from voice input until command policies are stricter
- Keep `.env` and runtime config files out of git

## Status

This is an early v1 desktop assistant build. The HUD and command flow are functional, but the safety model, tests, and production hardening should be improved before relying on it for high-risk automation.
