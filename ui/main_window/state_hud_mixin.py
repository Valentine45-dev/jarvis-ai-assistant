"""State-machine + HUD painting for JarvisWindow (R2-17a split).

Plain mixin — no QObject base, no signals defined here. Methods use only
``self``. Must NOT import ``window`` or ``app`` (no import cycle).

NOTE (condition 1): ``paintEvent`` is a Qt virtual override. Slice 2 proves —
via a real ``uv run python main.py`` launch and the smoke harness — that Qt
dispatches this mixin-hosted virtual. If that proof had failed, ALL four event
handlers would have stayed on JarvisWindow in ``window.py``.
"""

from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QFontMetrics, QColor, QPainter, QRadialGradient, QBrush

from ui.theme import CYAN, RADIUS_LG, BG, _primary, _c
from config.settings import config
from core.history_store import history_store


class _StateHudMixin:
    """``_set_state`` machine, status-text fade, session tick, history-clear
    sync, and ``paintEvent``."""

    def _on_history_cleared(self) -> None:
        """Sync main._history and SQLite DB when the user clicks CLEAR HISTORY."""
        self._history.clear()
        self._cmd_count = 0
        history_store.clear()

    def _set_state(self, s):
        self._state = s

        # Clear the listening flag whenever we leave "listening" state so the
        # mic button icon updates correctly.
        if s != "listening":
            from core.voice import voice_engine as _ve
            _ve.clear_listening()

        # Keep wake detector paused while the system is active.
        # The deferred resume guards against stale QTimer callbacks: if JARVIS
        # transitions idle→thinking in <300ms (always), without the guard the
        # old timer fires and re-enables the detector mid-execution.
        from core.wake_word import wake_detector
        from core.voice import voice_engine
        if s == "idle":
            def _resume_if_still_idle():
                # Do not resume detector while TTS is still speaking; this prevents
                # self-triggering wake events from JARVIS's own voice output.
                # Also skip resume if the user has disabled the wake word.
                if not self._wake_word_enabled:
                    return
                if self._state == "idle" and not voice_engine.is_speaking:
                    wake_detector.resume()
                elif self._state == "idle":
                    # TTS may still be finishing; retry shortly.
                    if config.debug_mode:
                        print("[wake] resume deferred: TTS still speaking")
                    QTimer.singleShot(200, _resume_if_still_idle)
            QTimer.singleShot(300, _resume_if_still_idle)
        else:
            wake_detector.pause()

        orb_map = {
            "idle": 0, "connecting": 1, "listening": 1, "thinking": 2,
            "processing": 2, "speaking": 3, "awaiting_confirmation": 2,
        }
        self._dashboard.left.orb.set_state(orb_map.get(s, 0))
        self._dashboard.left.mic.set_listening(s == "listening")

        self._fade_status_text()

        # Waveform only visible when audio is active; last_action strip otherwise
        active_audio = s in ("listening", "speaking")
        self._dashboard.left.waveform.setVisible(active_audio)
        self._dashboard.left.waveform.set_active(active_audio)

        # HUD status for state changes
        if s == "idle":
            self._dashboard.left.hud_status.set_status("STANDBY")
        elif s == "connecting":
            self._dashboard.left.hud_status.set_status("CONNECTING")
        elif s == "listening":
            self._dashboard.left.hud_status.set_status("LISTENING")
        elif s == "thinking":
            pass  # set by _process_cmd
        elif s == "processing":
            self._dashboard.left.hud_status.set_status("PROCESSING")
        elif s == "speaking":
            self._dashboard.left.hud_status.set_status("SPEAKING")
        elif s == "awaiting_confirmation":
            self._dashboard.left.hud_status.set_status("AWAITING RESPONSE")

        pill = self._dashboard.left.state_pill
        _pill_labels = {"awaiting_confirmation": "WAITING"}
        pill.setText(_pill_labels.get(s, s.upper()))
        pf = QFont(pill.font())
        pf.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        pill.setMinimumWidth(max(120, QFontMetrics(pf).horizontalAdvance(pill.text()) + 46))
        self._voice_view.set_state(s)

        pill_base = (
            f"border-radius:{RADIUS_LG}px;letter-spacing:1.5px;padding:0 20px;"
        )
        if s == "connecting":
            # Amber "hold on" cue — mic isn't live yet, don't speak.
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(255,190,50,0.90);border:1px solid rgba(255,190,50,0.40);"
                f"background:rgba(255,190,50,0.08);{pill_base}")
            self._dashboard.left.status_lbl.setText("Connecting…")
            self._set_cmd_placeholder("CONNECTING…")
        elif s == "listening":
            self._dashboard.left.state_pill.setStyleSheet(
                f"color:{CYAN};border:1px solid rgba(0,212,255,0.40);"
                f"background:rgba(0,212,255,0.09);{pill_base}")
            self._dashboard.left.status_lbl.setText("Listening…")
            self._set_cmd_placeholder("LISTENING…")
        elif s == "idle":
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(210,220,245,0.88);border:1px solid rgba(0,102,255,0.28);"
                f"background:rgba(0,102,255,0.05);{pill_base}")
            self._dashboard.left.status_lbl.setText("Awaiting command.")
            self._set_cmd_placeholder("AWAITING DIRECTIVE...")
        elif s == "awaiting_confirmation":
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(255,190,50,0.90);border:1px solid rgba(255,190,50,0.40);"
                f"background:rgba(255,190,50,0.08);{pill_base}")
        else:
            self._dashboard.left.state_pill.setStyleSheet(
                "color:rgba(210,220,245,0.88);border:1px solid rgba(0,102,255,0.42);"
                f"background:rgba(0,102,255,0.06);{pill_base}")

    def _set_cmd_placeholder(self, text: str) -> None:
        """Update the command-bar placeholder so the live-capture cue shows right
        where the user looks (and where dictation lands). Best-effort."""
        try:
            self._dashboard.left.cmd_bar._input.setPlaceholderText(text)  # noqa: SLF001
        except Exception:
            pass

    def _fade_status_text(self):
        """Quick opacity fade on the status label for state transitions."""
        lbl = self._dashboard.left.status_lbl
        lbl.setStyleSheet("color:rgba(200,215,240,0.0);")
        self._fade_step = 0

        def _step():
            self._fade_step += 1
            alpha = min(0.42, self._fade_step * 0.06)
            lbl.setStyleSheet(f"color:rgba(200,215,240,{alpha});")
            if self._fade_step < 7:
                QTimer.singleShot(25, _step)

        QTimer.singleShot(25, _step)

    def _sys_tick(self):
        # CPU is owned by _CpuCard's internal 1s timer — no duplicate poll here.
        # Memory is owned by _MemCard's internal 2s timer — no duplicate poll here.
        session_delta = datetime.now() - self._session_start
        s_hours, s_rem = divmod(int(session_delta.total_seconds()), 3600)
        s_mins = s_rem // 60
        self._dashboard.right.uptime_card.val.setText(f"{s_hours}h {s_mins}m")
        # Bar fills up over a 4-hour session
        session_pct = min(100, (session_delta.total_seconds() / 14400) * 100)
        self._dashboard.right.uptime_card.set_bar(session_pct)

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(BG))

        g1 = QRadialGradient(w * 0.25, h * 0.35, max(w, h) * 0.55)
        g1.setColorAt(0, _primary(8))
        g1.setColorAt(1, _primary(0))
        p.fillRect(0, 0, w, h, QBrush(g1))

        g2 = QRadialGradient(w * 0.75, h * 0.65, max(w, h) * 0.5)
        g2.setColorAt(0, _c(0, 212, 255, 5))
        g2.setColorAt(1, _c(0, 212, 255, 0))
        p.fillRect(0, 0, w, h, QBrush(g2))

        p.end()
