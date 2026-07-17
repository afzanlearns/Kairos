from __future__ import annotations

"""Regression tests for widget redesign (JetBrains Mono spec).

Note: Button hover/pressed state QSS verification is a visual/manual check
since QSS pseudo-states are hard to automate. See the QSS block in widget.py
for the exact #primary, #primary:hover, #primary:pressed rules.
"""

import sys
import pytest
from PyQt6.QtWidgets import QApplication, QPushButton, QLabel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestWidgetNaming:
    """unnamed-session fallback (never show blank pill or 'none')."""

    def test_empty_name_becomes_unnamed_session(self, qapp):
        from kairos.widget import _make_pill
        btn = _make_pill("")
        assert btn.text() == "unnamed-session"

    def test_none_name_becomes_unnamed_session(self, qapp):
        from kairos.widget import _make_pill
        btn = _make_pill(None)
        assert btn.text() == "unnamed-session"

    def test_whitespace_name_becomes_unnamed_session(self, qapp):
        from kairos.widget import _make_pill
        btn = _make_pill("   ")
        assert btn.text() == "unnamed-session"

    def test_valid_name_preserved(self, qapp):
        from kairos.widget import _make_pill
        btn = _make_pill("youtube")
        assert btn.text() == "youtube"


class TestReminderWrapping:
    """Reminder text must wrap fully with no truncation/ellipsis."""

    def test_long_text_wraps_no_truncation(self, qapp):
        from kairos.widget import ReminderWidget
        long_text = (
            "This is a very long reminder text that should wrap across "
            "multiple lines without being truncated or having an ellipsis "
            "added to the end of it. Edge case: Long Wrap — make sure "
            "the widget doesn't cut this off at any point."
        ) * 2
        w = ReminderWidget(long_text, on_done=lambda w: None)
        w.adjustSize()
        single_line_est = 40
        assert w.height() > single_line_est, (
            f"Widget height {w.height()} suggests text was truncated"
        )
        w.close()


class TestDesignTokens:
    """Verify exact hex values used in widget QSS."""

    def test_primary_button_colors(self, qapp):
        from kairos.widget import _PRIMARY, _PRIMARY_HOVER, _PRIMARY_PRESSED, _PRIMARY_BORDER
        assert _PRIMARY == "#3b659c"
        assert _PRIMARY_HOVER == "#4a77b3"
        assert _PRIMARY_PRESSED == "#345c8f"
        assert _PRIMARY_BORDER == "#4c7cb8"

    def test_secondary_button_colors(self, qapp):
        from kairos.widget import _SECONDARY, _SECONDARY_HOVER, _SECONDARY_PRESSED
        assert _SECONDARY == "#1c1c20"
        assert _SECONDARY_HOVER == "#27272c"
        assert _SECONDARY_PRESSED == "#161619"

    def test_font_families_resolved(self, qapp):
        from kairos.widget import _load_fonts
        _load_fonts()
        from kairos.widget import MONO, SANS
        assert MONO is not None
        assert SANS is not None


class TestHeadsUpWidget:
    """Heads-up widget structure."""

    def test_pill_rendered(self, qapp):
        from kairos.models import Session
        from kairos.widget import HeadsUpWidget
        s = Session(name="test-session")
        w = HeadsUpWidget(s, on_open_now=lambda w: None, on_snooze=lambda w: None)
        pills = w.findChildren(QPushButton)
        assert any(b.objectName() == "pill" for b in pills), "No pill button found"
        w.close()
