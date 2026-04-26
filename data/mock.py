"""
Optional stub data. The live HUD uses an empty session — no mock transcript seed.

`MOCK_AUTOMATIONS` is sample shape only for local UI experiments; not loaded by main.
"""

MOCK_HISTORY: list = []
MOCK_HISTORY_FULL: list = []

MOCK_AUTOMATIONS = [
    {"id": 1, "name": "Morning Routine",
     "steps": ["Open Browser", "Check Email", "Open Calendar", "Weather Report", "News Brief"],
     "enabled": True, "lastRun": "Today 07:00", "trigger": "Daily 7:00 AM"},
    {"id": 2, "name": "Dev Setup",
     "steps": ["Open VS Code", "Start Terminal", "Run Dev Server", "Open Browser localhost"],
     "enabled": True, "lastRun": "Today 09:15", "trigger": "Manual"},
    {"id": 3, "name": "Night Mode",
     "steps": ["Enable Dark Mode", "Lower Brightness", "Close Work Apps", "Open Music"],
     "enabled": False, "lastRun": "Yesterday 22:00", "trigger": "Daily 10:00 PM"},
    {"id": 4, "name": "Meeting Prep",
     "steps": ["Open Calendar", "Check Email", "Open Notes", "Start Screen Record"],
     "enabled": True, "lastRun": "Mon 14:00", "trigger": "Manual"},
]
