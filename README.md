# Kairos

A personal workflow orchestrator for Windows. Define named "sessions" (e.g. `portfolio`, `java-study`, `wind-down`) -- each a set of apps, browser tabs, terminal commands, and reminders. Kairos runs as a silent background daemon that pops an on-screen widget to launch a session, remind you of a to-do, or catch up on anything missed since boot.

## Philosophy

- **Deterministic, not AI-guessing.** No LLM calls, no cloud dependency. Every decision is traceable to an explicit rule.
- **Daemon-driven, not user-driven.** A background process decides when to surface UI. You never type a command to "check now."
- **Confirm before acting on parsed input.** Anything derived from natural language is shown to you for confirmation before it's saved.
- **Local-first.** Everything lives in local JSON files and SQLite. No accounts, no servers.
- **Aesthetic consistency.** Dark background, flat 1px borders, monospace fonts, muted tones.

## Installation

```bash
pip install -e .
```

## CLI Command Reference

### Session Management

```
kairos new <name>                          Create a new empty session
kairos list                                List all defined sessions
kairos show <name>                         Pretty-print a session
kairos edit <name> --remove-app <idx>      Remove an app by index
kairos edit <name> --remove-todo <idx>     Remove a todo by index
kairos note <name> "<text>"                Set a session note
kairos start <name>                        Launch every app in the session
```

### Adding Items

```
kairos add <name> --code <path>
kairos add <name> --terminal --cwd <path> --run <command>
kairos add <name> --chrome <url> [--chrome <url> ...]
kairos add <name> --spotify [<playlist>]
kairos add <name> --todo "<text>"
kairos done <name> "<todo text>"           Mark a todo complete (fuzzy match)
```

### Scheduling

```
kairos schedule <name> --at HH:MM --days mon,tue,wed,...
kairos schedule <name> --on-boot
kairos today                               List today's sessions
kairos next                                Show the next upcoming session
kairos skip <name>                         Skip a session for today
```

### Natural Language Parsing

```
kairos parse                               Enter multi-line input interactively
kairos parse --file <path>                 Parse from a text file
```

Example input:
```
Open vscode at 7 pm
Set a reminder for meeting at 7:30 pm
Bootup reminder regarding GitHub check
play youtube : https://youtube.com/watch?v=xyz at 6pm reminder
```

### Analytics

```
kairos stats <name>                        Show run/skip/miss stats
kairos config --quiet HH:MM-HH:MM         Set quiet hours
```

## Daemon

Run the daemon in the background:

```bash
python kairos_daemon.py           # Start the daemon
python kairos_daemon.py --register   # Register for auto-start on login
python kairos_daemon.py --unregister # Remove auto-start
```

Use `pythonw.exe` (no console window) for background operation. The daemon:
- Enforces single-instance via a lock file
- Shows a tray icon (via pystray)
- Checks for due sessions every 60 seconds
- Triggers heads-up 5 minutes before a scheduled session
- Catches up on missed sessions on startup
- Displays PyQt6 on-screen widgets for heads-up, launch, and reminders

## Configuration

Configuration files are stored under `~/.kairos/`:

| File | Purpose |
|------|---------|
| `sessions/<name>.json` | Session definitions |
| `app_mapping.json` | Keyword-to-app mapping for NLP |
| `stopwords.txt` | Filler words stripped during NLP |
| `quiet_hours.json` | Quiet hours configuration |
| `kairos.db` | Session history/analytics |
| `logs/daemon.log` | Rotating daemon logs |

## Project Structure

```
kairos/
  kairos/
    __init__.py
    __main__.py
    cli.py              # CLI commands
    models.py           # Pydantic data models
    storage.py          # JSON read/write with atomic operations
    launcher.py         # App launch dispatch table
    config.py           # Paths, constants
    nlp.py              # Rule-based natural language parsing
    daemon.py           # Background scheduler and daemon logic
    widget.py           # PyQt6 on-screen widgets
    analytics.py        # Session history/stats
  kairos_daemon.py      # Daemon entry point
  tests/
    test_storage.py
    test_launcher.py
    test_daemon.py
    test_nlp.py
  pyproject.toml
  README.md
```

## App Types Supported

- `code` -- VS Code (`code` on PATH)
- `terminal` -- Windows Terminal (`wt` on PATH)
- `chrome` -- Google Chrome
- `spotify` -- Spotify

Extend by adding a handler function in `launcher.py` and adding it to the `DISPATCH` dict.

## Testing

```bash
pytest tests/
```
