from __future__ import annotations

import pytest

from kairos.nlp import (
    strip_fillers, extract_time, classify_kind,
    extract_app_target, parse_line, _load_app_mapping,
)

MAPPING = _load_app_mapping()

STOPWORDS = ["mate", "please", "like", "um", "just", "could", "would", "maybe"]


def test_strip_fillers():
    result = strip_fillers("please open vscode like um just now", STOPWORDS)
    assert result == "open vscode now"


def test_extract_time_24h():
    assert extract_time("at 19:00") == "19:00"
    assert extract_time("meeting at 14:30") == "14:30"


def test_extract_time_12h():
    assert extract_time("at 6 pm") == "18:00"
    assert extract_time("at 7:30 pm") == "19:30"
    assert extract_time("at 9 am") == "09:00"


def test_extract_time_none():
    assert extract_time("open vscode") is None


def test_classify_todo():
    assert classify_kind("remind me to do something", MAPPING) == "todo"
    assert classify_kind("set a reminder for meeting", MAPPING) == "todo"
    assert classify_kind("don't forget to buy milk", MAPPING) == "todo"
    assert classify_kind("make sure to check email", MAPPING) == "todo"


def test_classify_app_launch():
    assert classify_kind("open vscode", MAPPING) == "app_launch"
    assert classify_kind("launch chrome", MAPPING) == "app_launch"
    assert classify_kind("start terminal", MAPPING) == "app_launch"
    assert classify_kind("play music", MAPPING) == "app_launch"


def test_classify_boot():
    assert classify_kind("bootup reminder", MAPPING) == "boot_reminder"
    assert classify_kind("startup check", MAPPING) == "boot_reminder"
    assert classify_kind("on boot", MAPPING) == "boot_reminder"


def test_classify_unparsed():
    assert classify_kind("some random text", MAPPING) == "unparsed"


CASES = [
    (
        "Open vscode at 7 pm",
        {"kind": "app_launch", "app": "code", "time": "19:00", "confidence": "high"},
    ),
    (
        "Set a reminder for meeting at 7:30 pm",
        {"kind": "todo", "time": "19:30", "confidence": "high"},
    ),
    (
        "Bootup reminder regarding GitHub check",
        {"kind": "boot_reminder", "time": None, "confidence": "high"},
    ),
    (
        "Remind me to reply to client email",
        {"kind": "todo", "time": None, "confidence": "low"},
    ),
    (
        "play youtube at 6 pm",
        {"kind": "app_launch", "app": "chrome", "time": "18:00", "confidence": "high"},
    ),
    (
        "open terminal",
        {"kind": "app_launch", "app": "terminal", "time": None, "confidence": "high"},
    ),
    (
        "some completely ambiguous line",
        {"kind": "unparsed", "confidence": "low"},
    ),
    (
        "play youtube : https://youtube.com/watch?v=xyz at 6pm reminder",
        {"kind": "app_launch", "app": "chrome", "time": "18:00", "target": "https://youtube.com/watch?v=xyz", "confidence": "high"},
    ),
]


def test_all_cases():
    for input_text, expected in CASES:
        result = parse_line(input_text)
        assert result.kind == expected["kind"], (
            f"Input: {input_text!r} — expected kind={expected['kind']}, got {result.kind}"
        )
        if "app" in expected:
            assert result.app == expected["app"], (
                f"Input: {input_text!r} — expected app={expected['app']}, got {result.app}"
            )
        if "time" in expected:
            assert result.time == expected["time"], (
                f"Input: {input_text!r} — expected time={expected['time']}, got {result.time}"
            )
        if "confidence" in expected:
            assert result.confidence == expected["confidence"], (
                f"Input: {input_text!r} — expected confidence={expected['confidence']}, got {result.confidence}"
            )
        if "target" in expected:
            assert result.target == expected["target"], (
                f"Input: {input_text!r} — expected target={expected['target']}, got {result.target}"
            )
