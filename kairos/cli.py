from __future__ import annotations

import sys
import logging
from datetime import datetime

import click

from kairos.config import (
    VALID_APP_TYPES, INVALID_FS_CHARS, ensure_dirs, APP_MAPPING_PATH,
    STOPWORDS_PATH, DEFAULT_APP_MAPPING, DEFAULT_STOPWORDS,
)
from kairos.models import Session, AppItem, TodoItem, ScheduleConfig, SessionLog
from kairos.storage import (
    session_exists, load_session, save_session, list_sessions,
    create_empty_session,
)
from kairos.launcher import launch_session
from kairos.nlp import parse_line, StageResult
from kairos.analytics import get_stats
from kairos.widget import show_widgets_cli

logger = logging.getLogger(__name__)


def _auto_session_name(item, used_names: set[str] | None = None) -> str:
    """Derive a session name from a parsed line's content."""
    from kairos.storage import list_sessions

    existing = set(list_sessions()) | (used_names or set())

    if item.kind == "app_launch":
        base = (item.target or item.app or "app").replace(".com", "").replace(".", "_").strip()
    elif item.kind == "todo":
        base = (item.text or item.raw or "reminder")[:30].strip()
    elif item.kind == "boot_reminder":
        base = (item.text or item.raw or "boot")[:30].strip()
    else:
        base = "task"

    base = base.strip(" ,.!?;:").strip()
    if not base or len(base) < 2:
        base = "task"

    if base not in existing:
        return base

    counter = 2
    while f"{base} ({counter})" in existing:
        counter += 1
    return f"{base} ({counter})"


def _validate_name(name: str) -> None:
    if not name or not name.strip():
        raise click.UsageError("Session name cannot be empty.")
    if any(c in name for c in INVALID_FS_CHARS):
        raise click.UsageError(
            f"Session name contains invalid filesystem characters: {INVALID_FS_CHARS}"
        )


def _require_session(name: str) -> Session:
    session = load_session(name)
    if session is None:
        raise click.UsageError(
            f"Session '{name}' does not exist. Use 'kairos new {name}' first."
        )
    return session


def _format_time(dt_str: str | None) -> str:
    if dt_str is None:
        return "never"
    return dt_str


def _print_session(session: Session) -> None:
    click.echo(f"Session: {session.name}")
    click.echo(f"  Created: {session.created_at}")
    click.echo(f"  Last run: {_format_time(session.last_run)}")
    click.echo(f"  Note: {session.note or '(none)'}")
    if session.schedule.time or session.schedule.on_boot:
        parts = []
        if session.schedule.time:
            parts.append(f"at {session.schedule.time}")
        if session.schedule.days:
            parts.append(f"on {', '.join(session.schedule.days)}")
        if session.schedule.on_boot:
            parts.append("on boot")
        click.echo(f"  Schedule: {' '.join(parts)}")
    else:
        click.echo("  Schedule: (none)")
    click.echo(f"\n  Apps ({len(session.apps)}):")
    for i, app in enumerate(session.apps):
        desc = app.type
        if app.path:
            desc += f" ({app.path})"
        if app.urls:
            desc += f" -> {', '.join(app.urls)}"
        if app.run:
            desc += f" run: {app.run}"
        if app.cwd:
            desc += f" cwd: {app.cwd}"
        if app.playlist:
            desc += f" playlist: {app.playlist}"
        click.echo(f"    [{i}] {desc}")
    click.echo(f"\n  Todos ({len(session.todos)}):")
    for i, todo in enumerate(session.todos):
        status = "x" if todo.completed_today else " "
        click.echo(f"    [{i}] [{status}] {todo.text}")
    click.echo(f"\n  History ({len(session.history)}):")
    for h in session.history[-5:]:
        click.echo(f"    {h.date}: {h.status}")
    click.echo()


# ── CLI group ────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Kairos — personal workflow orchestrator."""
    ensure_dirs()
    if ctx.invoked_subcommand is None:
        _show_daemon_status()


# ── new ───────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
def new(name: str):
    """Create a new empty session."""
    _validate_name(name)
    try:
        create_empty_session(name)
        click.echo(f"Created session '{name}'.")
    except FileExistsError as e:
        raise click.UsageError(str(e)) from e


# ── add ───────────────────────────────────────────────────────────


def _parse_app_type(ctx, param, value):
    if value is not None and value not in VALID_APP_TYPES:
        raise click.BadParameter(
            f"Invalid app type '{value}'. Valid types: {', '.join(sorted(VALID_APP_TYPES))}"
        )
    return value


@cli.command()
@click.argument("name")
@click.option("--code", "code_path", default=None, help="Path to open in VS Code")
@click.option("--terminal", "is_terminal", is_flag=True, help="Add a terminal")
@click.option("--cwd", default=None, help="Working directory for terminal")
@click.option("--run", default=None, help="Command to run in terminal")
@click.option("--chrome", "chrome_urls", multiple=True, help="URL(s) to open in Chrome")
@click.option("--spotify", "spotify_playlist", default=None, flag_value="", help="Open Spotify")
@click.option("--todo", default=None, help="Add a todo item")
def add(
    name: str,
    code_path: str | None,
    is_terminal: bool,
    cwd: str | None,
    run: str | None,
    chrome_urls: tuple[str, ...],
    spotify_playlist: str | None,
    todo: str | None,
):
    """Append an app or todo to a session."""
    session = _require_session(name)

    if code_path is not None:
        session.apps.append(AppItem(type="code", path=code_path))
        click.echo(f"Added 'code' app to '{name}'.")
    elif is_terminal:
        session.apps.append(AppItem(type="terminal", cwd=cwd, run=run))
        click.echo(f"Added 'terminal' app to '{name}'.")
    elif chrome_urls:
        session.apps.append(AppItem(type="chrome", urls=list(chrome_urls)))
        click.echo(f"Added 'chrome' app ({len(chrome_urls)} URL(s)) to '{name}'.")
    elif spotify_playlist is not None:
        session.apps.append(
            AppItem(type="spotify", playlist=spotify_playlist or None)
        )
        click.echo(f"Added 'spotify' app to '{name}'.")
    elif todo is not None:
        session.todos.append(TodoItem(text=todo))
        click.echo(f"Added todo to '{name}'.")
    else:
        raise click.UsageError(
            "Specify one of: --code, --terminal, --chrome, --spotify, --todo"
        )

    save_session(session)


# ── list ──────────────────────────────────────────────────────────


@cli.command(name="list")
def list_():
    """List all defined sessions."""
    names = list_sessions()
    if not names:
        click.echo("No sessions defined. Use 'kairos new <name>' to create one.")
        return
    for name in names:
        session = load_session(name)
        if session is None:
            continue
        app_count = len(session.apps)
        todo_count = len(session.todos)
        schedule = ""
        if session.schedule.time:
            schedule = f" @ {session.schedule.time}"
            if session.schedule.date:
                schedule += f" on {session.schedule.date}"
            if session.schedule.days:
                schedule += f" ({', '.join(session.schedule.days)})"
        if session.schedule.on_boot:
            schedule += " [boot]"
        click.echo(f"  {name:<24} {app_count} app(s), {todo_count} todo(s){schedule}")


# ── show ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
def show(name: str):
    """Pretty-print a session's full contents."""
    session = _require_session(name)
    _print_session(session)


# ── edit ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.option("--remove-app", default=None, help="Index of app to remove")
@click.option("--remove-todo", default=None, help="Index of todo to remove")
def edit(name: str, remove_app: str | None, remove_todo: str | None):
    """Remove an app or todo from a session."""
    session = _require_session(name)

    if remove_app is not None:
        try:
            idx = int(remove_app)
            removed = session.apps.pop(idx)
            click.echo(f"Removed app [{idx}]: {removed.type}")
        except (ValueError, IndexError) as e:
            raise click.UsageError(f"Invalid app index: {e}") from e

    if remove_todo is not None:
        try:
            idx = int(remove_todo)
            removed = session.todos.pop(idx)
            click.echo(f"Removed todo [{idx}]: {removed.text}")
        except (ValueError, IndexError) as e:
            raise click.UsageError(f"Invalid todo index: {e}") from e

    if remove_app is None and remove_todo is None:
        raise click.UsageError("Specify --remove-app <index> or --remove-todo <index>")

    save_session(session)


# ── note ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.argument("text")
def note(name: str, text: str):
    """Set or overwrite a session's note."""
    session = _require_session(name)
    session.note = text
    save_session(session)
    click.echo(f"Note set for '{name}'.")


# ── start ─────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.option("--no-gui", is_flag=True, help="Skip GUI widgets, output to terminal only")
def start(name: str, no_gui: bool):
    """Manually launch every app in a session."""
    session = _require_session(name)

    if not session.apps:
        click.echo(f"Session '{name}' has no apps configured — nothing to launch.")
        return

    click.echo(f"Launching session '{name}'...")
    launch_session(session.name, session.apps)

    session.last_run = datetime.now().isoformat(timespec="seconds")
    session.history.append(
        SessionLog(
            date=datetime.now().isoformat(timespec="seconds").split("T")[0],
            status="launched",
            launched_at=datetime.now().isoformat(timespec="seconds"),
        )
    )
    save_session(session)

    if not no_gui:
        try:
            pending = [t for t in session.todos if not t.completed_today]
            reminders = [(t.text, lambda w: None) for t in pending]
            show_widgets_cli(
                launched_sessions=[session],
                reminders=reminders,
                timeout_ms=8000,
            )
            return
        except Exception as e:
            logger.warning("Widget display failed, falling back to terminal: %s", e)

    if session.note:
        click.echo(f"\n  Note: {session.note}")

    pending = [t for t in session.todos if not t.completed_today]
    if pending:
        click.echo(f"\n  Pending todos ({len(pending)}):")
        for t in pending:
            click.echo(f"    [ ] {t.text}")


# ── done ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.argument("todo_text")
def done(name: str, todo_text: str):
    """Mark a todo as completed (fuzzy match)."""
    session = _require_session(name)
    matched = [
        t for t in session.todos
        if todo_text.lower() in t.text.lower()
    ]
    if not matched:
        raise click.UsageError(
            f"No todo matching '{todo_text}' found in session '{name}'."
        )
    for t in matched:
        t.completed_today = True
    save_session(session)
    if len(matched) == 1:
        click.echo(f"Marked todo '{matched[0].text}' as done.")
    else:
        click.echo(f"Marked {len(matched)} todos as done (matched '{todo_text}').")


# ── schedule ──────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
@click.option("--at", "at_time", default=None, help="Time in HH:MM format")
@click.option("--date", "date_str", default=None, help="Date in YYYY-MM-DD format")
@click.option("--days", default=None, help="Comma-separated weekdays (mon,tue,...)")
@click.option("--on-boot", "on_boot", is_flag=True, default=None, help="Run on boot")
def schedule(name: str, at_time: str | None, date_str: str | None, days: str | None, on_boot: bool | None):
    """Set scheduling for a session."""
    session = _require_session(name)
    if at_time is not None:
        session.schedule.time = at_time
    if date_str is not None:
        session.schedule.date = date_str
    if days is not None:
        session.schedule.days = [d.strip().lower() for d in days.split(",") if d.strip()]
    if on_boot is not None:
        session.schedule.on_boot = on_boot
    save_session(session)
    click.echo(f"Schedule updated for '{name}'.")


# ── today ─────────────────────────────────────────────────────────


@cli.command(name="today")
def today():
    """List sessions scheduled for today."""
    from datetime import date
    weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_str = weekday_map[date.today().weekday()]
    sessions = []
    for name in list_sessions():
        s = load_session(name)
        if s is None:
            continue
        if today_str in s.schedule.days or s.schedule.on_boot:
            sessions.append(s)
    sessions.sort(key=lambda s: s.schedule.time or "")
    if not sessions:
        click.echo("Nothing scheduled for today.")
        return
    click.echo(f"Scheduled for today ({today_str.capitalize()}):")
    for s in sessions:
        status = "pending"
        if s.last_run and s.last_run.startswith(str(date.today())):
            status = "launched"
        elif s.history and s.history[-1].date == str(date.today()) and s.history[-1].status == "skipped":
            status = "skipped"
        boot = " [boot]" if s.schedule.on_boot else ""
        click.echo(f"  {s.schedule.time or '--:--'}{boot}  {s.name:<24} {status}")


# ── next ──────────────────────────────────────────────────────────


@cli.command(name="next")
def next_():
    """Show the next upcoming session."""
    from datetime import datetime, date, timedelta
    weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    now = datetime.now()
    today_str = weekday_map[date.today().weekday()]
    upcoming = []
    overdue = []
    for name in list_sessions():
        s = load_session(name)
        if s is None or not s.schedule.time:
            continue
        if not s.schedule.days and not s.schedule.on_boot:
            continue
        if s.schedule.on_boot:
            continue
        if today_str not in s.schedule.days:
            continue
        try:
            h, m = s.schedule.time.split(":")
            sched_dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        except (ValueError, AttributeError):
            continue
        if sched_dt < now:
            overdue.append((s, sched_dt))
        else:
            upcoming.append((s, sched_dt))
    upcoming.sort(key=lambda x: x[1])
    overdue.sort(key=lambda x: x[1])
    if upcoming:
        s, dt = upcoming[0]
        delta = dt - now
        mins = int(delta.total_seconds() // 60)
        click.echo(f"Next: {s.name} at {s.schedule.time} (in ~{mins} min)")
    else:
        click.echo("No upcoming sessions today.")
    if overdue:
        for s, dt in overdue:
            delta = now - dt
            mins = int(delta.total_seconds() // 60)
            click.echo(f"Overdue: {s.name} (was due {mins} min ago)")


# ── skip ──────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
def skip(name: str):
    """Mark a session as skipped for today (no launch)."""
    session = _require_session(name)
    today_str = datetime.now().isoformat(timespec="seconds").split("T")[0]
    session.history.append(
        SessionLog(date=today_str, status="skipped")
    )
    save_session(session)
    click.echo(f"Session '{name}' skipped for today.")


# ── stats ─────────────────────────────────────────────────────────


@cli.command()
@click.argument("name")
def stats(name: str):
    """Show analytics summary for a session."""
    session = _require_session(name)
    result = get_stats(session.name, session.history)
    click.echo(f"Stats for '{session.name}':")
    click.echo(f"  Run {result['run_days']}/{result['total_days']} days in tracked period")
    click.echo(f"  Launched: {result['launched']}, Skipped: {result['skipped']}, Missed: {result['missed']}")
    click.echo(f"  Avg todos completed: {result['avg_todos_completed']:.1f}")


# ── config ────────────────────────────────────────────────────────


@cli.command()
@click.option("--quiet", "quiet_window", default=None, help="Quiet hours range HH:MM-HH:MM")
def config(quiet_window: str | None):
    """Set global daemon configuration."""
    from kairos.config import QUIET_HOURS_PATH
    from kairos.models import QuietHoursConfig
    if quiet_window:
        parts = quiet_window.split("-")
        if len(parts) != 2:
            raise click.UsageError("Use format HH:MM-HH:MM")
        qh = QuietHoursConfig(start=parts[0], end=parts[1])
        QUIET_HOURS_PATH.write_text(qh.model_dump_json(indent=2), encoding="utf-8")
        click.echo(f"Quiet hours set: {quiet_window}")


# ── daemon-status ─────────────────────────────────────────────────

def _show_daemon_status():
    """Print daemon status to stdout."""
    from kairos.daemon import is_daemon_running, read_heartbeat
    from kairos.config import DAEMON_HEARTBEAT_MAX_AGE
    from datetime import datetime

    running = is_daemon_running()
    hb = read_heartbeat()

    if not running:
        click.echo("Daemon: stopped")
        return

    if hb is None:
        click.echo("Daemon: running (no heartbeat data yet)")
        return

    try:
        hb_time = datetime.fromisoformat(hb["time"])
        age = (datetime.now() - hb_time).total_seconds()
        pid = hb.get("pid", "?")
        if age < DAEMON_HEARTBEAT_MAX_AGE:
            click.echo(f"Daemon: running (PID {pid}, last heartbeat {age:.0f}s ago)")
        else:
            click.echo(
                f"Daemon: stale/likely dead (PID {pid}, "
                f"last heartbeat {age:.0f}s ago — >{DAEMON_HEARTBEAT_MAX_AGE}s threshold)"
            )
    except (KeyError, ValueError) as e:
        click.echo(f"Daemon: running (corrupt heartbeat: {e})")


@cli.command(name="daemon-status")
def daemon_status():
    """Check whether the Kairos daemon is running and healthy."""
    _show_daemon_status()


# ── daemon-restart ────────────────────────────────────────────────

@cli.command(name="daemon-restart")
def daemon_restart():
    """Force-kill and restart the Kairos supervisor (which manages the daemon)."""
    from kairos.daemon import force_stop_daemon, force_stop_supervisor
    import subprocess, sys, os, time

    click.echo("Stopping supervisor and daemon...")
    force_stop_supervisor()
    force_stop_daemon()
    time.sleep(1)

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "kairos_supervisor.py")
    click.echo(f"Starting supervisor: {pythonw} {script}")
    subprocess.Popen(
        [pythonw, script],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    time.sleep(2)
    click.echo("Supervisor started.")


# ── parse ─────────────────────────────────────────────────────────


@cli.command()
@click.option("--file", "file_path", default=None, help="Read input from a text file (skips editor)")
def parse(file_path: str | None):
    """Parse natural language input into structured session items.

    Opens the system text editor for multi-line input (respects $VISUAL,
    then $EDITOR, falls back to Notepad on Windows). Type your
    description, save, and close the editor to parse it.

    Use --file to read from a plain text file directly without opening an editor.
    Pipe input via stdin (e.g. `echo "..." | kairos parse`) for non-interactive use.
    """
    from kairos.nlp import parse_session_input
    from kairos.storage import session_exists

    if file_path:
        text = open(file_path, encoding="utf-8").read()
    elif not sys.stdin.isatty():
        lines = [l.rstrip("\r\n") for l in sys.stdin]
        text = "\n".join(lines)
    else:
        click.echo("Opening editor for multi-line input...")
        text = click.edit()
        if text is None:
            click.echo("No input provided.")
            return

    if not text or not text.strip():
        click.echo("No input provided.")
        return

    click.echo("\nParsing...")
    result = parse_session_input(text)

    # Show structured breakdown
    click.echo("\nParsed:")
    for item in result.items:
        prefix = "?" if item.confidence == "low" else "+"
        schedule_str = _format_schedule_for_preview(item)
        if item.kind == "app_launch":
            click.echo(f"  {prefix} {schedule_str:>20}  - {item.app or '?'} -> {item.target or '(default)'}")
        elif item.kind == "todo":
            click.echo(f"  {prefix} {schedule_str:>20}  - Reminder: {item.text}")
        elif item.kind == "boot_reminder":
            click.echo(f"  {prefix} {'On boot':>20}  - Reminder: {item.text}")
        else:
            click.echo(f"  {prefix} Unparsed: \"{item.raw}\" - please edit manually")

    unparsed = [i for i in result.items if i.kind == "unparsed"]
    need_recurrence = [i for i in result.items if i.needs_recurrence_confirmation]

    # Prompt for recurrence on items that need it
    for item in need_recurrence:
        click.echo()
        click.echo(f"  No repeat specified for: \"{item.raw}\"")
        choice = click.prompt(
            "  Repeat this? [Once / Daily / Choose days]",
            default="Once",
        )
        choice_lower = choice.strip().lower()
        if choice_lower in ("daily", "d"):
            item.days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        elif choice_lower in ("once", "o", ""):
            item.days = []
        elif choice_lower.startswith("choose") or choice_lower.startswith("c"):
            days_input = click.prompt(
                "  Enter weekdays (e.g. mon,wed,fri)",
                default="",
            )
            item.days = [d.strip().lower()[:3] for d in days_input.split(",") if d.strip()]
        else:
            # Try parsing as a comma-separated list of day abbreviations
            item.days = [d.strip().lower()[:3] for d in choice_lower.replace(" and ", ",").split(",") if d.strip()]

    if unparsed:
        click.echo(f"\nWarning: {len(unparsed)} line(s) could not be parsed.")

    # Save each item as its own session, auto-named from content
    click.echo()
    saved_count = 0
    used_names: set[str] = set()
    for item in result.items:
        if item.kind == "unparsed":
            continue

        session_name = _auto_session_name(item, used_names)
        used_names.add(session_name)
        _validate_name(session_name)

        app_type = item.app or "chrome" if item.kind == "app_launch" else None
        if app_type and app_type not in VALID_APP_TYPES:
            app_type = "chrome"

        session = create_empty_session(session_name)

        if item.kind == "app_launch":
            session.apps.append(AppItem(type=app_type, target=item.target))
        elif item.kind in ("todo", "boot_reminder"):
            session.todos.append(TodoItem(text=item.text or item.raw))

        if item.time or item.days is not None or item.on_boot or item.date:
            session.schedule = ScheduleConfig(
                time=item.time,
                date=item.date,
                days=item.days or [],
                on_boot=item.on_boot,
            )

        save_session(session)
        saved_count += 1

        schedule_hint = ""
        if item.time:
            schedule_hint = f" @ {item.time}"
        if item.on_boot:
            schedule_hint = " [boot]"
        click.echo(f"  + {session_name}{schedule_hint}")

    if saved_count:
        click.echo(f"\nSaved {saved_count} session(s). Daemon will launch each at its scheduled time.")
    else:
        click.echo("Nothing to save.")


# ── now ────────────────────────────────────────────────────────────


@cli.command(name="now")
def now():
    """Launch every session that is scheduled at the current time."""
    from datetime import datetime, date

    _weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    now = datetime.now()
    today_str = _weekday_map[date.today().weekday()]
    launched = 0

    for name in list_sessions():
        s = load_session(name)
        if s is None:
            continue
        if not s.schedule.time:
            continue
        if s.schedule.days and today_str not in s.schedule.days:
            continue
        if s.last_run and s.last_run.startswith(str(date.today())):
            continue
        if any(h.date == str(date.today()) and h.status == "skipped" for h in s.history):
            continue

        try:
            h, m = s.schedule.time.split(":")
            sched_dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        except (ValueError, AttributeError):
            continue

        if now >= sched_dt:
            click.echo(f"Launching '{s.name}' (scheduled at {s.schedule.time})...")
            if s.apps:
                launch_session(s.name, s.apps)
            s.last_run = now.isoformat(timespec="seconds")
            s.history.append(
                SessionLog(
                    date=str(date.today()),
                    status="launched",
                    launched_at=now.isoformat(timespec="seconds"),
                )
            )
            save_session(s)
            launched += 1

            try:
                pending = [t for t in s.todos if not t.completed_today]
                reminders = [(t.text, lambda w: None) for t in pending]
                show_widgets_cli(
                    launched_sessions=[s],
                    reminders=reminders,
                    timeout_per_widget_ms=8000,
                )
            except Exception as e:
                logger.warning("Widget display failed: %s", e)

    if launched == 0:
        click.echo("Nothing due right now.")


def _format_schedule_for_preview(item) -> str:
    """Build a human-readable schedule label for a parsed item."""
    from kairos.models import ParsedLine
    if item.on_boot:
        return "On boot"
    parts = []
    if item.time:
        parts.append(item.time)
    if item.days is not None and len(item.days) > 0:
        if set(item.days) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
            parts.append("daily")
        elif set(item.days) == {"mon", "tue", "wed", "thu", "fri"}:
            parts.append("weekdays")
        elif set(item.days) == {"sat", "sun"}:
            parts.append("weekends")
        else:
            short_days = [d.capitalize()[:3] for d in item.days]
            parts.append("/".join(short_days))
    elif item.days is not None and len(item.days) == 0:
        parts.append("once")
    elif item.time and item.days is None and not item.on_boot:
        parts.append("no repeat")
    if parts:
        return ", ".join(parts)
    return ""


# ── entry ─────────────────────────────────────────────────────────


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cli()


if __name__ == "__main__":
    main()
