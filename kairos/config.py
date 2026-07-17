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
LOCK_FILE_PATH = KAIROS_DIR / "daemon.lock"

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

VALID_APP_TYPES = {"code", "terminal", "chrome", "spotify"}
INVALID_FS_CHARS = set('<>:"/\\|?*')
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
WIDGET_DISPLAY_SECONDS = 18
WIDGET_ANIMATION_MS = 300
DAEMON_POLL_SECONDS = 60
HEADS_UP_MINUTES = 5


def ensure_dirs() -> None:
    for d in [KAIROS_DIR, SESSIONS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
