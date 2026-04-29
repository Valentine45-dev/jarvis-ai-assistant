"""Compatibility shim for moved controller module."""

from core.controllers.session_flags import persist_session_flags, sync_session_flag_views

__all__ = ["sync_session_flag_views", "persist_session_flags"]
