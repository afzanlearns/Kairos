from __future__ import annotations

import subprocess
import shutil
import logging
from typing import Any

from kairos.models import AppItem

logger = logging.getLogger(__name__)


def launch_code(item: AppItem) -> bool:
    exe = _resolve_exe("code", "Visual Studio Code")
    if not exe:
        return False
    args = [exe]
    if item.path:
        args.append(item.path)
    return _run(args)


def launch_terminal(item: AppItem) -> bool:
    exe = _resolve_exe("wt", "Windows Terminal")
    if not exe:
        return False
    args = [exe]
    if item.cwd:
        args.extend(["-d", item.cwd])
    if item.run:
        args.extend(["cmd", "/k", item.run])
    return _run(args)


def launch_chrome(item: AppItem) -> bool:
    exe = _resolve_exe("chrome", "Google Chrome")
    if not exe:
        return False
    urls = item.urls
    target = item.target
    args = [exe]
    if target:
        args.append(target)
    args.extend(urls)
    return _run(args)


def launch_spotify(item: AppItem) -> bool:
    exe = _resolve_exe("spotify", "Spotify")
    if not exe:
        return False
    return _run([exe])


def _resolve_exe(name: str, display_name: str) -> str | None:
    exe_path = shutil.which(name)
    if exe_path:
        return exe_path
    logger.warning("%s executable '%s' not found on PATH", display_name, name)
    print(f"  [WARN] {display_name} ('{name}') not found on PATH — skipping.")
    return None


def _run(args: list[str]) -> bool:
    try:
        subprocess.Popen(args, shell=False)
        return True
    except FileNotFoundError as e:
        logger.error("Failed to launch %s: %s", args[0], e)
        print(f"  [ERROR] Could not launch '{args[0]}': {e}")
        return False
    except OSError as e:
        logger.error("OS error launching %s: %s", args[0], e)
        print(f"  [ERROR] OS error launching '{args[0]}': {e}")
        return False


DISPATCH: dict[str, Any] = {
    "code": launch_code,
    "terminal": launch_terminal,
    "chrome": launch_chrome,
    "spotify": launch_spotify,
}


def launch_app(item: AppItem) -> bool:
    handler = DISPATCH.get(item.type)
    if handler is None:
        logger.warning("Unknown app type: %s", item.type)
        print(f"  [WARN] Unknown app type '{item.type}' — skipping.")
        return False
    return handler(item)


def launch_session(session_name: str, apps: list[AppItem]) -> int:
    logger.info("Launching session '%s' with %d app(s)", session_name, len(apps))
    success_count = 0
    for i, item in enumerate(apps, 1):
        print(f"  [{i}/{len(apps)}] Launching {item.type}...", end="")
        if launch_app(item):
            success_count += 1
            print(" OK")
        else:
            print(" FAILED")
    logger.info(
        "Session '%s': %d/%d apps launched successfully",
        session_name, success_count, len(apps),
    )
    return success_count
