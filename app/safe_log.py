# File: app/safe_log.py
import traceback


def log_error(logger, msg, exc):
    """Log msg, the exception type and stack frames only; never the exception message,
    which can carry patient data (DB error details, file paths)."""
    logger.error("%s (%s)\n%s", msg, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
