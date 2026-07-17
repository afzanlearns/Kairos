#!python
"""Kairos daemon entry point — run with pythonw.exe for background operation.

Usage:
    python kairos_daemon.py          # Run daemon
    python kairos_daemon.py --register  # Register for auto-start
    python kairos_daemon.py --unregister # Remove auto-start
"""
import sys
import logging
import logging.handlers
from pathlib import Path

from kairos.config import LOGS_DIR, ensure_dirs
from kairos.widget import WidgetManager, run_widget_app


def setup_logging():
    ensure_dirs()
    log_path = LOGS_DIR / "daemon.log"
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    args = [a.lower() for a in sys.argv[1:]]

    if "--register" in args:
        from kairos.daemon import register_autostart
        script_path = str(Path(__file__).resolve())
        register_autostart(f'"{sys.executable}" "{script_path}"')
        print("Daemon registered for auto-start.")
        return

    if "--unregister" in args:
        from kairos.daemon import unregister_autostart
        unregister_autostart()
        print("Daemon unregistered.")
        return

    logger.info("Starting Kairos daemon...")

    from kairos.daemon import Daemon
    daemon = Daemon()
    widget_mgr = WidgetManager()
    widget_mgr.start()
    daemon.set_widget_manager(widget_mgr)

    try:
        from threading import Thread
        daemon_thread = Thread(target=daemon.run, daemon=True)
        daemon_thread.start()
        run_widget_app(widget_mgr)
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()
