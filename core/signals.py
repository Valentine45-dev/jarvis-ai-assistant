"""
JarvisSignals — central Qt signal hub.
Every backend module emits signals, every UI view listens.
No direct imports between backend and frontend.
"""

from PyQt5.QtCore import QObject, pyqtSignal


class JarvisSignals(QObject):
    status_changed = pyqtSignal(str)
    """Fires when a scheduled reminder includes an executable JARVIS action (main thread)."""
    reminder_action = pyqtSignal(dict)
    command_received = pyqtSignal(str)
    confidence_updated = pyqtSignal(float)
    speaking_state_changed = pyqtSignal(bool)
    hud_status_updated = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    confirmation_required = pyqtSignal(dict)
    workflow_library_changed = pyqtSignal()
    terminal_line_ready = pyqtSignal(str)   # one stdout/stderr line from a running command
    terminal_done = pyqtSignal(int)         # exit code when the process finishes
    # R2-15: document_creation runs off the Qt main thread; payload is {"exec_out": dict}
    document_generation_done = pyqtSignal(dict)
    # F-3: cron scheduler fires this when a workflow's schedule is due. Payload
    # is the workflow id (str). Main thread receives it via QueuedConnection
    # and dispatches the workflow through the standard executor path.
    scheduled_workflow_fire = pyqtSignal(str)
    # F-4: global hotkey fired (Ctrl+Shift+J etc). Payload is the action
    # name (focus_command_bar / toggle_mic_mute / take_screenshot / ...).
    # Main thread routes to the appropriate JarvisWindow slot.
    hotkey_triggered = pyqtSignal(str)


signals = JarvisSignals()
