from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from kairos.models import SessionLog


def get_stats(name: str, history: list[SessionLog]) -> dict[str, Any]:
    today = date.today()
    # Look at last 7 days
    tracked_days = 7
    dates = [(today - timedelta(days=i)).isoformat() for i in range(tracked_days)]

    launched = 0
    skipped = 0
    missed = 0
    run_days = 0
    total_todos = 0
    completed_todos = 0

    for d in dates:
        day_logs = [h for h in history if h.date == d]
        if not day_logs:
            continue
        run_days += 1
        for log in day_logs:
            if log.status == "launched":
                launched += 1
            elif log.status == "skipped":
                skipped += 1
            elif log.status == "missed":
                missed += 1

    avg_todos_completed = 0.0
    if run_days > 0:
        avg_todos_completed = completed_todos / run_days if total_todos > 0 else 0.0

    return {
        "name": name,
        "total_days": tracked_days,
        "run_days": run_days,
        "launched": launched,
        "skipped": skipped,
        "missed": missed,
        "avg_todos_completed": avg_todos_completed,
    }
