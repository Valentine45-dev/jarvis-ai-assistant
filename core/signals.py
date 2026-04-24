"""
JarvisSignals — central Qt signal hub.
Every backend module emits signals, every UI view listens.
No direct imports between backend and frontend.
"""

from PyQt5.QtCore import QObject, pyqtSignal


class JarvisSignals(QObject):
    status_changed = pyqtSignal(str)
    command_received = pyqtSignal(str)
    confidence_updated = pyqtSignal(float)
    speaking_state_changed = pyqtSignal(bool)
    hud_status_updated = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    confirmation_required = pyqtSignal(dict)


signals = JarvisSignals()
