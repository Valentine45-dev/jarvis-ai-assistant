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
