from __future__ import annotations

import json
import re
import logging
from typing import Optional

import dateparser

from kairos.config import (
    APP_MAPPING_PATH, STOPWORDS_PATH, RECURRENCE_PHRASES_PATH,
    DEFAULT_APP_MAPPING, DEFAULT_STOPWORDS, DEFAULT_RECURRENCE_PHRASES,
    WEEKDAY_NAMES, ensure_dirs,
)
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


def _load_recurrence_phrases() -> dict:
    if RECURRENCE_PHRASES_PATH.exists():
        return json.loads(RECURRENCE_PHRASES_PATH.read_text(encoding="utf-8"))
    ensure_dirs()
    RECURRENCE_PHRASES_PATH.write_text(
        json.dumps(DEFAULT_RECURRENCE_PHRASES, indent=2), encoding="utf-8"
    )
    return DEFAULT_RECURRENCE_PHRASES


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


# ── Stage 2b: Extract recurrence (days / on_boot) ────────────────


WEEKDAY_ABBREV = {
    "mon": "mon", "tue": "tue", "wed": "wed",
    "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
}


def extract_recurrence(line_lower: str, phrases: dict) -> tuple[Optional[list[str]], bool, str]:
    """Returns (days_list, on_boot, cleaned_line_lower).

    Checks for known recurrence phrases first, then parses inline
    weekday lists (e.g. 'every Mon Wed Fri', 'on Mondays and Fridays').
    Matched phrases are removed from the returned line so downstream
    stages don't see them.
    """
    cleaned = line_lower

    # 1. Check exact phrases from config
    for phrase, config in sorted(phrases.items(), key=lambda x: -len(x[0])):
        if phrase in cleaned:
            cleaned = cleaned.replace(phrase, "").strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if "days" in config:
                return config["days"], False, cleaned
            if "on_boot" in config:
                return None, True, cleaned

    # 2. Check for inline weekday lists: "every Mon Wed Fri", "on mondays and fridays", etc.
    #    Match patterns like: every <day1> <day2> ... / on <day1> and <day2> / <day1>, <day2>, ...
    weekday_pattern = r"(?:every|on)\s+((?:(?:mon|tue|wed|thu|fri|sat|sun)\w*(?:\s+(?:and\s+)?|\s*,\s*)?)+)"
    m = re.search(weekday_pattern, cleaned, re.IGNORECASE)
    if m:
        segment = m.group(1).lower()
        found = []
        for abbrev in WEEKDAY_ABBREV:
            if abbrev in segment:
                found.append(WEEKDAY_ABBREV[abbrev])
        # Also check full names
        for full_name, abbrev in WEEKDAY_NAMES.items():
            if full_name in segment and len(full_name) > 3:
                if abbrev not in found:
                    found.append(abbrev)
        if found:
            # Deduplicate preserving order
            seen = set()
            deduped = [d for d in found if not (d in seen or seen.add(d))]
            cleaned = cleaned[:m.start()] + cleaned[m.end():]
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return deduped, False, cleaned

    # Also check for weekday lists without "every" prefix, e.g. "Mondays, Wednesdays"
    m2 = re.search(
        r"\b((?:mon|tue|wed|thu|fri|sat|sun)\w*(?:\s+(?:and\s+)?|\s*,\s*)"
        r"(?:mon|tue|wed|thu|fri|sat|sun)\w*)",
        cleaned, re.IGNORECASE,
    )
    if m2:
        segment = m2.group(1).lower()
        found = []
        for full_name, abbrev in WEEKDAY_NAMES.items():
            if full_name in segment:
                if abbrev not in found:
                    found.append(abbrev)
        if found:
            cleaned = cleaned[:m2.start()] + cleaned[m2.end():]
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return found, False, cleaned

    return None, False, cleaned


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
        # No known app keyword found — try extracting target from remaining text
        # e.g. "open antigravity" → target="antigravity", app="chrome"
        for kw in ["open", "launch", "start", "play"]:
            pattern = re.compile(r'\b' + re.escape(kw) + r'\s+(.+)', re.IGNORECASE)
            m = pattern.search(line)
            if m:
                fallback_target = m.group(1).strip()
                if fallback_target:
                    return "chrome", fallback_target
        if explicit_target:
            return "chrome", explicit_target
        return None, None

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


def assess_confidence(
    kind: str, time_val: Optional[str], app: Optional[str], line_lower: str,
    days: Optional[list[str]] = None, on_boot: bool = False,
) -> str:
    if kind == "unparsed":
        return "low"
    if kind == "boot_reminder":
        return "high"
    if kind == "todo":
        if time_val is None:
            return "low"
        return "high"
    if kind == "app_launch":
        return "high"
    return "high"


# ── Main pipeline ────────────────────────────────────────────────


def parse_line(line: str) -> ParsedLine:
    stopwords = _load_stopwords()
    mapping = _load_app_mapping()
    recurrence_phrases = _load_recurrence_phrases()

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

    # Stage 3: classify BEFORE recurrence extraction so boot keywords are still present
    kind = classify_kind(line_for_stages_lower, mapping)

    # Stage 2b: extract recurrence (days / on_boot) — runs after classification
    # so boot keywords survive for kind-detection but are removed before app/target extraction
    days, on_boot, line_for_stages_lower = extract_recurrence(
        line_for_stages_lower, recurrence_phrases
    )
    line_for_stages = _reconstruct_original_case(line_for_stages, line_for_stages_lower)

    # Stage 4: extract app/target (on time+recurrence-free text)
    app_type, target = extract_app_target(line_for_stages, line_for_stages_lower, mapping)

    # Build text for todos
    text = None
    if kind in ("todo", "boot_reminder"):
        text = line_for_stages
        for kw in ["remind me", "reminder", "don't forget", "make sure", "remember", "regarding", "about", "set a", "set an", "to"]:
            text = re.sub(r'\b' + re.escape(kw) + r'\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip().strip(",").strip(".").strip()
        # Strip trailing prepositions left after keyword removal
        text = re.sub(r'\s+(?:at|for|on|in|by|with|about)\s*$', '', text, flags=re.IGNORECASE).strip()
        if not text or len(text) < 3 or text.lower() in ("to", "set", "a", "an", "the", "for", "set a", "remind"):
            text = raw

    # Stage 5: confidence
    confidence = assess_confidence(kind, time_val, app_type, line_for_stages_lower, days, on_boot)

    if kind == "todo" and not time_val and not on_boot:
        confidence = "low"

    # Determine if recurrence confirmation is needed: has a time but no days and not on_boot
    needs_recurrence_confirmation = (
        time_val is not None
        and days is None
        and not on_boot
        and kind != "unparsed"
        and kind != "boot_reminder"
    )

    return ParsedLine(
        kind=kind,
        time=time_val,
        app=app_type,
        target=target,
        text=text or raw,
        confidence=confidence,
        raw=raw,
        days=days,
        on_boot=on_boot,
        needs_recurrence_confirmation=needs_recurrence_confirmation,
    )


def _reconstruct_original_case(original: str, lower: str) -> str:
    """Reconstruct a case-preserved version of `original` from a lowercase
    version that may have had words removed. This is a best-effort scan."""
    if not original:
        return ""
    orig_words = original.split()
    lower_words = lower.split()
    if not lower_words:
        return ""
    # Simple greedy alignment: walk orig_words, keep words that appear in lower_words
    result = []
    li = 0
    for ow in orig_words:
        if li < len(lower_words) and ow.lower() == lower_words[li]:
            result.append(ow)
            li += 1
        elif li < len(lower_words) and ow.lower() in lower_words[li]:
            # Partial match (unlikely but handle gracefully)
            pass
    return " ".join(result)


def parse_session_input(text: str) -> StageResult:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    items = [parse_line(l) for l in lines]
    return StageResult(items=items)
