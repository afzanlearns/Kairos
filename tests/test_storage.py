from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from kairos.models import Session, AppItem, TodoItem, ScheduleConfig
from kairos.storage import (
    session_exists, load_session, save_session, list_sessions,
    create_empty_session, delete_session, _session_path,
)


@pytest.fixture
def tmp_sessions_dir(tmp_path):
    from kairos import storage
    original = storage.SESSIONS_DIR
    storage.SESSIONS_DIR = tmp_path / "sessions"
    storage.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    yield storage.SESSIONS_DIR
    storage.SESSIONS_DIR = original


def test_create_empty_session(tmp_sessions_dir):
    s = create_empty_session("test-session")
    assert s.name == "test-session"
    assert s.apps == []
    assert s.todos == []
    assert session_exists("test-session")


def test_create_duplicate_fails(tmp_sessions_dir):
    create_empty_session("dup")
    with pytest.raises(FileExistsError):
        create_empty_session("dup")


def test_load_nonexistent(tmp_sessions_dir):
    assert load_session("nonexistent") is None


def test_save_and_load(tmp_sessions_dir):
    s = Session(
        name="work",
        apps=[AppItem(type="code", path="C:\\dev")],
        todos=[TodoItem(text="fix bug")],
    )
    save_session(s)
    loaded = load_session("work")
    assert loaded is not None
    assert loaded.name == "work"
    assert len(loaded.apps) == 1
    assert loaded.apps[0].type == "code"
    assert loaded.apps[0].path == "C:\\dev"
    assert len(loaded.todos) == 1
    assert loaded.todos[0].text == "fix bug"


def test_list_sessions(tmp_sessions_dir):
    create_empty_session("a")
    create_empty_session("b")
    names = list_sessions()
    assert names == ["a", "b"]


def test_delete_session(tmp_sessions_dir):
    create_empty_session("todelete")
    assert session_exists("todelete")
    delete_session("todelete")
    assert not session_exists("todelete")


def test_atomic_write_creates_valid_json(tmp_sessions_dir):
    """Check that saved file is valid JSON and has correct content."""
    s = Session(name="atomic_test")
    save_session(s)
    path = _session_path("atomic_test")
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["name"] == "atomic_test"


def test_corrupted_file_raises(tmp_sessions_dir):
    path = _session_path("corrupted")
    path.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupted"):
        load_session("corrupted")


def test_invalid_name_rejected(tmp_sessions_dir):
    from kairos.cli import _validate_name
    import click
    with pytest.raises(click.UsageError):
        _validate_name("file<name>")
    with pytest.raises(click.UsageError):
        _validate_name("")
