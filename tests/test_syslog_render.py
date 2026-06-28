"""SYS_LOG_BUFFER renderer — Variant B (outcome rail + gutters + JARVIS chips).

Pure-HTML tests (no QApplication): exercise the module-level _build_log_html and
its helpers directly. Ambient-independent (the info rail follows whatever theme is
resolved, so it's compared against the CYAN token, not a literal). A separate qtgui
test covers TranscriptPanel back-compat + that setHtml accepts the output.
"""

from __future__ import annotations

import pytest

import ui.components.transcript as tr
from ui.components.design import intent_label_color


def _row(you="", y="", jar="", j="", intent="", conf=None, success=None):
    return (you, y, jar, j, intent, conf, success)


# ── rail colour: info themed, semantic fixed ────────────────────────────────

def test_rail_colours_info_themed_semantic_fixed():
    assert tr._rail_color(True, "", None) == tr.CYAN            # YOU = info, themed
    assert tr._rail_color(False, "open_app", None) == tr.CYAN   # JARVIS no-outcome = info
    assert tr._rail_color(False, "open_app", True) == tr._RAIL_OK
    assert tr._rail_color(False, "search_web", False) == tr._RAIL_FAIL
    assert tr._rail_color(False, "interrupted", None) == tr._RAIL_INTERRUPT
    # interrupt wins regardless of speaker/success
    assert tr._rail_color(True, "interrupted", True) == tr._RAIL_INTERRUPT


def test_semantic_rail_hexes_are_the_locked_values():
    assert tr._RAIL_OK == "#83fba5"
    assert tr._RAIL_FAIL == "#ff6b6b"
    assert tr._RAIL_INTERRUPT == "#ffd166"


# ── chips: JARVIS only, intent + confidence, no latency ─────────────────────

def test_jarvis_row_has_intent_and_conf_chip():
    html = tr._build_log_html([_row(jar="On it.", j="15:04", intent="browser_automation",
                                    conf=0.96, success=True)], set(), 260)
    label, color = intent_label_color("browser_automation")
    assert label.upper() in html                 # intent label (BROWSER)
    assert color in html                         # intent chip coloured from INTENT_COLOR
    assert "96%" in html                         # confidence chip
    assert 'cellpadding="3"' in html             # the chip table


def test_you_row_has_no_chips():
    html = tr._build_log_html([_row(you="open chrome", y="15:04")], set(), 260)
    assert 'cellpadding="3"' not in html         # no chip table on a YOU line
    assert "YOU:" in html


def test_conf_chip_omitted_when_conf_none():
    html = tr._build_log_html([_row(jar="Done.", j="15:04", intent="open_app", conf=None,
                                    success=True)], set(), 260)
    assert "%&nbsp;</td>" not in html            # no confidence chip cell without a conf
    assert "APP" in html                         # but the intent chip still renders


def test_no_latency_chip_ever():
    html = tr._build_log_html([_row(jar="Searching.", j="15:04", intent="search_web",
                                    conf=0.9, success=True)], set(), 260)
    assert "ms" not in html
    assert "0.4s" not in html and "0.0s" not in html


def test_intent_chip_uses_design_maps_not_a_second_source():
    # file_operation → label "file", colour from INTENT_COLOR — both via design.py.
    html = tr._build_log_html([_row(jar="Created.", j="15:04", intent="file_operation",
                                    conf=0.95, success=True)], set(), 260)
    label, color = intent_label_color("file_operation")
    assert label == "file"
    assert "FILE" in html               # label rendered (uppercased)
    assert f"color:{color}" in html     # colour from INTENT_COLOR, not a new map


# ── preserved behaviour: interrupt, expander, anchors ───────────────────────

def test_interrupted_line_amber_no_chips():
    html = tr._build_log_html([_row(jar="Stood down.", j="15:06", intent="interrupted")],
                              set(), 260)
    assert "⛔" in html
    assert tr._INTERRUPT_TEXT in html            # the ⛔ text colour preserved
    assert tr._RAIL_INTERRUPT in html            # amber rail
    assert 'cellpadding="3"' not in html         # no chips on an interrupt line


def test_load_more_and_show_less_expander():
    long = "x" * 400
    collapsed = tr._build_log_html([_row(jar=long, j="15:04", intent="open_app", conf=0.9)],
                                   set(), 260)
    assert "jarvis://expand/0" in collapsed and "[load more]" in collapsed
    expanded = tr._build_log_html([_row(jar=long, j="15:04", intent="open_app", conf=0.9)],
                                  {0}, 260)
    assert "jarvis://collapse/0" in expanded and "[show less]" in expanded


def test_rail_table_present_per_line():
    html = tr._build_log_html([_row(you="hi", y="15:04")], set(), 260)
    assert "bgcolor=" in html and 'width="4"' in html   # the 4px rail cell


# ── live path through _TypewriterProxy (Option B: row-id anchoring) ──────────
# The proxy targets each animation's OWN row by id (never "the last row"), so a
# concurrent append (narration / follow / reminder) mid-animation can't cross the
# in-flight reply onto another row. _IdPanel is a faithful by-id stand-in for
# TranscriptPanel (add_exchange/append return ids; update_jarvis/update_you edit by
# id with the same merge semantics) so we can assert WHICH row each write lands on.
# No QApplication: the proxy's QTimers construct fine without one and we drive _tick
# manually, keeping this in the default suite.

class _IdPanel:
    def __init__(self):
        self.rows: list[dict] = []
        self._by_id: dict[int, dict] = {}
        self._next = 0

    def _add(self, you, y_time, jarvis, j_time, intent, conf, success) -> int:
        rid = self._next
        self._next += 1
        row = {"id": rid, "you": you, "y_time": y_time, "jarvis": jarvis,
               "j_time": j_time, "intent": intent, "conf": conf, "success": success}
        self.rows.append(row)
        self._by_id[rid] = row
        return rid

    def add_exchange(self, you, y_time, jarvis="", j_time="", intent="", conf=None,
                     success=None) -> int:
        return self._add(you, y_time, jarvis, j_time, intent, conf, success)

    def append_jarvis_scheduled(self, jarvis, j_time, intent="", conf=None,
                                success=None) -> int:
        return self._add("", "", jarvis, j_time, intent, conf, success)

    def update_jarvis(self, rid, text, j_time="", intent="", conf=None, success=None):
        r = self._by_id.get(rid)
        if r is None:
            return
        r["jarvis"] = text
        if j_time:
            r["j_time"] = j_time
        if intent:
            r["intent"] = intent
        if conf is not None:
            r["conf"] = conf
        if success is not None:
            r["success"] = success

    def update_you(self, rid, text, y_time=""):
        r = self._by_id.get(rid)
        if r is None:
            return
        r["you"] = text
        if y_time:
            r["y_time"] = y_time


def _drain(proxy):
    for _ in range(2000):
        if proxy._pending is None:
            return
        proxy._tick()


def test_typewriter_proxy_forwards_success_to_its_own_row():
    from ui.components.typewriter import _TypewriterProxy

    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("", "15:04")        # live command row (no you text)
        # THE prod crash signature: 5 positional args incl. success. Lands on the
        # command row by id with the real intent/conf/success after typing.
        proxy.update_last_jarvis("Chrome up.", "15:04", "open_app", 0.97, False)
        _drain(proxy)
        cmd = panel.rows[0]
        assert cmd["jarvis"] == "Chrome up."
        assert cmd["intent"] == "open_app" and cmd["conf"] == 0.97
        assert cmd["success"] is False          # success forwarded to the right row

        # Instant (history) add_exchange path forwards success too.
        proxy.add_exchange("y", "15:05", "Done.", "15:05", "file_operation", 0.9, True)
        inst = panel.rows[-1]
        assert inst["jarvis"] == "Done." and inst["success"] is True

        # append_jarvis_scheduled falls through to the panel as an INDEPENDENT row.
        proxy.append_jarvis_scheduled("Reminder.", "15:06", "reminder_task", 1.0, success=True)
        assert panel.rows[-1]["jarvis"] == "Reminder." and panel.rows[-1]["success"] is True
    finally:
        proxy.stop_animations()
        for _t in (proxy._timer, proxy._thinking_timer, proxy._you_timer):
            _t.stop()


def test_proxy_append_mid_typewriter_keeps_reply_on_its_own_row():
    """THE bug B fixes, forced deterministically: a narration row appends WHILE the
    primary reply is mid-typewriter. Before B the typewriter's remaining ticks
    targeted rows[-1] = the narration row, so the reply's tail + final chip crossed
    onto it and the command row froze as a partial-text / UNKNOWN orphan. With B the
    reply is bound to its own row id, so it finishes on the command row regardless."""
    from ui.components.typewriter import _TypewriterProxy

    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("open the website http://dead.example", "18:29")
        cmd_id = proxy._active_row_id
        reply = "Couldn't load dead.example. net::ERR_NAME_NOT_RESOLVED"
        proxy.update_last_jarvis(reply, "18:29", "browser_automation", 0.97, False)

        # Type a few chars, THEN append the narration row mid-animation.
        for _ in range(10):
            proxy._tick()
        partial_cmd = panel.rows[0]["jarvis"]
        assert 0 < len(partial_cmd) < len(reply)          # genuinely mid-typewriter
        narration_id = proxy.append_jarvis_scheduled(
            "DNS miss — check the address.", "18:29", "browser_automation", 0.97,
            success=False)
        assert narration_id != cmd_id and len(panel.rows) == 2

        # Finish typing. The remaining ticks must STILL land on the command row.
        _drain(proxy)

        cmd = panel._by_id[cmd_id]
        narration = panel._by_id[narration_id]
        # Command row: the FULL reply + the real final chip — not truncated, not UNKNOWN.
        assert cmd["jarvis"] == reply
        assert cmd["intent"] == "browser_automation" and cmd["conf"] == 0.97
        assert cmd["you"].startswith("open the website")
        # Narration stayed on its OWN row, untouched by the typewriter.
        assert narration["jarvis"] == "DNS miss — check the address."
        assert narration["you"] == ""
        # No orphan: exactly two rows, neither is a partial of the other.
        assert len(panel.rows) == 2
    finally:
        proxy.stop_animations()
        for _t in (proxy._timer, proxy._thinking_timer, proxy._you_timer):
            _t.stop()


def test_proxy_narration_before_primary_lands_on_command_row():
    """The earlier manifestation: narration appends while only the thinking
    placeholder is showing, BEFORE the primary starts typing. The primary must still
    land on the command row; the narration stays its own row below."""
    from ui.components.typewriter import _TypewriterProxy

    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("", "18:30")          # command row, thinking starts
        cmd_id = proxy._active_row_id
        # Narration beats the primary entirely → its own row appended first.
        narration_id = proxy.append_jarvis_scheduled(
            "Heads up — that domain looks wrong.", "18:30", "browser_automation", 0.97,
            success=False)
        assert narration_id != cmd_id

        # Now the primary arrives and types onto the COMMAND row (by id), not rows[-1].
        proxy.update_last_jarvis("Couldn't load it.", "18:30", "browser_automation", 0.97, False)
        _drain(proxy)

        assert panel._by_id[cmd_id]["jarvis"] == "Couldn't load it."
        assert panel._by_id[cmd_id]["intent"] == "browser_automation"
        assert panel._by_id[narration_id]["jarvis"] == "Heads up — that domain looks wrong."
        # Command row stays ABOVE the narration row (created first).
        assert panel.rows[0]["id"] == cmd_id and panel.rows[1]["id"] == narration_id
    finally:
        proxy.stop_animations()
        for _t in (proxy._timer, proxy._thinking_timer, proxy._you_timer):
            _t.stop()


# ── sequential follow-up animation (narration types out AFTER the primary) ───
# The narration/follow now ANIMATES (animate=True) on its own row, queued to type
# out only after the primary reply finishes — mirroring the FIFO audio. Reminders/
# scheduled (animate=False) stay instant and never enter the queue. Option B's
# row-id guarantee must hold throughout: each animation writes only to its own
# captured row id, never crossing.

def _close(proxy):
    proxy.stop_animations()
    for _t in (proxy._timer, proxy._thinking_timer, proxy._you_timer):
        _t.stop()


def test_sequential_animation_resp1_then_resp2():
    """resp 1 types fully on its row, THEN resp 2 (animate=True) types on ITS row —
    never two at once, never crossing."""
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("open the website http://dead.example", "18:29")
        cmd_id = proxy._active_row_id
        resp1 = "Couldn't load dead.example. net::ERR_NAME_NOT_RESOLVED"
        proxy.update_last_jarvis(resp1, "18:29", "browser_automation", 0.97, False)

        # Type resp 1 partway, THEN the narration arrives (fast HTTP).
        for _ in range(8):
            proxy._tick()
        assert proxy._pending[5] == cmd_id          # still animating resp 1
        resp2_id = proxy.append_jarvis_scheduled(
            "DNS miss — check the address.", "18:29", "browser_automation", 0.97,
            success=False, animate=True)
        # resp 2 is RESERVED + QUEUED but NOT animating yet (resp 1 still busy).
        assert resp2_id != cmd_id
        assert proxy._pending[5] == cmd_id          # resp 1 still the active animation
        assert len(proxy._anim_queue) == 1
        assert panel._by_id[resp2_id]["jarvis"] == ""   # reserved empty, invisible

        # Finish resp 1 → it lands fully on the command row, THEN resp 2 starts.
        while proxy._pending is not None and proxy._pending[5] == cmd_id:
            proxy._tick()
        assert panel._by_id[cmd_id]["jarvis"] == resp1
        assert panel._by_id[cmd_id]["intent"] == "browser_automation"
        assert proxy._pending is not None and proxy._pending[5] == resp2_id  # resp 2 now animating
        assert proxy._anim_queue == []

        # Finish resp 2 on its own row.
        _drain(proxy)
        assert panel._by_id[resp2_id]["jarvis"] == "DNS miss — check the address."
        assert panel._by_id[resp2_id]["success"] is False
        # Neither crossed: command row still holds resp 1, exactly two rows.
        assert panel._by_id[cmd_id]["jarvis"] == resp1
        assert len(panel.rows) == 2
    finally:
        _close(proxy)


def test_narration_during_thinking_waits_for_primary():
    """Narration appended while the command row is still THINKING (primary not yet
    arrived) must wait, then type after the primary — correct order, own rows."""
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("", "18:30")             # no you-text → thinking starts
        cmd_id = proxy._active_row_id
        resp2_id = proxy.append_jarvis_scheduled(
            "Heads up — that domain looks wrong.", "18:30", "browser_automation", 0.97,
            success=False, animate=True)
        # Thinking is active → queued, not animating.
        assert proxy._pending is None and len(proxy._anim_queue) == 1
        assert resp2_id != cmd_id

        proxy.update_last_jarvis("Couldn't load it.", "18:30", "browser_automation", 0.97, False)
        assert proxy._pending[5] == cmd_id          # primary animates first
        _drain(proxy)                                # drains resp 1 then resp 2

        assert panel._by_id[cmd_id]["jarvis"] == "Couldn't load it."
        assert panel._by_id[resp2_id]["jarvis"] == "Heads up — that domain looks wrong."
        assert panel.rows[0]["id"] == cmd_id and panel.rows[1]["id"] == resp2_id
    finally:
        _close(proxy)


def test_no_narration_primary_animates_alone():
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("open chrome", "18:31")
        cmd_id = proxy._active_row_id
        proxy.update_last_jarvis("Chrome's up.", "18:31", "open_app", 0.98, True)
        _drain(proxy)
        assert panel._by_id[cmd_id]["jarvis"] == "Chrome's up."
        assert proxy._pending is None and proxy._anim_queue == []
        assert len(panel.rows) == 1
    finally:
        _close(proxy)


def test_interrupt_clears_pending_animation_queue():
    """Esc mid-resp-1 with resp 2 queued: the queue is dropped so resp 2 does NOT
    ghost-type afterward."""
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("open the website http://dead.example", "18:32")
        proxy.update_last_jarvis("Couldn't load it, here is why…", "18:32",
                                 "browser_automation", 0.97, False)
        for _ in range(5):
            proxy._tick()
        resp2_id = proxy.append_jarvis_scheduled(
            "ghost narration", "18:32", "browser_automation", 0.97,
            success=False, animate=True)

        proxy.stop_animations()                     # Esc
        assert proxy._anim_queue == [] and proxy._pending is None

        # Draining must NOT type the dropped narration onto its (or any) row.
        _drain(proxy)
        assert panel._by_id[resp2_id]["jarvis"] == ""   # never animated
    finally:
        _close(proxy)


def test_reminder_append_stays_instant_and_unqueued():
    """A reminder (animate=False) fired mid-command appends instantly as a full static
    row, never enters the animation queue, and doesn't disturb the in-flight reply."""
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("open chrome", "18:33")
        cmd_id = proxy._active_row_id
        proxy.update_last_jarvis("Chrome's coming up nice and slow…", "18:33",
                                 "open_app", 0.98, True)
        for _ in range(6):
            proxy._tick()                            # resp 1 mid-animation

        rem_id = proxy.append_jarvis_scheduled(
            "Reminder — stretch.", "18:33", "reminder_task", 1.0, success=True)  # animate=False
        # Instant: full text immediately, NOT queued, primary still animating.
        assert panel._by_id[rem_id]["jarvis"] == "Reminder — stretch."
        assert proxy._anim_queue == []
        assert proxy._pending[5] == cmd_id

        _drain(proxy)
        assert panel._by_id[cmd_id]["jarvis"] == "Chrome's coming up nice and slow…"
        assert panel._by_id[rem_id]["jarvis"] == "Reminder — stretch."   # untouched
    finally:
        _close(proxy)


def test_new_command_finalizes_pending_animations():
    """A new command snaps the in-flight reply AND a queued narration to full on their
    own rows (no dropped partial, no late interleaving), then starts fresh."""
    from ui.components.typewriter import _TypewriterProxy
    panel = _IdPanel()
    proxy = _TypewriterProxy(panel)
    try:
        proxy.add_exchange("first command", "18:34")
        c1 = proxy._active_row_id
        proxy.update_last_jarvis("First reply in progress…", "18:34", "open_app", 0.9, True)
        for _ in range(4):
            proxy._tick()
        n1 = proxy.append_jarvis_scheduled(
            "First narration.", "18:34", "open_app", 0.9, success=True, animate=True)

        # New command supersedes → finalize pending + queued onto their own rows.
        proxy.add_exchange("second command", "18:35")
        c2 = proxy._active_row_id
        assert panel._by_id[c1]["jarvis"] == "First reply in progress…"   # snapped to full
        assert panel._by_id[n1]["jarvis"] == "First narration."           # snapped to full
        assert proxy._anim_queue == [] and c2 not in (c1, n1)
        assert panel.rows[-1]["id"] == c2
    finally:
        _close(proxy)


@pytest.mark.qtgui
def test_panel_by_id_update_targets_correct_row_after_append():
    """Panel-level: update_jarvis(id) edits its row even after another row appended;
    back-compat update_last_* still hits the last row. Needs a real QWidget panel →
    qtgui-gated (a bare QApplication in the default suite segfaults — see conftest)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    assert app is not None
    from ui.components.transcript import TranscriptPanel

    p = TranscriptPanel()
    a = p.add_exchange("cmd", "t1")
    b = p.append_jarvis_scheduled("bg", "t2")
    assert a != b
    # Editing the OLDER row by id must not touch the newer one.
    p.update_jarvis(a, "reply on a", "t1", "open_app", 0.9, True)
    assert p._rows[p._id_index[a]][2] == "reply on a"
    assert p._rows[p._id_index[b]][2] == "bg"
    # Back-compat: update_last_jarvis edits the LAST row (b).
    p.update_last_jarvis("reply on b", "t2", "weather", 0.8, True)
    assert p._rows[p._id_index[b]][2] == "reply on b"
    assert p._rows[p._id_index[a]][2] == "reply on a"


# ── back-compat + setHtml acceptance (needs QApplication) ───────────────────

@pytest.mark.qtgui
def test_transcript_panel_back_compat_and_sethtml():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    panel = tr.TranscriptPanel()
    try:
        # Existing callers pass NO success → must still work (default None).
        panel.add_exchange("open chrome", "15:04")
        panel.update_last_jarvis("Chrome up.", "15:04", "open_app", 0.97)
        panel.append_jarvis_scheduled("Reminder fired.", "15:05", "reminder_task", 1.0)
        assert all(len(r) == 7 for r in panel._rows)     # rows carry the success slot
        assert panel._rows[0][6] is None                 # back-compat default
        # New caller can pass success explicitly.
        panel.add_exchange("delete x", "15:06", "Deleted.", "15:06", "file_operation",
                           0.9, success=False)
        assert panel._rows[-1][6] is False
    finally:
        panel.deleteLater()
