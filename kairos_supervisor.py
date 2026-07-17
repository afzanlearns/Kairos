#!python
"""Kairos supervisor — self-relaunching wrapper for kairos_daemon.py.

The supervisor monitors the daemon process and restarts it on crash,
with rate limiting and exponential backoff. This is the entry point
that Task Scheduler / Run key launches on login.

Usage:
    python kairos_supervisor.py              # Run supervisor
    python kairos_supervisor.py --register   # Register for auto-start
    python kairos_supervisor.py --unregister # Remove auto-start
"""
import sys
import os
import time
import logging
import logging.handlers
import subprocess
from collections import deque
from pathlib import Path

from kairos.config import LOGS_DIR, ensure_dirs

SUPERVISOR_MUTEX_NAME = "KairosSupervisorMutex"
MAX_CRASHES = 5
CRASH_WINDOW_SECONDS = 60
BACKOFF_BASE_SECONDS = 2
BACKOFF_MAX_SECONDS = 60


def setup_logging():
    ensure_dirs()
    log_path = LOGS_DIR / "supervisor.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def acquire_supervisor_lock() -> bool:
    """Single-instance enforcement for supervisor via Windows named mutex."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, SUPERVISOR_MUTEX_NAME)
    if not handle:
        return False
    err = ctypes.GetLastError()
    if err == 183:
        kernel32.CloseHandle(handle)
        return False
    return True


def get_daemon_script_path() -> str:
    return str(Path(__file__).resolve().parent / "kairos_daemon.py")


def run_supervisor():
    logger = logging.getLogger(__name__)
    if not acquire_supervisor_lock():
        logger.error("Another supervisor is already running.")
        print("Kairos supervisor is already running.")
        return

    logger.info("Supervisor starting (PID %d)", os.getpid())

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable

    daemon_script = get_daemon_script_path()
    crash_times: deque = deque(maxlen=MAX_CRASHES)
    attempt = 0

    while True:
        attempt += 1
        logger.info("Launching daemon (attempt %d)...", attempt)

        proc = subprocess.Popen(
            [pythonw, daemon_script],
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        proc.wait()
        exit_code = proc.returncode
        now = time.time()

        if exit_code == 0:
            logger.info("Daemon exited cleanly (code 0). Supervisor shutting down.")
            break

        crash_times.append(now)
        logger.warning(
            "Daemon crashed with exit code %d (attempt %d)",
            exit_code, attempt,
        )

        if len(crash_times) == MAX_CRASHES:
            window_start = crash_times[0]
            window_end = crash_times[-1]
            if window_end - window_start <= CRASH_WINDOW_SECONDS:
                backoff = min(
                    BACKOFF_BASE_SECONDS ** (attempt - MAX_CRASHES + 1),
                    BACKOFF_MAX_SECONDS,
                )
                logger.error(
                    "Rate limit hit: %d crashes in %.0fs. Backing off %ds.",
                    MAX_CRASHES, window_end - window_start, backoff,
                )
                time.sleep(backoff)

                if backoff >= BACKOFF_MAX_SECONDS:
                    logger.error(
                        "Max backoff reached (%ds). Supervisor giving up after %d attempts.",
                        BACKOFF_MAX_SECONDS, attempt,
                    )
                    break
            else:
                crash_times.clear()

        time.sleep(1)

    logger.info("Supervisor exiting (PID %d)", os.getpid())


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    args = [a.lower() for a in sys.argv[1:]]

    if "--register" in args:
        from kairos.daemon import register_autostart
        register_autostart(get_daemon_script_path())
        return

    if "--unregister" in args:
        from kairos.daemon import unregister_autostart
        unregister_autostart()
        return

    run_supervisor()


if __name__ == "__main__":
    main()
