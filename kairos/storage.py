from __future__ import annotations

import json
import tempfile
import os
import shutil
from pathlib import Path
from typing import Optional

from kairos.config import SESSIONS_DIR, ensure_dirs
from kairos.models import Session


def _atomic_write(path: Path, data: str) -> None:
    ensure_dirs()
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=path.stem,
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        shutil.move(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _session_path(name: str) -> Path:
    return SESSIONS_DIR / f"{name}.json"


def session_exists(name: str) -> bool:
    return _session_path(name).exists()


def list_sessions() -> list[str]:
    ensure_dirs()
    return sorted(
        p.stem for p in SESSIONS_DIR.glob("*.json")
    )


def load_session(name: str) -> Optional[Session]:
    path = _session_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Session(**data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ValueError(f"Corrupted session file '{name}': {e}") from e


def save_session(session: Session) -> None:
    data = session.model_dump_json(indent=2, exclude_none=True)
    _atomic_write(_session_path(session.name), data)


def delete_session(name: str) -> None:
    path = _session_path(name)
    if path.exists():
        path.unlink()


def create_empty_session(name: str) -> Session:
    if session_exists(name):
        raise FileExistsError(f"Session '{name}' already exists.")
    session = Session(name=name)
    save_session(session)
    return session
