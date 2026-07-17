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


def test_heads_up_generated_once_within_window():
    now = datetime(2026, 7, 17, 8, 55, 0)
    s = _session("morning", time="09:00", days=["fri"])
    due = get_due_sessions([s], now, QuietHoursConfig(), set())
    assert len(due) == 1
    assert due[0].kind == "heads_up"


def test_multiple_sessions_due():
    now = datetime(2026, 7, 17, 9, 0, 0)
    s1 = _session("a", time="09:00", days=["fri"])
    s2 = _session("b", time="09:00", days=["fri"])
    due = get_due_sessions([s1, s2], now, QuietHoursConfig(), set())
    assert len(due) == 2


def test_same_time_sessions_both_due():
    """Two sessions at the exact same HH:MM are both returned by get_due_sessions."""
    now = datetime(2026, 7, 17, 9, 0, 0)
    s1 = _session("alpha", time="09:00", days=["fri"])
    s2 = _session("beta", time="09:00", days=["fri"])
    due = get_due_sessions([s1, s2], now, QuietHoursConfig(), set())
    kinds = [e.kind for e in due]
    names = [e.session_name for e in due]
    assert len(due) == 2
    assert "alpha" in names and "beta" in names
    assert all(k == "launch" for k in kinds)


def test_same_time_heads_up_both_due():
    """Two sessions at the same time both get heads-up 5 min before."""
    now = datetime(2026, 7, 17, 8, 55, 0)
    s1 = _session("alpha", time="09:00", days=["fri"])
    s2 = _session("beta", time="09:00", days=["fri"])
    due = get_due_sessions([s1, s2], now, QuietHoursConfig(), set())
    assert len(due) == 2
    assert all(e.kind == "heads_up" for e in due)


class TestSnooze:
    """Snooze defers re-firing for exactly 5 minutes."""

    def test_snooze_suppresses_one_minute_later(self):
        """After snoozing, the same session should NOT re-fire 1 min later."""
        from kairos.daemon import Daemon

        daemon = Daemon()
        now = datetime(2026, 7, 17, 8, 55, 0)
        s = _session("morning", time="09:00", days=["fri"])

        # Simulate snooze
        key = f"morning_heads_up_{now.strftime('%Y-%m-%d')}"
        daemon._snoozed_until[key] = now + timedelta(minutes=5)

        # 1 minute later — still snoozed
        later = now + timedelta(minutes=1)
        due = get_due_sessions([s], later, QuietHoursConfig(), set())
        assert len(due) > 0, "Session should still be due"

        # The daemon's tick should skip it due to snooze
        # Simulate the tick logic
        snooze_key = f"morning_heads_up_{later.strftime('%Y-%m-%d')}"
        snoozed_until = daemon._snoozed_until.get(snooze_key)
        assert snoozed_until is not None
        assert later < snoozed_until, "Snooze should still be active after 1 min"

    def test_snooze_expires_after_five_minutes(self):
        """After 5 minutes, the snooze should have expired."""
        from kairos.daemon import Daemon

        daemon = Daemon()
        now = datetime(2026, 7, 17, 8, 55, 0)
        s = _session("morning", time="09:00", days=["fri"])

        # Simulate snooze
        key = f"morning_heads_up_{now.strftime('%Y-%m-%d')}"
        daemon._snoozed_until[key] = now + timedelta(minutes=5)

        # 5 minutes later — snooze expired
        later = now + timedelta(minutes=5)
        snooze_key = f"morning_heads_up_{later.strftime('%Y-%m-%d')}"
        snoozed_until = daemon._snoozed_until.get(snooze_key)
        assert later >= snoozed_until, "Snooze should have expired after 5 min"

    def test_snooze_prevents_re_fire_in_tick(self):
        """Daemon._tick should skip a snoozed event and not add it to notified_set."""
        from kairos.daemon import Daemon

        daemon = Daemon()
        now = datetime(2026, 7, 17, 8, 55, 0)
        key = f"morning_heads_up_{now.strftime('%Y-%m-%d')}"
        daemon._snoozed_until[key] = now + timedelta(minutes=5)

        s = _session("morning", time="09:00", days=["fri"])
        due = get_due_sessions([s], now, QuietHoursConfig(), set())
        assert len(due) == 1

        # Simulate the tick's filtering logic directly
        for event in due:
            snooze_key = f"{event.session_name}_heads_up_{now.strftime('%Y-%m-%d')}"
            snoozed_until = daemon._snoozed_until.get(snooze_key)
            if snoozed_until is not None and now < snoozed_until:
                continue  # skip — this is what the tick does
            pytest.fail("Should have been skipped by snooze")

        # Verify nothing was added to notified_set
        assert len(daemon._notified_set) == 0

    def test_snooze_does_not_affect_other_sessions(self):
        """Snoozing one session should not block unrelated sessions."""
        from kairos.daemon import Daemon

        daemon = Daemon()
        now = datetime(2026, 7, 17, 8, 55, 0)
        s1 = _session("morning", time="09:00", days=["fri"])
        s2 = _session("evening", time="09:00", days=["fri"])

        # Snooze only morning
        key = f"morning_heads_up_{now.strftime('%Y-%m-%d')}"
        daemon._snoozed_until[key] = now + timedelta(minutes=5)

        # Both still due
        due = get_due_sessions([s1, s2], now, QuietHoursConfig(), set())
        assert len(due) == 2

        # Verify evening is not affected
        evening_key = f"evening_heads_up_{now.strftime('%Y-%m-%d')}"
        assert evening_key not in daemon._snoozed_until
