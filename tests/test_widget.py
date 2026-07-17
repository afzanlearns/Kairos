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


class TestStacking:
    """Multiple stacked widgets must not overlap, and back widgets dim."""

    def test_three_stacked_widgets_no_overlap(self, qapp):
        from kairos.models import Session
        from kairos.widget import (
            WidgetManager, _GAP_STACK,
            SlidingWidget, HeadsUpWidget, LaunchedWidget, ReminderWidget,
        )

        mgr = WidgetManager()
        mgr.start()
        mgr.mark_ready()
        mgr._process_queue()

        s1 = Session(name="alpha", note="first session")
        s2 = Session(name="beta", todo_items=[{"text": "task beta"}])
        s3 = Session(name="gamma", note="third session longer text here")

        inner1 = HeadsUpWidget(s1, on_open_now=lambda w: None, on_snooze=lambda w: None)
        sw1 = SlidingWidget(inner1, stack_index=0)
        mgr._active_stack.append(sw1)

        inner2 = LaunchedWidget(s2)
        sw2 = SlidingWidget(inner2, stack_index=1)
        mgr._active_stack.append(sw2)

        inner3 = ReminderWidget("reminder text for gamma", on_done=lambda w: None)
        sw3 = SlidingWidget(inner3, stack_index=2)
        mgr._active_stack.append(sw3)

        mgr._reposition_all()

        rects = [sw.geometry() for sw in mgr._active_stack]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not rects[i].intersects(rects[j]), (
                    f"Widget {i} ({rects[i]}) overlaps widget {j} ({rects[j]})"
                )

        for sw in mgr._active_stack:
            sw.close()
        mgr.stop()

    def test_back_widgets_have_lower_opacity(self, qapp):
        from kairos.models import Session
        from kairos.widget import (
            WidgetManager, _GAP_STACK,
            SlidingWidget, HeadsUpWidget, LaunchedWidget,
        )

        mgr = WidgetManager()
        mgr.start()
        mgr.mark_ready()
        mgr._process_queue()

        inner0 = HeadsUpWidget(
            Session(name="front"), on_open_now=lambda w: None, on_snooze=lambda w: None,
        )
        sw0 = SlidingWidget(inner0, stack_index=0)
        mgr._active_stack.append(sw0)

        inner1 = LaunchedWidget(Session(name="middle", todo_items=[{"text": "x"}]))
        sw1 = SlidingWidget(inner1, stack_index=1)
        mgr._active_stack.append(sw1)

        inner2 = LaunchedWidget(Session(name="back", todo_items=[{"text": "y"}, {"text": "z"}]))
        sw2 = SlidingWidget(inner2, stack_index=2)
        mgr._active_stack.append(sw2)

        mgr._reposition_all()

        assert sw0.windowOpacity() == pytest.approx(1.0, abs=0.01), "Frontmost should be full opacity"
        assert sw1.windowOpacity() == pytest.approx(0.6, abs=0.01), "Middle should be 0.6 opacity"
        assert sw2.windowOpacity() == pytest.approx(0.3, abs=0.01), "Back should be 0.3 opacity"

        for sw in mgr._active_stack:
            sw.close()
        mgr.stop()
