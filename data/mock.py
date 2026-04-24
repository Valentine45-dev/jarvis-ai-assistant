"""
Mock data for development — history, automations, and conversation stubs.
"""

MOCK_HISTORY = [
    {"time": "04:47", "you": "What's the weather in San Francisco?",
     "jarvis": "Currently 68\u00b0F, partly cloudy with a high of 72\u00b0F, sir.",
     "jTime": "04:47", "intent": "search_web", "conf": 0.95},
    {"time": "04:44", "you": "Open Chrome",
     "jarvis": "Chrome is now open, sir.",
     "jTime": "04:44", "intent": "open_app", "conf": 0.98},
    {"time": "04:40", "you": "System status report",
     "jarvis": "All systems nominal. CPU at 23%, memory usage 5.2 GB.",
     "jTime": "04:40", "intent": "system_control", "conf": 0.97},
]

MOCK_HISTORY_FULL = [
    {"id": 1, "time": "04:47:12", "you": "What's the weather in San Francisco?",
     "jarvis": "Currently 68\u00b0F, partly cloudy with a high of 72\u00b0F, sir.", "jTime": "04:47:14",
     "intent": "search_web", "confidence": 0.95, "status": "success"},
    {"id": 2, "time": "04:44:30", "you": "Open Chrome",
     "jarvis": "Chrome is now open, sir.", "jTime": "04:44:31",
     "intent": "open_app", "confidence": 0.98, "status": "success"},
    {"id": 3, "time": "04:40:05", "you": "System status report",
     "jarvis": "All systems nominal. CPU at 23%, memory usage 5.2 GB.", "jTime": "04:40:07",
     "intent": "system_control", "confidence": 0.97, "status": "success"},
    {"id": 4, "time": "04:35:18", "you": "Delete temp files",
     "jarvis": "Cleared 2.3 GB of temporary files, sir.", "jTime": "04:35:22",
     "intent": "file_operation", "confidence": 0.91, "status": "success"},
    {"id": 5, "time": "04:30:00", "you": "Run morning routine",
     "jarvis": "Executing 5-step morning routine...", "jTime": "04:30:02",
     "intent": "automation_task", "confidence": 0.94, "status": "success"},
    {"id": 6, "time": "04:22:45", "you": "What's 2+2?",
     "jarvis": "4, sir. Though I suspect you already knew that.", "jTime": "04:22:46",
     "intent": "jarvis_meta", "confidence": 0.99, "status": "success"},
    {"id": 7, "time": "04:15:10", "you": "Deploy to production",
     "jarvis": "Deployment initiated. Pipeline running...", "jTime": "04:15:14",
     "intent": "code_execution", "confidence": 0.88, "status": "warning"},
    {"id": 8, "time": "04:10:33", "you": "Open Spotify",
     "jarvis": "Unable to locate Spotify application.", "jTime": "04:10:34",
     "intent": "open_app", "confidence": 0.72, "status": "error"},
]

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
