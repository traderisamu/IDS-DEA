"""
A small rotating-file logger, purely for troubleshooting after the fact.

Several places in this app intentionally swallow exceptions rather than
interrupt the user - a one-off network hiccup checking the reminder
schedule, or a transient failure resolving the config file, shouldn't
pop an error box in someone's face every minute. That's the right user
experience, but it also means a problem that's happening EVERY time
would otherwise be completely invisible. This gives anyone troubleshooting
later (an admin, or whoever built the app) a plain-text file to open by
hand - it's never surfaced in the UI itself.

Usage:
    from shared.applog import get_logger
    log = get_logger(__name__)
    try:
        ...
    except Exception:
        log.exception("brief note on what was being attempted")
"""
import logging
import logging.handlers
import os

from .pathutils import local_app_dir

_LOG_FILENAME = "app.log"
_configured = False


def _configure_once():
    global _configured
    if _configured:
        return
    _configured = True
    try:
        log_path = os.path.join(local_app_dir(), _LOG_FILENAME)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
        ))
        root = logging.getLogger("dea_app")
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except Exception:
        # Even the logger itself must never take the app down with it -
        # if the log file can't be created (e.g. a locked-down profile),
        # just fall back to a do-nothing logger silently.
        pass


def get_logger(name):
    _configure_once()
    return logging.getLogger(f"dea_app.{name}")
