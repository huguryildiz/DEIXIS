"""What a failed install job shows for an exception (B3): a fixed marker line, never the exception's class, message or paths.

The page words the marker in its own language. The exception itself goes to the log.
"""

import logging

log = logging.getLogger("deixis.jobs")

COULD_NOT_RUN = "[could_not_run]"


def failure_line(exc: BaseException, what: str) -> str:
    """The line a failed job carries for `exc`; `what` names the job in the log."""
    log.warning("%s failed: %s: %s", what, type(exc).__name__, exc, exc_info=exc)
    return COULD_NOT_RUN
