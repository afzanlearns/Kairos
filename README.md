# Kairos

**Kairos remembers your workspace so you can continue working instead of reconstructing it.**

Kairos is a personal workflow orchestrator for Windows. Define a "session" — a bundle of apps, browser tabs, terminal commands, and reminders — once, and Kairos launches it for you automatically, exactly when you need it. No more manually reopening the same fifteen things every morning. No more forgetting the thing you meant to do at 7pm. Kairos runs quietly in the background and taps you on the shoulder, right on time.

```
$ kairos parse
Open vscode at 9am
Remind me to check GitHub notifications every weekday at 9am
Bootup reminder regarding client email
```
That's it. Kairos parses it, confirms what it understood, and from then on it just happens — no scheduling app to check, no command to remember.

---

## Why

Every developer has the same fifteen-click morning ritual: open the IDE, open the right folder, start the dev server, open the right tabs, maybe open Spotify. Kairos exists to remove that ritual entirely — you define your workflow once, and Kairos owns making sure it shows up, on schedule, without you lifting a finger.

The design is deliberately simple and transparent:

- **Deterministic, not AI-guessing.** No LLM calls, no cloud dependency. Every decision — what fires, when, and what it does — is traceable to an explicit rule you can read in the code.
- **Daemon-driven, not user-driven.** A background process decides when to surface a reminder. You never type a command to "check now" — that would just make this a to-do list you have to remember to open.
- **Confirm before acting on parsed input.** Anything derived from natural language is shown to you for confirmation before anything is saved — Kairos never silently guesses.
- **Local-first.** Everything lives in local JSON files and SQLite. No accounts, no servers, nothing leaves your machine.

---

## Features

- **Sessions** — named, reusable bundles of apps (VS Code, Windows Terminal, Chrome tabs, Spotify), todos, and a note, each schedulable independently.
- **Natural language input** — `kairos parse` turns a plain-English, multi-line description into fully scheduled sessions, including recurrence ("every day," "every Mon/Wed/Fri," "weekdays") and specific future dates ("tomorrow at 3pm," "next friday," "2026-07-20").
- **A background daemon that's actually always on** — auto-starts at login, self-heals if it ever crashes (via a lightweight supervisor process), and catches up on anything scheduled while your laptop was off.
- **On-screen widgets, not just terminal output** — a heads-up 5 minutes before a session fires, a launch confirmation as apps open, and standalone reminder popups, all frameless, always-on-top, and styled dark/minimal.
- **Smart handling of collisions** — sessions due at the exact same time merge into a single widget instead of piling up; widgets stack cleanly and cap out with a "+N more" indicator rather than fading into illegibility.
- **Quiet hours** — no notifications during a window you define, so a missed-and-caught-up reminder doesn't wake you at 2am.
- **Analytics** — `kairos stats` tracks how often you actually run vs. skip a session over time.

---

## Installation

```bash
git clone https://github.com/afzanlearns/Kairos.git
cd Kairos
pip install -e .
```

Requires Python 3.11+ and Windows (the app-launch dispatch, daemon auto-start, and notification system are all Windows-specific in this version).

---

## Quick Start

**1. Describe your morning in plain English:**
```bash
kairos parse
```
Your default editor opens — type what you want, save, and close:
```
Open vscode at 9am
Open localhost:3000 at 9am
Remind me to check GitHub at 9am
```
Kairos shows you exactly what it understood and asks for confirmation before saving anything.

**2. Start the daemon so it actually runs on its own:**
```bash
python kairos_supervisor.py --register
```
This registers Kairos to start automatically at login and keeps it alive — if the daemon process ever dies for any reason, the supervisor relaunches it within seconds, no manual intervention required.

**3. That's it.** From here on, sessions fire on their own. Check in anytime with:
```bash
kairos today       # what's scheduled today
kairos next        # what's coming up next
kairos daemon-status   # confirm the daemon is alive and healthy
```

---

## CLI Reference

### Session management
| Command | Purpose |
|---|---|
| `kairos new <name>` | Create an empty session |
| `kairos add <name> --code/--terminal/--chrome/--spotify/--todo ...` | Add an item to a session |
| `kairos list` | List all sessions |
| `kairos show <name>` | Show a session's full contents |
| `kairos edit <name> --remove-app/--remove-todo <idx>` | Remove an item |
| `kairos note <name> "<text>"` | Attach a note |
| `kairos start <name>` | Launch a session right now, manually |
| `kairos done <name> "<todo>"` | Mark a todo complete |

### Scheduling
| Command | Purpose |
|---|---|
| `kairos schedule <name> --at HH:MM --days mon,wed,fri` | Set a recurring schedule |
| `kairos schedule <name> --on-boot` | Fire once, at daemon startup, regardless of time |
| `kairos schedule <name> --date YYYY-MM-DD` | One-time, date-specific schedule |
| `kairos skip <name>` | Skip today only, without touching future runs |
| `kairos today` / `kairos next` | See what's due |

### Natural language
| Command | Purpose |
|---|---|
| `kairos parse` | Describe sessions and reminders in plain English, with recurrence and dates inferred automatically |
| `kairos parse --file <path>` | Same, from a text file |

### Daemon
| Command | Purpose |
|---|---|
| `python kairos_supervisor.py --register` | Register the self-healing daemon to auto-start at login |
| `kairos daemon-status` | Check whether the daemon is alive and when it last checked in |
| `kairos daemon-restart` | Force-restart the daemon on demand |

### Analytics & config
| Command | Purpose |
|---|---|
| `kairos stats <name>` | Run/skip/completion history for a session |
| `kairos config --quiet HH:MM-HH:MM` | Set a quiet-hours window |

---

## How it works

```
kairos parse ──► rule-based NLP pipeline ──► session JSON (~/.kairos/sessions/)
                                                     │
                                                     ▼
                                    kairos_supervisor.py (auto-starts at login,
                                    restarts the daemon if it ever dies)
                                                     │
                                                     ▼
                                        kairos_daemon.py (60s poll loop)
                                          checks what's due, catches up on
                                          anything missed, dedupes, respects
                                          quiet hours and snoozes
                                                     │
                                                     ▼
                                     PyQt6 widget (heads-up / launched /
                                     reminder / merged-multi), always-on-top,
                                     dismissible, with a notification sound
```

The daemon and the widget layer run on separate threads — the daemon does I/O and scheduling math in the background, while Qt's event loop owns the main thread, so a widget being on screen never blocks the scheduler from doing its job.

---

## Project structure

```
kairos/
  kairos/
    cli.py          # all CLI commands
    models.py        # pydantic session/schedule/todo models
    storage.py        # atomic JSON read/write
    launcher.py        # app-launch dispatch table
    nlp.py             # rule-based natural language parser
    daemon.py           # scheduler, catch-up, quiet hours, dedup
    widget.py            # PyQt6 widgets and animations
    analytics.py           # run/skip/completion stats
  kairos_daemon.py     # daemon entry point
  kairos_supervisor.py  # self-healing supervisor (auto-restart on crash)
  tests/                  # unit + regression test suite
```

---

## Design philosophy

Kairos deliberately avoids anything resembling an AI assistant guessing at your intentions. The natural-language parser is a transparent, rule-based pipeline (time extraction, keyword classification, recurrence detection) — not a model — and it always shows you exactly what it parsed before saving anything. If you want to know why a session fired at a given time, the answer is always in a config file you can open and read, not a black box.

---

## Status

Actively developed as a personal daily-driver tool. Contributions, issues, and suggestions are welcome.

## License

MIT
