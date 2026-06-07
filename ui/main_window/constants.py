"""Shared module-level constants for the JarvisWindow package (R2-17a).

Extracted so both ``window.py`` (used in ``__init__``) and the method-group
mixins can read them without any mixin importing ``window`` (which would create
an import cycle). Imports nothing from the package — safe to import anywhere.
"""

from __future__ import annotations

# Sidebar nav slot for the Settings page — kept as a constant so any future
# nav reorder only needs to change one line.
_SETTINGS_NAV_IDX = 4

# Maximum number of history entries kept in memory. Oldest are evicted when exceeded.
_HISTORY_MAX = 500

# Maximum characters sent to TTS for data-heavy actions (read_page, OCR, code output).
_TTS_MAX_CHARS = 800
