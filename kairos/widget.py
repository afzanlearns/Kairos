from __future__ import annotations

import sys
import logging
import threading
import queue
import winsound
from datetime import datetime
from typing import Optional, Callable

from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QTimer, QObject, pyqtProperty, pyqtSignal
)
from PyQt6.QtGui import QFont, QFontDatabase, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame,
)

from kairos.models import Session

logger = logging.getLogger(__name__)

# ── Font loading ──────────────────────────────────────────────────

MONO: str | None = None
SANS: str | None = None

def _load_fonts():
    global MONO, SANS
    families = QFontDatabase.families()
    for f in ["JetBrains Mono", "Cascadia Mono", "Consolas"]:
        if f in families:
            MONO = f
            break
    if MONO is None:
        MONO = "Consolas"
    for f in ["Inter", "Segoe UI"]:
        if f in families:
            SANS = f
            break
    if SANS is None:
        SANS = "Segoe UI"
    logger.info("Widget fonts: mono=%s  sans=%s", MONO, SANS)


# ── Design tokens ─────────────────────────────────────────────────

_W = 320
_PAD = 12
_GAP = 12
_BTN_H = 28
_BTN_GAP = 8
_CORNER = 3
_CORNER_SM = 2
_GAP_STACK = 8

_BG = "#111113"
_BORDER = "#2f2f36"
_PILL_BG = "#1c1c20"
_PILL_TEXT = "#ececed"
_MUTED = "#a1a1aa"
_BODY = "#d1d1d6"
_DIMMED = "#85858e"
_PRIMARY = "#3b659c"
_PRIMARY_HOVER = "#4a77b3"
_PRIMARY_PRESSED = "#345c8f"
_PRIMARY_BORDER = "#4c7cb8"
_SECONDARY = "#1c1c20"
_SECONDARY_HOVER = "#27272c"
_SECONDARY_PRESSED = "#161619"
_CHECK_COLOR = "#446b9e"
_CHECKBOX_BORDER = "#4a4a52"

_QSS = f"""
QPushButton {{
    border-radius: {_CORNER_SM}px;
    font-size: 11px;
    padding: 0 12px;
    min-height: {_BTN_H}px;
    max-height: {_BTN_H}px;
    border: 1px solid;
}}
QPushButton#primary {{
    background: {_PRIMARY};
    color: #fff;
    border-color: {_PRIMARY_BORDER};
}}
QPushButton#primary:hover {{
    background: {_PRIMARY_HOVER};
}}
QPushButton#primary:pressed {{
    background: {_PRIMARY_PRESSED};
}}
QPushButton#secondary {{
    background: {_SECONDARY};
    color: {_BODY};
    border-color: {_BORDER};
}}
QPushButton#secondary:hover {{
    background: {_SECONDARY_HOVER};
}}
QPushButton#secondary:pressed {{
    background: {_SECONDARY_PRESSED};
}}
QPushButton#pill {{
    background: {_PILL_BG};
    color: {_PILL_TEXT};
    border-color: {_BORDER};
    border-radius: {_CORNER_SM}px;
    font-size: 13px;
    font-weight: 500;
    padding: 0 8px;
    min-height: 22px;
    max-height: 22px;
}}
QPushButton#pill:hover {{
    border-color: {_BORDER};
}}
"""


# ── Button factory ────────────────────────────────────────────────


def _make_pill(name: str) -> QPushButton:
    display = name if name and name.strip() else "unnamed-session"
    btn = QPushButton(display)
    btn.setObjectName("pill")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_QSS)
    return btn


def _make_primary(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("primary")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_QSS)
    return btn


def _make_secondary(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("secondary")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_QSS)
    return btn


# ── WidgetBase (redesigned) ───────────────────────────────────────


class WidgetBase(QFrame):
    """Base for all notification inner widgets. Each subclass builds its
    own header, body, and footer layout."""

    closed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dismissed = False
        self.setFixedWidth(_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        outer.setSpacing(_GAP)

        self._header = QVBoxLayout()
        self._header.setSpacing(4)
        outer.addLayout(self._header)

        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        outer.addLayout(self._body)

        self._footer = QHBoxLayout()
        self._footer.setSpacing(_BTN_GAP)
        outer.addLayout(self._footer)

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame {{ background: {_BG}; border: 1px solid {_BORDER}; border-radius: {_CORNER}px; }}"
        )

    def _add_pill(self, name: str) -> QPushButton:
        pill = _make_pill(name)
        pill_row = QHBoxLayout()
        pill_row.setSpacing(8)
        pill_row.addWidget(pill)
        pill_row.addStretch()
        self._header.addLayout(pill_row)
        return pill

    def _add_muted(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"color: {_MUTED}; font-family: '{MONO}'; font-size: 11px;"
            " border: none; background: transparent;"
        )
        self._header.addWidget(label)
        return label

    def _add_body_label(self, text: str, color: str = _BODY, font_size: int = 13) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {color}; font-family: '{SANS}'; font-size: {font_size}px;"
            " border: none; background: transparent;"
        )
        self._body.addWidget(label)
        return label

    def _add_checklist_row(self, indicator: str, icn_color: str, text: str, txt_color: str):
        row = QHBoxLayout()
        row.setSpacing(6)
        icon = QLabel(indicator)
        icon.setStyleSheet(
            f"color: {icn_color}; border: none; background: transparent; font-size: 12px;"
        )
        row.addWidget(icon)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(
            f"color: {txt_color}; font-family: '{SANS}'; font-size: 12px;"
            " border: none; background: transparent;"
        )
        row.addWidget(label, 1)
        self._body.addLayout(row)

    def _add_button_row(self, buttons: list[QPushButton]):
        for b in buttons:
            self._footer.addWidget(b)

    def closeEvent(self, event: QCloseEvent):
        self.dismissed = True
        self.closed.emit(self)
        super().closeEvent(event)

    def dismiss(self):
        self.dismissed = True
        self.close()


# ── HeadsUpWidget ─────────────────────────────────────────────────


class HeadsUpWidget(WidgetBase):
    def __init__(self, session: Session, on_open_now: Callable, on_snooze: Callable, parent=None):
        super().__init__(parent)
        self._add_pill(session.name)
        if session.schedule.time:
            try:
                h, m = session.schedule.time.split(":")
                sched = datetime.now().replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                mins = max(1, int((sched - datetime.now()).total_seconds() // 60))
                self._add_muted(f"in {mins} min")
            except Exception:
                pass
        if session.note:
            self._add_body_label(session.note)
        pending = [t for t in session.todos if not t.completed_today]
        if pending:
            for t in pending:
                self._add_checklist_row("\u25e6", _MUTED, t.text, _BODY)

        self._add_button_row([_make_primary("Open Now"), _make_secondary("Snooze 5m")])
        self._footer.itemAt(0).widget().clicked.connect(lambda: on_open_now(self))
        self._footer.itemAt(1).widget().clicked.connect(lambda: on_snooze(self))


# ── LaunchedWidget ────────────────────────────────────────────────


class LaunchedWidget(WidgetBase):
    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self._add_pill(session.name)
        self._add_muted("Starting now")
        if session.note:
            self._add_body_label(session.note)

        launched_apps = [a for a in session.apps]
        pending_todos = [t for t in session.todos if not t.completed_today]

        for app in launched_apps:
            desc = app.type
            if app.urls:
                desc += f" ({len(app.urls)} tabs)"
            if app.run:
                desc += f" ({app.run})"
            self._add_checklist_row("\u2713", _CHECK_COLOR, desc, _DIMMED)

        for t in pending_todos:
            self._add_checklist_row("\u25a1", _CHECKBOX_BORDER, t.text, _BODY)

        self._add_button_row([_make_secondary("Got it")])
        self._footer.itemAt(0).widget().clicked.connect(lambda: self.dismiss())


# ── ReminderWidget ────────────────────────────────────────────────


class ReminderWidget(WidgetBase):
    def __init__(self, text: str, on_done: Callable, parent=None):
        super().__init__(parent)
        lbl = QLabel("REMINDER")
        lbl.setStyleSheet(
            f"color: {_MUTED}; font-family: '{MONO}'; font-size: 11px; font-weight: 600;"
            " letter-spacing: 1px; border: none; background: transparent;"
        )
        self._header.addWidget(lbl)
        self._add_body_label(text)
        self._add_button_row([_make_primary("Done"), _make_secondary("Dismiss")])
        self._footer.itemAt(0).widget().clicked.connect(lambda: on_done(self))
        self._footer.itemAt(1).widget().clicked.connect(lambda: self.dismiss())


# ── MultiWidget (same-time merging) ───────────────────────────────


class MultiWidget(WidgetBase):
    """Compact merged widget for multiple due events in the same tick."""

    def __init__(self, items: list[tuple[str, str, Callable]], parent=None):
        """items: list of (display_name, action_label, action_callback)"""
        super().__init__(parent)
        self._add_muted(f"{len(items)} items due now")
        shown = items[:4]
        extra = len(items) - 4
        for display_name, action_label, callback in shown:
            row = QHBoxLayout()
            row.setSpacing(6)
            dot = QLabel("\u2022")
            dot.setStyleSheet(
                f"color: {_MUTED}; border: none; background: transparent; font-size: 12px;"
            )
            row.addWidget(dot)
            lbl = QLabel(display_name)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {_BODY}; font-family: '{SANS}'; font-size: 12px;"
                " border: none; background: transparent;"
            )
            row.addWidget(lbl, 1)
            act = _make_secondary(action_label)
            act.clicked.connect(callback)
            row.addWidget(act)
            self._body.addLayout(row)
        if extra > 0:
            more = QLabel(f"+{extra} more \u2014 click to see all")
            more.setStyleSheet(
                f"color: {_MUTED}; font-family: '{MONO}'; font-size: 10px;"
                " border: none; background: transparent;"
            )
            self._body.addWidget(more)
        self._add_button_row([_make_secondary("Dismiss all")])
        self._footer.itemAt(0).widget().clicked.connect(lambda: self.dismiss())


# ── SlidingWidget ─────────────────────────────────────────────────


class SlidingWidget(QFrame):
    """Wrapper that provides slide-in/out animation for a WidgetBase.
    Supports stacking: dimmed opacity for back widgets.
    Enforces always-on-top z-order via periodic raise_()."""

    _Z_TIMER_INTERVAL_MS = 2000

    def __init__(self, inner: WidgetBase, stack_index: int = 0):
        super().__init__(
            flags=Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.inner = inner
        self.stack_index = stack_index
        self._offset = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)
        self.setStyleSheet(f"background: {_BG}; border: 1px solid {_BORDER}; border-radius: {_CORNER}px;")

        self.adjustSize()
        # Start off-screen — WidgetManager positions via _position_widget / _reposition_all
        self.move(QApplication.primaryScreen().availableGeometry().right(), 0)

        self._anim = QPropertyAnimation(self, b"offset")
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._z_timer = QTimer(self)
        self._z_timer.setInterval(self._Z_TIMER_INTERVAL_MS)
        self._z_timer.timeout.connect(self._raise_to_top)

    def _raise_to_top(self):
        self.raise_()
        if self.isVisible():
            self.activateWindow()

    def get_offset(self):
        return self._offset

    def set_offset(self, val):
        self._offset = val
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() + int(val), self._target_y)

    offset = pyqtProperty(float, get_offset, set_offset)

    def show_slide_in(self):
        self.show()
        self.raise_()
        self._z_timer.start()
        self._anim.stop()
        self._anim.setDuration(250)
        self._anim.setStartValue(0)
        self._anim.setEndValue(-self.width() - _PAD)
        self._anim.start()

    def slide_out(self):
        self._z_timer.stop()
        self._anim.stop()
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setDuration(200)
        self._anim.setStartValue(-self.width() - _PAD)
        self._anim.setEndValue(0)
        self._anim.finished.connect(self._on_out_done)
        self._anim.start()

    def _on_out_done(self):
        self._z_timer.stop()
        self.close()
        self.deleteLater()

    def set_stack_position(self, index: int, count: int):
        """Apply dimming based on position in stack.
        Frontmost widget (index == count - 1) gets full opacity;
        back widgets get 0.6 (legibility floor)."""
        self.stack_index = index
        is_front = index == count - 1
        opacity = 1.0 if is_front else 0.6
        self.setWindowOpacity(opacity)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not is_front,
        )


# ── CollapsedOverlay ──────────────────────────────────────────────


class CollapsedOverlay(QFrame):
    """Small pill-shaped overlay shown when widgets are collapsed beyond the cap.
    Shares the same always-on-top window flags and z-order enforcement."""
    expand_requested = pyqtSignal()

    def __init__(self, count: int, parent=None):
        super().__init__(
            parent,
            flags=Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool,
        )
        self.setFixedWidth(_W)
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        self._label = QLabel()
        self._label.setStyleSheet(
            f"color: {_MUTED}; font-family: '{SANS}'; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self._label)
        self._btn = _make_secondary("Show")
        self._btn.clicked.connect(lambda: self.expand_requested.emit())
        layout.addWidget(self._btn)
        self.set_count(count)
        self.setStyleSheet(
            f"QFrame {{ background: {_BG}; border: 1px solid {_BORDER};"
            f" border-radius: {_CORNER}px; }}"
        )

        self._z_timer = QTimer(self)
        self._z_timer.setInterval(2000)
        self._z_timer.timeout.connect(self._raise_to_top)

    def _raise_to_top(self):
        self.raise_()
        if self.isVisible():
            self.activateWindow()

    def show(self):
        super().show()
        self.raise_()
        self._z_timer.start()

    def hide(self):
        self._z_timer.stop()
        super().hide()

    def set_count(self, n: int):
        self._label.setText(f"+{n} more")


# ── WidgetManager ─────────────────────────────────────────────────


class WidgetManager(QObject):
    """Thread-safe widget manager with stacked visual, same-time merging,
    and a hard cap on visible widgets (MAX_VISIBLE=2). Beyond the cap,
    items are collapsed into a '+N more' overlay."""

    _WIDGET_TIMEOUT_MS = 18000
    _MAX_VISIBLE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app: QApplication | None = None
        self._running = False
        self._ready = threading.Event()
        self._req_queue: queue.Queue = queue.Queue()
        self._active_stack: list[SlidingWidget] = []
        self._poll_timer: QTimer | None = None
        self._collapsed_items: list[WidgetBase] = []
        self._collapsed_descriptions: list[str] = []
        self._collapsed_overlay: CollapsedOverlay | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        _load_fonts()
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
        for sw in list(self._active_stack):
            sw.close()
            sw.deleteLater()
        self._active_stack.clear()
        self._collapsed_items.clear()
        self._collapsed_descriptions.clear()
        if self._collapsed_overlay:
            self._collapsed_overlay.hide()
            self._collapsed_overlay.deleteLater()
            self._collapsed_overlay = None
        if self._app:
            self._app.quit()

    def _prune_stack(self):
        for sw in list(self._active_stack):
            if not sw.isVisible() or sw.inner.dismissed:
                sw.deleteLater()
                self._active_stack.remove(sw)

    def _restack(self):
        self._prune_stack()
        self._promote_collapsed()
        self._reposition_all()
        if self._active_stack:
            self._schedule_auto_dismiss()

    def _promote_collapsed(self):
        while len(self._active_stack) < self._MAX_VISIBLE and self._collapsed_items:
            inner = self._collapsed_items.pop(0)
            self._collapsed_descriptions.pop(0)
            sw = SlidingWidget(inner, stack_index=len(self._active_stack))
            self._active_stack.append(sw)
            sw.show()
        self._update_collapsed_overlay()

    def _reposition_all(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - _W - _PAD
        base_y = screen.bottom() - 48
        cumulative = 0
        count = len(self._active_stack)
        for i, sw in enumerate(self._active_stack):
            sw.set_stack_position(i, count)
            h = sw.inner.height()
            y = base_y - h - cumulative
            sw._target_y = y
            sw._target_x = x
            sw.move(x, y)
            cumulative += h + _GAP_STACK

    # ── Queue processing ──

    def _process_queue(self):
        try:
            while True:
                req = self._req_queue.get_nowait()
                method, args, kwargs = req
                try:
                    getattr(self, f"_do_{method}")(*args, **kwargs)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "Error processing widget request: %s", method
                    )
        except queue.Empty:
            pass

    # ── Public thread-safe API ──

    def show_heads_up(self, session: Session, on_open_now=None, on_snooze=None):
        self._req_queue.put(("heads_up", (session, on_open_now, on_snooze), {}))

    def show_launched(self, session: Session):
        self._req_queue.put(("launched", (session,), {}))

    def show_reminder(self, text: str, on_done=None):
        self._req_queue.put(("reminder", (text, on_done), {}))

    def show_batch(self, kind: str, sessions_or_texts: list, callbacks: list | None = None):
        """Show a batch of events that fired in the same tick.
        Multiple items → merged MultiWidget; single item → normal widget."""
        self._req_queue.put(("batch", (kind, sessions_or_texts, callbacks or []), {}))

    # ── Dispatch methods (Qt thread) ──

    def _do_heads_up(self, session: Session, on_open_now, on_snooze):
        if not self._running:
            return
        inner = HeadsUpWidget(session, on_open_now, on_snooze)
        self._push_widget(inner)

    def _do_launched(self, session: Session):
        if not self._running:
            return
        inner = LaunchedWidget(session)
        self._push_widget(inner)

    def _do_reminder(self, text: str, on_done=None):
        if not self._running:
            return
        inner = ReminderWidget(text, on_done or (lambda w: None))
        self._push_widget(inner)

    def _do_batch(self, kind: str, items: list, callbacks: list):
        if not self._running or not items:
            return
        if len(items) == 1:
            if kind == "heads_up":
                cb = callbacks[0] if callbacks else (None, None)
                on_open, on_snooze = cb if isinstance(cb, (list, tuple)) else (cb, None)
                self._do_heads_up(items[0], on_open, on_snooze)
            elif kind == "launched":
                self._do_launched(items[0])
            elif kind == "reminder":
                self._do_reminder(items[0], callbacks[0] if callbacks else None)
            return
        # Build MultiWidget entries
        entries = []
        for i, item in enumerate(items):
            cb = callbacks[i] if i < len(callbacks) else (lambda w: None)
            display = item.name if hasattr(item, "name") else str(item)[:40]
            entry = (display, "Open", cb)
            entries.append(entry)
        inner = MultiWidget(entries)
        self._push_widget(inner)

    def _push_widget(self, inner: WidgetBase):
        try:
            winsound.MessageBeep(winsound.MB_OK)
            logger.debug("Notification sound played for %s", type(inner).__name__)
        except Exception:
            logger.warning("Failed to play notification sound", exc_info=True)
        inner.closed.connect(self._on_inner_closed)

        if len(self._active_stack) >= self._MAX_VISIBLE:
            desc = self._describe_widget(inner)
            self._collapsed_items.append(inner)
            self._collapsed_descriptions.append(desc)
            self._show_collapsed_overlay()
            return

        self._do_push_widget(inner)

    def _do_push_widget(self, inner: WidgetBase):
        sw = SlidingWidget(inner, stack_index=len(self._active_stack))
        self._active_stack.append(sw)
        self._position_widget(sw)
        sw.show_slide_in()
        self._schedule_auto_dismiss()

    def _describe_widget(self, inner: WidgetBase) -> str:
        for child in inner.findChildren(QPushButton):
            if child.objectName() == "pill":
                return child.text()[:40]
        for child in inner.findChildren(QLabel):
            t = child.text()
            if t not in ("REMINDER",) and len(t) > 1:
                return t[:40]
        return "(item)"

    def _on_inner_closed(self, inner: WidgetBase):
        for sw in list(self._active_stack):
            if sw.inner is inner:
                self._active_stack.remove(sw)
                sw.slide_out()
                break
        QTimer.singleShot(400, self._restack)

    def _show_collapsed_overlay(self):
        n = len(self._collapsed_items)
        if n == 0:
            if self._collapsed_overlay:
                self._collapsed_overlay.hide()
            return
        if self._collapsed_overlay is None:
            self._collapsed_overlay = CollapsedOverlay(0)
            self._collapsed_overlay.expand_requested.connect(self._expand_collapsed)
        self._collapsed_overlay.set_count(n)
        self._position_collapsed_overlay()
        self._collapsed_overlay.show()

    def _position_collapsed_overlay(self):
        if not self._active_stack:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        last = self._active_stack[-1]
        base_y = screen.bottom() - 48
        cumulative = sum(
            sw.inner.height() + _GAP_STACK for sw in self._active_stack
        )
        self._collapsed_overlay.move(
            screen.right() - _W - _PAD,
            base_y - cumulative - 36 - _GAP_STACK,
        )

    def _update_collapsed_overlay(self):
        if self._collapsed_items:
            self._show_collapsed_overlay()
        elif self._collapsed_overlay:
            self._collapsed_overlay.hide()

    def _expand_collapsed(self):
        if not self._collapsed_items:
            return
        descriptions = list(self._collapsed_descriptions)
        items = list(self._collapsed_items)
        self._collapsed_items.clear()
        self._collapsed_descriptions.clear()
        if self._collapsed_overlay:
            self._collapsed_overlay.hide()

        inner = MultiWidget([
            (desc, "Open", lambda w: None) for desc in descriptions
        ])
        self._do_push_widget(inner)

    def _schedule_auto_dismiss(self):
        """Set auto-dismiss timer only for the frontmost widget."""
        if self._active_stack:
            QTimer.singleShot(
                self._WIDGET_TIMEOUT_MS,
                lambda: self._dismiss_frontmost() if self._active_stack else None,
            )

    def _position_widget(self, widget: SlidingWidget):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - _W - _PAD
        cumulative = sum(
            sw.inner.height() + _GAP_STACK
            for sw in self._active_stack[:-1]  # exclude the widget being positioned
        )
        widget._target_x = x
        widget._target_y = screen.bottom() - 48 - widget.inner.height() - cumulative
        widget.move(screen.right(), widget._target_y)
        # Dim all existing widgets behind the new one
        count = len(self._active_stack)
        for i, sw in enumerate(self._active_stack):
            if sw is not widget:
                sw.set_stack_position(i, count)

    def _dismiss_frontmost(self):
        if not self._active_stack:
            return
        front = self._active_stack[-1]
        if front.inner.dismissed:
            return
        front.inner.close()  # triggers closeEvent → closed signal → _on_inner_closed


# ── CLI helper ────────────────────────────────────────────────────


def show_widgets_cli(
    launched_sessions: list[Session] | None = None,
    reminders: list[tuple[str, Callable]] | None = None,
    timeout_per_widget_ms: int = 10000,
):
    app = QApplication.instance() or QApplication(sys.argv)
    mgr = WidgetManager()
    mgr._app = app
    mgr._WIDGET_TIMEOUT_MS = timeout_per_widget_ms
    mgr.start()
    mgr.mark_ready()

    if launched_sessions:
        for s in launched_sessions:
            mgr.show_launched(s)
    if reminders:
        for text, on_done in reminders:
            mgr.show_reminder(text, on_done or (lambda w: None))

    mgr._process_queue()

    if mgr._active_stack:
        total_timeout = (len(mgr._active_stack) * timeout_per_widget_ms) + 2000
        QTimer.singleShot(total_timeout, app.quit)
        app.exec()


def run_widget_app(widget_manager: WidgetManager):
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    widget_manager._app = app
    widget_manager.mark_ready()
    widget_manager.start()
    app.exec()
