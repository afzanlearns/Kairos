from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from kairos.models import Session, ScheduleConfig, SessionLog, QuietHoursConfig
from kairos.daemon import get_due_sessions


def _session(name: str, time: str | None = None, days: list[str] | None = None,
             on_boot: bool = False, last_run: str | None = None,
             history: list[SessionLog] | None = None) -> Session:
    return Session(
        name=name,
        schedule=ScheduleConfig(time=time, days=days or [], on_boot=on_boot),
        last_run=last_run,
        history=history or [],
    )


def test_on_time_trigger():
    """Session scheduled for this minute should be due."""
    now = datetime(2026, 7, 17, 9, 0, 0)
    s = _session("morning", time="09:00", days=["fri"])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert any(e.session_name == "morning" and e.kind == "launch" for e in due)


def test_not_due_if_already_run_today():
    """Session already launched today should not be due again."""
    now = datetime(2026, 7, 17, 9, 0, 0)
    s = _session("morning", time="09:00", days=["fri"],
                 last_run="2026-07-17T08:00:00")
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert len(due) == 0


def test_not_due_if_skipped_today():
    now = datetime(2026, 7, 17, 9, 0, 0)
    s = _session("morning", time="09:00", days=["fri"],
                 history=[SessionLog(date="2026-07-17", status="skipped")])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert len(due) == 0


def test_heads_up_five_minutes_before():
    now = datetime(2026, 7, 17, 8, 55, 0)
    s = _session("morning", time="09:00", days=["fri"])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert any(e.session_name == "morning" and e.kind == "heads_up" for e in due)


def test_missed_catch_up():
    """Session scheduled earlier today should show as missed."""
    now = datetime(2026, 7, 17, 10, 0, 0)
    s = _session("morning", time="09:00", days=["fri"])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert any(e.session_name == "morning" and e.kind == "missed" for e in due)


def test_boot_session_fires():
    now = datetime(2026, 7, 17, 8, 0, 0)
    s = _session("booty", on_boot=True)
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert any(e.session_name == "booty" and e.kind == "boot" for e in due)


def test_boot_already_launched_today():
    now = datetime(2026, 7, 17, 8, 0, 0)
    s = _session("booty", on_boot=True,
                 history=[SessionLog(date="2026-07-17", status="launched")])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert len(due) == 0


def test_quiet_hours_suppresses():
    now = datetime(2026, 7, 17, 2, 30, 0)
    qh = QuietHoursConfig(start="00:00", end="06:00")
    s = _session("night", time="02:30", days=["fri"])
    due = get_due_sessions([s], now, qh, set())
    assert len(due) == 0


def test_wrong_weekday_no_trigger():
    now = datetime(2026, 7, 17, 9, 0, 0)  # Friday
    s = _session("weekend", time="09:00", days=["sat", "sun"])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert len(due) == 0


def test_no_duplicate_notification():
    now = datetime(2026, 7, 17, 8, 55, 0)
    s = _session("morning", time="09:00", days=["fri"])
    notified = {"morning_2026-07-17"}
    due = get_due_sessions([s], now, QuietHoursConfig(), notified)
    assert len(due) == 0


def test_multiple_sessions_due():
    now = datetime(2026, 7, 17, 9, 0, 0)
    s1 = _session("a", time="09:00", days=["fri"])
    s2 = _session("b", time="09:00", days=["fri"])
    due = get_due_sessions([s1, s2], now, QuietHoursConfig(), set())
    assert len(due) == 2
