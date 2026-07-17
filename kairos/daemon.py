from __future__ import annotations

import logging
import sys
import time
import os
import signal
import threading
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
        # Specific date: only fire if today matches
        if schedule.date and schedule.date != today_str:
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

_MUTEX_HANDLE = None


def acquire_lock() -> bool:
    """Single-instance enforcement via Windows named mutex.
    Mutexes are kernel objects — automatically released by the OS when the
    owning process terminates (crash, kill, or normal exit), so there is no
    stale-lock / PID-recycling problem. A sidecar lock file is written for
    debugging visibility only."""
    global _MUTEX_HANDLE
    import ctypes
    kernel32 = ctypes.windll.kernel32
    mutex_name = "KairosDaemonMutex"
    _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, mutex_name)
    if not _MUTEX_HANDLE:
        logger.error("CreateMutexW failed (err=%d)", ctypes.GetLastError())
        return False
    err = ctypes.GetLastError()
    if err == 183:  # ERROR_ALREADY_EXISTS
        logger.warning("Another Kairos daemon is already running (mutex exists)")
        kernel32.CloseHandle(_MUTEX_HANDLE)
        _MUTEX_HANDLE = None
        return False
    # We own the mutex — write debug sidecar file
    import json
    try:
        LOCK_FILE_PATH.write_text(
            json.dumps({"pid": os.getpid(), "time": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8",
        )
    except Exception:
        pass
    return True


def release_lock():
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CloseHandle(_MUTEX_HANDLE)
        _MUTEX_HANDLE = None
    try:
        if LOCK_FILE_PATH.exists():
            LOCK_FILE_PATH.unlink()
    except Exception:
        pass


# ── Auto-start registration ──────────────────────────────────────

TASK_NAME = "KairosDaemon"


def _register_schtasks(pythonw_path: str, script_path: str) -> bool:
    """Register via Windows Task Scheduler (more robust than Run key).
    Returns True if registration succeeded, False if it should fall back."""
    import subprocess
    tr = f'"{pythonw_path}" "{script_path}"'
    for trigger in ['/sc onlogon', '/sc onstart /delay 0000:30']:
        cmd = f'schtasks /create /tn "{TASK_NAME}" /tr "{tr}" {trigger} /f'
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if r.returncode == 0:
            logger.info("Registered via Task Scheduler (%s)", trigger)
            print(f"Registered via Task Scheduler (trigger: {trigger.split()[1]}).")
            return True
        err_text = (r.stderr or "").lower()
        if "access is denied" in err_text:
            break
    logger.info("Task Scheduler not available (access denied), using Run key.")
    return False


def _register_runkey(script_path: str) -> None:
    """Fallback: register via Windows registry Run key."""
    import winreg
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    full_cmd = f'"{pythonw}" "{script_path}"'
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "KairosDaemon", 0, winreg.REG_SZ, full_cmd)
        logger.info("Registered Kairos daemon via Run key.")
        print("Registered via Run key (fallback).")
    except Exception as e:
        logger.error("Failed to register via Run key: %s", e)
        print(f"Error registering auto-start: {e}")


def register_autostart(script_path: str) -> None:
    """Register daemon for auto-start.
    Prefers Task Scheduler (more robust); falls back to registry Run key."""
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    try:
        if not _register_schtasks(pythonw, script_path):
            _register_runkey(script_path)
    except Exception as e:
        logger.error("schtasks registration failed: %s", e)
        _register_runkey(script_path)


def unregister_autostart() -> None:
    """Remove both Task Scheduler and Run key entries."""
    import winreg
    import subprocess
    # Remove Task Scheduler task
    subprocess.run(
        f'schtasks /delete /tn "{TASK_NAME}" /f',
        capture_output=True, text=True, shell=True,
    )
    # Remove registry Run key
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "KairosDaemon")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error("Failed to unregister Run key: %s", e)
    logger.info("Unregistered Kairos daemon auto-start.")
    print("Daemon unregistered from auto-start.")


# ── Daemon entry point ───────────────────────────────────────────


class Daemon:
    def __init__(self):
        self._running = False
        self._notified_set: set[str] = set()
        self._widget_manager = None
        self._launched_today: set[str] = set()
        self._startup_done = False
        self._snoozed_until: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def set_widget_manager(self, mgr):
        self._widget_manager = mgr

    def run(self):
        if not acquire_lock():
            logger.error("Another Kairos daemon is already running.")
            print("Kairos daemon is already running.")
            return

        self._running = True
        logger.info("Kairos daemon started (PID %d)", os.getpid())

        # Short startup delay to let filesystem/environment settle at boot
        time.sleep(2)

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
            # "Once" sessions (empty days) and date-specific sessions
            # should fire at their exact time only, not every time the daemon restarts.
            if not session.schedule.days or session.schedule.date:
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

        # Collect heads-up events by scheduled_time for batching
        heads_up_buckets: dict[str, list[Session]] = {}
        launch_sessions: list[Session] = []

        for event in due_events:
            session = next((s for s in sessions if s.name == event.session_name), None)
            if session is None:
                continue

            key = f"{event.session_name}_{event.kind}_{now.strftime('%Y-%m-%d')}"
            if key in self._notified_set:
                continue

            # Skip snoozed events
            snooze_key = f"{event.session_name}_heads_up_{now.strftime('%Y-%m-%d')}"
            with self._lock:
                snoozed_until = self._snoozed_until.get(snooze_key)
                if snoozed_until is not None:
                    if now < snoozed_until:
                        continue
                    del self._snoozed_until[snooze_key]

            self._notified_set.add(key)

            if event.kind == "heads_up":
                logger.info("Heads-up for session '%s'", session.name)
                bucket_key = event.scheduled_time or "0"
                heads_up_buckets.setdefault(bucket_key, []).append(session)
            elif event.kind in ("launch", "boot", "missed"):
                logger.info("Launching session '%s' (kind=%s)", session.name, event.kind)
                self._trigger_launch(session, event.kind)
                launch_sessions.append(session)

        # Dispatch batched heads-ups
        if self._widget_manager:
            for bucket_key, bucket_sessions in heads_up_buckets.items():
                if len(bucket_sessions) == 1:
                    s = bucket_sessions[0]
                    self._widget_manager.show_heads_up(
                        s,
                        on_open_now=lambda w, sess=s: self._on_open_now(sess, w),
                        on_snooze=lambda w, sess=s: self._on_snooze(sess, w),
                    )
                else:
                    callbacks = []
                    for s in bucket_sessions:
                        callbacks.append((
                            lambda w, sess=s: self._on_open_now(sess, w),
                            lambda w, sess=s: self._on_snooze(sess, w),
                        ))
                    self._widget_manager.show_batch("heads_up", bucket_sessions, callbacks)

    def _on_open_now(self, session: Session, widget):
        logger.info("User clicked 'Open Now' for session '%s'", session.name)
        self._trigger_launch(session, "launched_early")
        widget.close()

    def _on_snooze(self, session: Session, widget):
        logger.info("User snoozed session '%s' for 5 minutes", session.name)
        key = f"{session.name}_heads_up_{datetime.now().strftime('%Y-%m-%d')}"
        with self._lock:
            self._snoozed_until[key] = datetime.now() + timedelta(minutes=5)
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
