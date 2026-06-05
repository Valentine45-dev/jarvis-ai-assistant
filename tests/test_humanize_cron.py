"""Tests for humanize_cron — the cron→English label on the AUTOMATE page.

Guards the schedule descriptions users actually see next to a workflow. The
regression that prompted these: `* * * * *` (every minute) showed the raw cron
with no description because it fell through to the int(minute) parse.
"""

from __future__ import annotations

import pytest

from ui.views.automation.components import humanize_cron


@pytest.mark.parametrize("expr,expected", [
    ("* * * * *", "Every minute"),        # the fixed case
    ("*/5 * * * *", "Every 5 minutes"),
    ("*/1 * * * *", "Every 1 minute"),
    ("0 * * * *", "Every hour"),
    ("0 9 * * 1-5", "9:00 AM every weekday"),
    ("0 0 * * *", "Midnight every day"),
    ("0 12 * * *", "Noon every day"),
    ("30 14 * * 0,6", "2:30 PM every weekend"),
])
def test_known_patterns(expr: str, expected: str) -> None:
    assert humanize_cron(expr) == expected


@pytest.mark.parametrize("expr", [
    "",                 # empty
    "not a cron",       # garbage
    "* * *",            # wrong field count
    "60 0 * * *",       # out-of-range minute
    "0 25 * * *",       # out-of-range hour
    "0 9 5 * *",        # specific day-of-month — intentionally unhandled
])
def test_unrecognised_returns_empty(expr: str) -> None:
    assert humanize_cron(expr) == ""
