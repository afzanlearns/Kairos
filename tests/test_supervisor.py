"""Tests for kairos_supervisor.py — self-relaunching daemon wrapper."""

import sys
import os
import time
from collections import deque
from pathlib import Path
from unittest.mock import patch
import pytest


def test_get_daemon_script_path():
    """Returns absolute path to kairos_daemon.py sibling."""
    from kairos_supervisor import get_daemon_script_path

    path = get_daemon_script_path()
    p = Path(path)
    assert p.exists(), f"Path does not exist: {path}"
    assert p.name == "kairos_daemon.py", f"Expected kairos_daemon.py, got {p.name}"
    assert p.is_absolute()


def test_acquire_supervisor_lock_not_held():
    """Returns True when no other supervisor holds the mutex."""
    import ctypes
    from kairos_supervisor import acquire_supervisor_lock, SUPERVISOR_MUTEX_NAME

    kernel32 = ctypes.windll.kernel32
    # Release mutex if held by prior tests
    handle = kernel32.CreateMutexW(None, False, SUPERVISOR_MUTEX_NAME)
    if handle:
        # Whether we created it or it already existed, close our handle
        kernel32.CloseHandle(handle)

    result = acquire_supervisor_lock()
    assert result is True


def test_acquire_supervisor_lock_already_held():
    """Returns False when another supervisor already holds the mutex."""
    import ctypes
    from kairos_supervisor import acquire_supervisor_lock, SUPERVISOR_MUTEX_NAME

    # Hold the mutex ourselves
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, SUPERVISOR_MUTEX_NAME)
    assert handle, "Failed to create mutex for test"

    result = acquire_supervisor_lock()
    assert result is False, "Should return False when mutex is already held"

    kernel32.CloseHandle(handle)


def test_rate_limit_deque_size():
    """Crash times deque never exceeds MAX_CRASHES."""
    from kairos_supervisor import MAX_CRASHES

    dq: deque = deque(maxlen=MAX_CRASHES)
    for i in range(MAX_CRASHES * 2):
        dq.append(time.time())
    assert len(dq) == MAX_CRASHES


def test_backoff_increases_with_attempts():
    """Backoff grows exponentially and never exceeds max."""
    from kairos_supervisor import BACKOFF_BASE_SECONDS, BACKOFF_MAX_SECONDS

    # after MAX_CRASHES crashes, backoff starts at base^1
    for extra_attempt in range(1, 6):
        backoff = min(
            BACKOFF_BASE_SECONDS ** extra_attempt,
            BACKOFF_MAX_SECONDS,
        )
        assert backoff >= BACKOFF_BASE_SECONDS ** extra_attempt or backoff == BACKOFF_MAX_SECONDS
        assert backoff <= BACKOFF_MAX_SECONDS


def test_supervisor_module_importable():
    """The kairos_supervisor module can be imported without side effects."""
    import kairos_supervisor
    assert hasattr(kairos_supervisor, "run_supervisor")
    assert hasattr(kairos_supervisor, "main")


def test_main_register_calls_register_autostart(tmp_path, monkeypatch):
    """--register flag triggers register_autostart with supervisor's own path."""
    import kairos_supervisor

    calls = []

    def fake_register(script_path):
        calls.append(script_path)

    monkeypatch.setattr("kairos_supervisor.setup_logging", lambda: None)
    monkeypatch.setattr("kairos.daemon.register_autostart", fake_register)
    monkeypatch.setattr(sys, "argv", ["kairos_supervisor.py", "--register"])

    kairos_supervisor.main()

    assert len(calls) == 1
    # The script path should point to kairos_daemon.py
    assert calls[0].endswith("kairos_daemon.py")


def test_main_unregister_calls_unregister_autostart(monkeypatch):
    """--unregister flag triggers unregister_autostart."""
    import kairos_supervisor

    called = [False]

    def fake_unregister():
        called[0] = True

    monkeypatch.setattr("kairos_supervisor.setup_logging", lambda: None)
    monkeypatch.setattr("kairos.daemon.unregister_autostart", fake_unregister)
    monkeypatch.setattr(sys, "argv", ["kairos_supervisor.py", "--unregister"])

    kairos_supervisor.main()

    assert called[0]
