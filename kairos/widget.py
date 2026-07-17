from __future__ import annotations

import sys
import time
import queue
import logging
import threading
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRect, QPoint, QTimer, QObject, pyqtProperty
)
from PyQt6.QtGui import QFont, QColor, QPainter, QPalette
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QScrollArea,
)

from kairos.models import AppItem, Session
from kairos.launcher import launch_session

logger = logging.getLogger(__name__)

DARK_BG = QColor("#1e1e1e")
DARKER_BG = QColor("#252526")
BORDER_COLOR = QColor("#3c3c3c")
TEXT_COLOR = QColor("#d4d4d4")
ACCENT_COLOR = QColor("#569cd6")
SUCCESS_COLOR = QColor("#6a9955")
WARN_COLOR = QColor("#d7ba7d")
FONT_FAMILY = "Consolas"


def _make_button(text: str, accent: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedHeight(28)
    btn.setFont(QFont(FONT_FAMILY, 9))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    style = (
        f"background: {ACCENT_COLOR.name()}; color: #fff; border: 1px solid {ACCENT_COLOR.name()};"
        if accent
        else f"background: {DARKER_BG.name()}; color: {TEXT_COLOR.name()}; border: 1px solid {BORDER_COLOR.name()};"
    )
    btn.setStyleSheet(
        f"QPushButton {{ {style} padding: 2px 12px; border-radius: 0px; }}"
        f"QPushButton:hover {{ border-color: {ACCENT_COLOR.name()}; }}"
    )
    return btn


class WidgetBase(QFrame):
    dismissed = None

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.dismissed = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"background: {DARK_BG.name()}; border: 1px solid {BORDER_COLOR.name()};"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
        title_label.setStyleSheet(f"color: {ACCENT_COLOR.name()}; border: none;")
        self._layout.addWidget(title_label)
        self._content = QVBoxLayout()
        self._content.setSpacing(4)
        self._layout.addLayout(self._content)

        self._btn_layout = QHBoxLayout()
        self._btn_layout.setSpacing(6)
        self._btn_layout.addStretch()
        self._layout.addLayout(self._btn_layout)

    def add_content(self, text: str, color: str | None = None) -> None:
        label = QLabel(text)
        label.setFont(QFont(FONT_FAMILY, 9))
        label.setWordWrap(True)
        c = color or TEXT_COLOR.name()
        label.setStyleSheet(f"color: {c}; border: none;")
        self._content.addWidget(label)

    def add_button(self, text: str, callback, accent: bool = False) -> QPushButton:
        btn = _make_button(text, accent=accent)
        btn.clicked.connect(callback)
        self._btn_layout.insertWidget(self._btn_layout.count() - 1, btn)
        return btn

    def add_dismiss(self, text: str = "Dismiss") -> QPushButton:
        return self.add_button(text, self._on_dismiss)

    def _on_dismiss(self):
        self.dismissed = True
        self.close()


class HeadsUpWidget(WidgetBase):
    def __init__(self, session: Session, on_open_now, on_snooze, parent=None):
        title = f"{session.name} — in 5 min" if session.schedule.time else f"{session.name}"
        super().__init__(title, parent=parent)

        if session.note:
            self.add_content(session.note, color=WARN_COLOR.name())

        pending = [t for t in session.todos if not t.completed_today]
        if pending:
            for t in pending:
                self.add_content(f"\u25e6 {t.text}", color=TEXT_COLOR.name())

        self.add_button("Open Now", lambda: on_open_now(self), accent=True)
        self.add_button("Snooze 5m", lambda: on_snooze(self))
        self.add_dismiss("Skip Today")


class LaunchedWidget(WidgetBase):
    def __init__(self, session: Session, parent=None):
        title = f"{session.name} — starting now"
        super().__init__(title, parent=parent)

        for app in session.apps:
            desc = f"\u2713 {app.type}"
            if app.urls:
                desc += f" ({len(app.urls)} tabs)"
            if app.run:
                desc += f" ({app.run})"
            self.add_content(desc, color=SUCCESS_COLOR.name())

        if session.note:
            self.add_content(session.note, color=WARN_COLOR.name())

        pending = [t for t in session.todos if not t.completed_today]
        if pending:
            for t in pending:
                self.add_content(f"\u25e6 {t.text}", color=TEXT_COLOR.name())

        self.add_button("Got it", lambda: self._on_dismiss(), accent=True)


class ReminderWidget(WidgetBase):
    def __init__(self, text: str, on_done, parent=None):
        super().__init__("Reminder", parent=parent)
        self.add_content(text)

        self.add_button("Done", lambda: on_done(self), accent=True)
        self.add_dismiss()


class WidgetManager(QObject):
    """Thread-safe widget manager that dispatches all Qt operations to the main thread.

    Daemon threads push widget requests into a queue; a QTimer on the main
    Qt event loop polls the queue and creates/updates widgets.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._app: QApplication | None = None
        self._widgets: list[SlidingWidget] = []
        self._running = False
        self._ready = threading.Event()
        self._req_queue: queue.Queue = queue.Queue()
        self._poll_timer: QTimer | None = None

    def start(self):
        self._running = True
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._process_queue)
        self._poll_timer.start(100)

    def mark_ready(self):
        self._ready.set()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self):
        self._running = False
        if self._poll_timer:
            self._poll_timer.stop()
        for w in self._widgets:
            w.close()
        if self._app:
            self._app.quit()

    def _process_queue(self):
        try:
            while True:
                req = self._req_queue.get_nowait()
                method, args, kwargs = req
                getattr(self, f"_do_{method}")(*args, **kwargs)
        except queue.Empty:
            pass

    def show_heads_up(self, session: Session, on_open_now=None, on_snooze=None):
        self._req_queue.put(("heads_up", (session, on_open_now, on_snooze), {}))

    def show_launched(self, session: Session):
        self._req_queue.put(("launched", (session,), {}))

    def show_reminder(self, text: str, on_done=None):
        self._req_queue.put(("reminder", (text, on_done), {}))

    def _do_heads_up(self, session: Session, on_open_now, on_snooze):
        if not self._running:
            return
        widget = SlidingWidget(HeadsUpWidget(session, on_open_now, on_snooze))
        self._widgets.append(widget)
        widget.show_slide_in()
        QTimer.singleShot(18000, lambda: self._auto_dismiss(widget))

    def _do_launched(self, session: Session):
        if not self._running:
            return
        widget = SlidingWidget(LaunchedWidget(session))
        self._widgets.append(widget)
        widget.show_slide_in()
        QTimer.singleShot(18000, lambda: self._auto_dismiss(widget))

    def _do_reminder(self, text: str, on_done=None):
        if not self._running:
            return
        widget = SlidingWidget(ReminderWidget(text, on_done))
        self._widgets.append(widget)
        widget.show_slide_in()
        QTimer.singleShot(18000, lambda: self._auto_dismiss(widget))

    def _auto_dismiss(self, widget):
        if widget in self._widgets and not widget.inner.dismissed:
            widget.slide_out()
            self._widgets.remove(widget)


class SlidingWidget(QWidget):
    def __init__(self, inner: WidgetBase):
        super().__init__(
            flags=Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        )
        self.inner = inner
        self._anim_offset = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(f"background: {DARK_BG.name()}; border: 1px solid {BORDER_COLOR.name()};")

        self.adjustSize()

        screen = self.screen().availableGeometry() if self.screen() else QApplication.primaryScreen().availableGeometry()
        self._target_x = screen.right() - self.width() - 12
        self._target_y = screen.bottom() - self.height() - 48
        self.move(screen.right(), self._target_y)

        self._anim = QPropertyAnimation(self, b"offset")
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_offset(self):
        return self._anim_offset

    def set_offset(self, val):
        self._anim_offset = val
        screen = self.screen().availableGeometry() if self.screen() else QApplication.primaryScreen().availableGeometry()
        x = screen.right() + int(val)
        self.move(x, self._target_y)

    offset = pyqtProperty(float, get_offset, set_offset)

    def show_slide_in(self):
        self.show()
        self._anim.setDuration(300)
        self._anim.setStartValue(0)
        self._anim.setEndValue(-self.width() - 12)
        self._anim.start()

    def slide_out(self):
        self._anim.setDuration(200)
        self._anim.setStartValue(-self.width() - 12)
        self._anim.setEndValue(0)
        self._anim.finished.connect(self.close)
        self._anim.start()


def show_widgets_cli(
    launched_sessions: list[Session] | None = None,
    reminders: list[tuple[str, callable]] | None = None,
    timeout_ms: int = 8000,
):
    """Show widgets from a CLI context using a temporary QApplication.

    Creates a short-lived Qt event loop, displays the given widgets,
    and exits after *timeout_ms* or when all widgets are dismissed.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    mgr = WidgetManager()
    mgr._app = app
    mgr.start()
    mgr.mark_ready()

    if launched_sessions:
        for s in launched_sessions:
            mgr.show_launched(s)
    if reminders:
        for text, on_done in reminders:
            mgr.show_reminder(text, on_done or (lambda w: None))

    # Process queue immediately so widgets appear before event loop
    mgr._process_queue()

    if mgr._widgets:
        QTimer.singleShot(timeout_ms, app.quit)
        app.exec()


def run_widget_app(widget_manager: WidgetManager):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    widget_manager._app = app
    widget_manager.mark_ready()
    widget_manager.start()
    app.exec()
