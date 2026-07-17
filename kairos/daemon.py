from __future__ import annotations

import logging
import sys
import time
import os
import signal
from datetime import datetime, date, timedelta
from typing import Optional

from kairos.config import (
    KAIROS_DIR, LOCK_FILE_PATH, QUIET_HOURS_PATH, DAEMON_POLL_SECONDS,
    HEADS_UP_MINUTES, ensure_dirs,
)
from kairos.models import Session, DueEvent, SessionLog, QuietHoursConfig
from kairos.storage import list_sessions, load_session, save_session
from kairos.launcher import launch_session

logger = logging.getLogger(__name__)

WEEKDAY_MAP = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _load_quiet_hours() -> QuietHoursConfig:
    if QUIET_HOURS_PATH.exists():
        import json
        try:
            data = json.loads(QUIET_HOURS_PATH.read_text(encoding="utf-8"))
            return QuietHoursConfig(**data)
        except (json.JSONDecodeError, TypeError):
            pass
    return QuietHoursConfig()


def _in_quiet_hours(now: datetime, qh: QuietHoursConfig) -> bool:
    if not qh.start or not qh.end:
        return False
    try:
        start_h, start_m = qh.start.split(":")
        end_h, end_m = qh.end.split(":")
        start_min = int(start_h) * 60 + int(start_m)
        end_min = int(end_h) * 60 + int(end_m)
        now_min = now.hour * 60 + now.minute
        if start_min <= end_min:
            return start_min <= now_min <= end_min
        else:
            return now_min >= start_min or now_min <= end_min
    except (ValueError, AttributeError):
        return False


# ── Pure scheduling decision function ────────────────────────────


def get_due_sessions(
    sessions: list[Session],
    now: datetime,
    quiet_hours: QuietHoursConfig,
    notified_set: set[str],
) -> list[DueEvent]:
    """Pure function: given all sessions and current time, return what's due.
    No I/O, no side effects — unit-testable without mocking time.sleep."""
    today_str = now.strftime("%Y-%m-%d")
    weekday_str = WEEKDAY_MAP[now.weekday()]
    due: list[DueEvent] = []

    if _in_quiet_hours(now, quiet_hours):
        return due

    for session in sessions:
        key = f"{session.name}_{today_str}"
        if key in notified_set:
            continue

        schedule = session.schedule
        run_today = session.last_run is not None and session.last_run.startswith(today_str)
        skipped_today = any(
            h.date == today_str and h.status == "skipped" for h in session.history
        )

        if run_today or skipped_today:
            continue

        # Boot sessions — fire once, immediately
        if schedule.on_boot:
            # Check if already fired today
            boot_fired = any(
                h.date == today_str and h.status == "launched" for h in session.history
            )
            if not boot_fired:
                due.append(DueEvent(
                    session_name=session.name,
                    kind="boot",
                    scheduled_time=None,
                ))
            continue

        # Time-based sessions
        if not schedule.time:
            continue
        # Empty days = "once" (run today); non-empty days must include today
        if schedule.days and weekday_str not in schedule.days:
            continue
        try:
            h, m = schedule.time.split(":")
            sched_dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        except (ValueError, AttributeError):
            continue

        # Heads-up: exactly 5 minutes before
        heads_up_dt = sched_dt - timedelta(minutes=HEADS_UP_MINUTES)
        if now >= heads_up_dt and now < sched_dt:
            due.append(DueEvent(
                session_name=session.name,
                kind="heads_up",
                scheduled_time=schedule.time,
            ))
            continue

        # Launch: exactly at scheduled time
        if now >= sched_dt and now < sched_dt + timedelta(minutes=1):
            due.append(DueEvent(
                session_name=session.name,
                kind="launch",
                scheduled_time=schedule.time,
            ))
            continue

        # Missed/catch-up: scheduled time already passed today, not yet run
        if now > sched_dt + timedelta(minutes=1):
            due.append(DueEvent(
                session_name=session.name,
                kind="missed",
                scheduled_time=schedule.time,
            ))
            continue

    return due


# ── Single-instance enforcement ──────────────────────────────────


def acquire_lock() -> bool:
    try:
        with open(LOCK_FILE_PATH, "x", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        # Check if process still exists
        try:
            pid_str = LOCK_FILE_PATH.read_text(encoding="utf-8").strip()
            pid = int(pid_str)
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x400000, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return False
            else:
                os.kill(pid, 0)
                return False
        except (OSError, ValueError, ProcessLookupError):
            pass
        # Stale lock — overwrite
        LOCK_FILE_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return False


def release_lock():
    try:
        if LOCK_FILE_PATH.exists():
            LOCK_FILE_PATH.unlink()
    except Exception:
        pass


# ── Auto-start registration ──────────────────────────────────────


def register_autostart(script_path: str) -> None:
    """Register daemon for Windows auto-start via registry Run key."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "KairosDaemon", 0, winreg.REG_SZ, script_path)
        logger.info("Registered Kairos daemon for auto-start.")
    except Exception as e:
        logger.error("Failed to register auto-start: %s", e)
        print(f"Error registering auto-start: {e}")


def unregister_autostart() -> None:
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "KairosDaemon")
        logger.info("Unregistered Kairos daemon auto-start.")
    except Exception as e:
        logger.error("Failed to unregister auto-start: %s", e)
        print(f"Error unregistering auto-start: {e}")


# ── Daemon entry point ───────────────────────────────────────────


class Daemon:
    def __init__(self):
        self._running = False
        self._notified_set: set[str] = set()
        self._widget_manager = None
        self._launched_today: set[str] = set()
        self._startup_done = False

    def set_widget_manager(self, mgr):
        self._widget_manager = mgr

    def run(self):
        if not acquire_lock():
            logger.error("Another Kairos daemon is already running.")
            print("Kairos daemon is already running.")
            return

        self._running = True
        logger.info("Kairos daemon started (PID %d)", os.getpid())

        try:
            self._run_catch_up()
            self._startup_done = True

            # ── Main loop ──
            while self._running:
                try:
                    self._tick()
                except Exception as e:
                    logger.error("Error in daemon tick: %s", e, exc_info=True)
                time.sleep(DAEMON_POLL_SECONDS)
        finally:
            release_lock()
            logger.info("Kairos daemon stopped.")

    def stop(self):
        self._running = False

    def _load_all_sessions(self) -> list[Session]:
        sessions = []
        for name in list_sessions():
            s = load_session(name)
            if s:
                sessions.append(s)
        return sessions

    def _run_catch_up(self):
        now = datetime.now()
        quiet = _load_quiet_hours()
        weekday_str = WEEKDAY_MAP[now.weekday()]
        sessions = self._load_all_sessions()

        for session in sessions:
            if not session.schedule.time:
                continue
            # Only catch up repeating sessions (have days set).
            # "Once" sessions (empty days) should fire at their exact time only,
            # not every time the daemon restarts.
            if not session.schedule.days:
                continue
            if weekday_str not in session.schedule.days:
                continue
            if session.last_run and session.last_run.startswith(now.strftime("%Y-%m-%d")):
                continue
            if any(h.status in ("skipped", "missed", "launched") and h.date == now.strftime("%Y-%m-%d") for h in session.history):
                continue

            try:
                h, m = session.schedule.time.split(":")
                sched_dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            except (ValueError, AttributeError):
                continue

            if now > sched_dt and not _in_quiet_hours(now, quiet):
                logger.info("Catch-up: session '%s' was scheduled at %s", session.name, session.schedule.time)
                self._trigger_launch(session, "missed")

        # Boot sessions
        for session in sessions:
            if session.schedule.on_boot:
                boot_fired = any(
                    h.date == now.strftime("%Y-%m-%d") and h.status == "launched" for h in session.history
                )
                if not boot_fired:
                    self._trigger_launch(session, "boot")

    def _tick(self):
        now = datetime.now()
        quiet = _load_quiet_hours()
        sessions = self._load_all_sessions()
        due_events = get_due_sessions(sessions, now, quiet, self._notified_set)

        for event in due_events:
            session = next((s for s in sessions if s.name == event.session_name), None)
            if session is None:
                continue

            key = f"{event.session_name}_{event.kind}_{now.strftime('%Y-%m-%d')}"
            if key in self._notified_set:
                continue
            self._notified_set.add(key)

            if event.kind == "heads_up":
                logger.info("Heads-up for session '%s'", session.name)
                if self._widget_manager:
                    self._widget_manager.show_heads_up(
                        session,
                        on_open_now=lambda w, s=session: self._on_open_now(s, w),
                        on_snooze=lambda w, s=session: self._on_snooze(s, w),
                    )
            elif event.kind in ("launch", "boot", "missed"):
                logger.info("Launching session '%s' (kind=%s)", session.name, event.kind)
                self._trigger_launch(session, event.kind)

    def _on_open_now(self, session: Session, widget):
        logger.info("User clicked 'Open Now' for session '%s'", session.name)
        self._trigger_launch(session, "launched_early")
        widget.close()

    def _on_snooze(self, session: Session, widget):
        logger.info("User snoozed session '%s'", session.name)
        widget.close()

    def _trigger_launch(self, session: Session, kind: str):
        if session.apps:
            launch_session(session.name, session.apps)

        session.last_run = datetime.now().isoformat(timespec="seconds")
        session.history.append(SessionLog(
            date=datetime.now().strftime("%Y-%m-%d"),
            status="launched",
            launched_at=datetime.now().isoformat(timespec="seconds"),
        ))
        save_session(session)

        if self._widget_manager:
            self._widget_manager.show_launched(session)

        # Show pending todos
        pending = [t for t in session.todos if not t.completed_today]
        if pending and self._widget_manager:
            for todo in pending:
                self._widget_manager.show_reminder(
                    todo.text,
                    on_done=lambda w, s=session, t=todo: self._on_todo_done(s, t, w),
                )

    def _on_todo_done(self, session: Session, todo, widget):
        todo.completed_today = True
        save_session(session)
        widget.close()
