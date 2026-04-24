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
    "Right away, sir. Executing now.",
    "Done. Anything else you need?",
    "Command acknowledged, sir.",
    "Task completed successfully.",
    "Very well. I've taken care of it, sir.",
]
