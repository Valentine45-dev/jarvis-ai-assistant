"""
Intent constants, quick actions, and response templates.
"""

INTENTS = [
    "open_app", "search_web", "system_control", "automation_task",
    "file_operation", "code_execution", "jarvis_meta",
]

QUICK_ACTIONS = [
    ("fa5s.globe", "Browser"), ("fa5s.sun", "Weather"),
    ("fa5s.calendar-alt", "Schedule"), ("fa5s.chart-bar", "System"),
    ("fa5s.camera", "Screenshot"), ("fa5s.lock", "Lock"),
]

RESPONSES = [
    "Right away — executing now.",
    "Done. Anything else?",
    "Command acknowledged.",
    "Task completed.",
    "Taken care of.",
]
