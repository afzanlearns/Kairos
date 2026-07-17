from __future__ import annotations

import json
import re
import logging
from typing import Optional

import dateparser

from kairos.config import APP_MAPPING_PATH, STOPWORDS_PATH, DEFAULT_APP_MAPPING, DEFAULT_STOPWORDS, ensure_dirs
from kairos.models import ParsedLine

logger = logging.getLogger(__name__)


class StageResult:
    def __init__(self, items: list[ParsedLine]):
        self.items = items


def _load_stopwords() -> list[str]:
    if STOPWORDS_PATH.exists():
        return [
            line.strip().lower()
            for line in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    # Write defaults
    ensure_dirs()
    STOPWORDS_PATH.write_text("\n".join(DEFAULT_STOPWORDS), encoding="utf-8")
    return DEFAULT_STOPWORDS


def _load_app_mapping() -> dict:
    if APP_MAPPING_PATH.exists():
        return json.loads(APP_MAPPING_PATH.read_text(encoding="utf-8"))
    ensure_dirs()
    APP_MAPPING_PATH.write_text(
        json.dumps(DEFAULT_APP_MAPPING, indent=2), encoding="utf-8"
    )
    return DEFAULT_APP_MAPPING


# ── Stage 1: Strip filler words ──────────────────────────────────


def strip_fillers(line: str, stopwords: list[str]) -> str:
    words = line.split()
    filtered = [w for w in words if w.lower() not in stopwords]
    return " ".join(filtered)


# ── Stage 2: Extract time ────────────────────────────────────────


def extract_time(line: str) -> tuple[Optional[str], str]:
    """Returns (time_str, line_with_matched_time_removed).
    The cleaned line is passed to subsequent stages so time fragments
    (e.g. the colon in '18:45') don't leak into app/target extraction."""
    # 1. Check AM/PM patterns first (most explicit)
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", line, re.IGNORECASE)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3).lower()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            time_str = f"{h:02d}:{mi:02d}"
            cleaned = (line[:m.start()] + line[m.end():]).strip()
            return time_str, cleaned
    # 2. Check 24h HH:MM patterns
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", line)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            time_str = f"{h:02d}:{mi:02d}"
            cleaned = (line[:m.start()] + line[m.end():]).strip()
            return time_str, cleaned
    # 3. Try dateparser for fuzzy date/time extraction
    parsed = dateparser.parse(
        line,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if parsed:
        return parsed.strftime("%H:%M"), line
    return None, line


# ── Stage 3: Classify kind ───────────────────────────────────────


def classify_kind(line_lower: str, mapping: dict) -> str:
    if any(kw in line_lower for kw in ["boot", "bootup", "startup"]):
        return "boot_reminder"
    has_app_keyword = any(kw in line_lower for kw in ["open", "launch", "start", "play"])
    has_known_app = any(key.lower() in line_lower for key in mapping)
    if has_app_keyword and has_known_app:
        return "app_launch"
    if any(kw in line_lower for kw in ["remind me", "reminder", "don't forget", "make sure", "remember"]):
        return "todo"
    if has_app_keyword:
        return "app_launch"
    return "unparsed"


# ── Stage 4: Extract app/target ──────────────────────────────────


def extract_app_target(line: str, line_lower: str, mapping: dict) -> tuple[Optional[str], Optional[str]]:
    # Check for colon syntax first: e.g. "play youtube : https://..."
    colon_match = re.search(r":\s*(.+)", line)
    explicit_target = None
    if colon_match:
        raw_target = colon_match.group(1).strip()
        # Strip trailing time expressions and filler from the target
        raw_target = re.sub(r'\s+(?:at|@)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b.*$', '', raw_target, flags=re.IGNORECASE).strip()
        raw_target = re.sub(r'\s+\d{1,2}:\d{2}\b.*$', '', raw_target).strip()
        for kw in ["reminder", "remind me", "remember", "don't forget", "make sure"]:
            raw_target = re.sub(r'\s*' + re.escape(kw) + r'\s*', ' ', raw_target, flags=re.IGNORECASE)
        raw_target = raw_target.strip()
        # Strip trailing standalone prepositions left after time/keyword removal
        raw_target = re.sub(r'\s+(?:at|for|on|in|by|with|about)\s*$', '', raw_target, flags=re.IGNORECASE).strip()
        if raw_target:
            explicit_target = raw_target

    # Find which keyword from the mapping appears in the line
    matched_key = None
    for key in mapping:
        if key.lower() in line_lower:
            matched_key = key
            break

    if not matched_key:
        return None, explicit_target

    entry = mapping[matched_key]
    app_type = entry.get("type", "chrome")

    # If there's an explicit target after colon, use it
    if explicit_target:
        if _looks_like_url(explicit_target):
            return "chrome", explicit_target
        return app_type, explicit_target

    # Use default URL from mapping if present
    default_url = entry.get("url")
    if default_url:
        return app_type, default_url

    return app_type, None


def _looks_like_url(s: str) -> bool:
    return bool(re.match(r'^https?://', s)) or '.' in s and ' ' not in s


# ── Stage 5: Confidence ──────────────────────────────────────────


def assess_confidence(kind: str, time_val: Optional[str], app: Optional[str], line_lower: str) -> str:
    if kind == "unparsed":
        return "low"
    if kind == "boot_reminder":
        return "high"
    if kind == "todo":
        if time_val is None:
            return "low"
        return "high"
    if kind == "app_launch":
        if app is None:
            return "low"
        return "high"
    return "high"


# ── Main pipeline ────────────────────────────────────────────────


def parse_line(line: str) -> ParsedLine:
    stopwords = _load_stopwords()
    mapping = _load_app_mapping()

    raw = line.strip()
    if not raw:
        return ParsedLine(kind="unparsed", raw=raw, confidence="low")

    # Stage 1: strip fillers
    cleaned = strip_fillers(raw, stopwords)
    if not cleaned:
        cleaned = raw  # if everything was filler, keep original

    cleaned_lower = cleaned.lower()

    # Stage 2: extract time, removing the matched span from the working string
    time_val, line_for_stages = extract_time(cleaned)
    line_for_stages_lower = line_for_stages.lower()

    # Stage 3: classify (on time-free text)
    kind = classify_kind(line_for_stages_lower, mapping)

    # Stage 4: extract app/target (on time-free text so colons in HH:MM don't leak)
    app_type, target = extract_app_target(line_for_stages, line_for_stages_lower, mapping)

    # Build text for todos
    text = None
    if kind in ("todo", "boot_reminder"):
        text = line_for_stages
        for kw in ["remind me", "reminder", "don't forget", "make sure", "remember", "regarding", "about", "set a", "set an", "to"]:
            text = re.sub(r'\b' + re.escape(kw) + r'\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip().strip(",").strip(".").strip()
        if not text or len(text) < 3 or text.lower() in ("to", "set", "a", "an", "the", "for", "set a", "remind"):
            text = raw

    # Stage 5: confidence
    confidence = assess_confidence(kind, time_val, app_type, line_for_stages_lower)

    # If no time and not boot, low confidence
    if kind == "todo" and not time_val:
        confidence = "low"

    return ParsedLine(
        kind=kind,
        time=time_val,
        app=app_type,
        target=target,
        text=text or raw,
        confidence=confidence,
        raw=raw,
    )


def parse_session_input(text: str) -> StageResult:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    items = [parse_line(l) for l in lines]
    return StageResult(items=items)
