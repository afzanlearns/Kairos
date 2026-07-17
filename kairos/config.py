from pathlib import Path
import os

USER_HOME = Path.home()
KAIROS_DIR = USER_HOME / ".kairos"
SESSIONS_DIR = KAIROS_DIR / "sessions"
LOGS_DIR = KAIROS_DIR / "logs"
DB_PATH = KAIROS_DIR / "kairos.db"
QUIET_HOURS_PATH = KAIROS_DIR / "quiet_hours.json"
APP_MAPPING_PATH = KAIROS_DIR / "app_mapping.json"
STOPWORDS_PATH = KAIROS_DIR / "stopwords.txt"
RECURRENCE_PHRASES_PATH = KAIROS_DIR / "recurrence_phrases.json"
LOCK_FILE_PATH = KAIROS_DIR / "daemon.lock"
HEARTBEAT_PATH = KAIROS_DIR / "heartbeat.json"
DAEMON_HEARTBEAT_MAX_AGE = 90

DEFAULT_APP_MAPPING = {
    "youtube": {"type": "chrome", "url": "youtube.com"},
    "vscode": {"type": "code"},
    "code": {"type": "code"},
    "spotify": {"type": "spotify"},
    "terminal": {"type": "terminal"},
    "wt": {"type": "terminal"},
    "chrome": {"type": "chrome"},
    "browser": {"type": "chrome"},
}

DEFAULT_STOPWORDS = ["mate", "please", "like", "um", "just", "could", "would", "maybe"]

DEFAULT_RECURRENCE_PHRASES = {
    "every day": {"days": ["mon","tue","wed","thu","fri","sat","sun"]},
    "daily": {"days": ["mon","tue","wed","thu","fri","sat","sun"]},
    "each day": {"days": ["mon","tue","wed","thu","fri","sat","sun"]},
    "every weekday": {"days": ["mon","tue","wed","thu","fri"]},
    "weekdays": {"days": ["mon","tue","wed","thu","fri"]},
    "every weekend": {"days": ["sat","sun"]},
    "weekend": {"days": ["sat","sun"]},
    "on boot": {"on_boot": True},
    "bootup": {"on_boot": True},
    "at startup": {"on_boot": True},
}

VALID_APP_TYPES = {"code", "terminal", "chrome", "spotify"}
INVALID_FS_CHARS = set('<>:"/\\|?*')
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
WIDGET_DISPLAY_SECONDS = 18
WIDGET_ANIMATION_MS = 300
DAEMON_POLL_SECONDS = 60
HEADS_UP_MINUTES = 5

WEEKDAY_NAMES = {
    "mon": "mon", "monday": "mon", "mondays": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue", "tuesdays": "tue",
    "wed": "wed", "weds": "wed", "wednesday": "wed", "wednesdays": "wed",
    "thu": "thu", "thurs": "thu", "thur": "thu", "thursday": "thu", "thursdays": "thu",
    "fri": "fri", "friday": "fri", "fridays": "fri",
    "sat": "sat", "saturday": "sat", "saturdays": "sat",
    "sun": "sun", "sunday": "sun", "sundays": "sun",
}


def ensure_dirs() -> None:
    for d in [KAIROS_DIR, SESSIONS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
