from __future__ import annotations

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


class AppItem(BaseModel):
    type: str
    path: Optional[str] = None
    cwd: Optional[str] = None
    run: Optional[str] = None
    urls: list[str] = []
    playlist: Optional[str] = None
    target: Optional[str] = None  # explicit target for nlp-based launch


class TodoItem(BaseModel):
    text: str
    completed_today: bool = False


class ScheduleConfig(BaseModel):
    time: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD for one-shot future dates
    days: list[str] = []
    on_boot: bool = False


class SessionLog(BaseModel):
    date: str
    status: str = "pending"  # pending, launched, skipped, missed
    launched_at: Optional[str] = None


class Session(BaseModel):
    name: str
    apps: list[AppItem] = []
    todos: list[TodoItem] = []
    schedule: ScheduleConfig = ScheduleConfig()
    note: str = ""
    last_run: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    history: list[SessionLog] = []


class QuietHoursConfig(BaseModel):
    start: str = ""  # HH:MM format
    end: str = ""


class DueEvent(BaseModel):
    session_name: str
    kind: str  # "heads_up", "launch", "boot", "missed"
    scheduled_time: Optional[str] = None


class ParsedLine(BaseModel):
    kind: str  # "app_launch", "todo", "boot_reminder", "unparsed"
    time: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD for one-shot future dates
    app: Optional[str] = None
    target: Optional[str] = None
    text: Optional[str] = None
    confidence: str = "high"  # "high" or "low"
    raw: str = ""
    days: Optional[list[str]] = None  # extracted weekdays, None if not specified
    on_boot: bool = False
    needs_recurrence_confirmation: bool = False
