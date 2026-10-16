"""Keys never reach a log line through a URL (E27).

Some sources take the key in the URL query (`api_key` for OpenAlex's rate-limit page, NCBI and SerpApi; `apikey` for IEEE
Xplore). httpx logs every request URL at INFO, and an HTTP error carries its URL in the message, so a logger set to INFO
or DEBUG would write the key. `install()` wraps the log record factory once at app start: every record, from any logger and
any handler (uvicorn's, httpx's, pytest's), is redacted when it is created, and so is the traceback text of an exception.
"""

from __future__ import annotations

import logging
import re

# A query parameter whose name says it is a secret. The value runs to the next separator, quote, space or fragment.
_QUERY_SECRET = re.compile(r"(?i)([?&;](?:api[_-]?key|apikey|access[_-]?token|token|key)=)[^&;\s\"'<>#]+")
REDACTED = "<redacted>"


def redact(text: str) -> str:
    """`text` with the value of every secret-named query parameter replaced; anything else is untouched."""
    return _QUERY_SECRET.sub(lambda m: m.group(1) + REDACTED, text) if "=" in text else text


def _redacting_factory(inner):
    def make(*args, **kwargs) -> logging.LogRecord:
        record = inner(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001  a bad format string stays the logging module's business
            return record
        if (clean := redact(message)) != message:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
            text = logging.Formatter().formatException(record.exc_info)
            if (clean := redact(text)) != text:
                record.exc_text = clean  # the Formatter prints this instead of formatting the exception again
        return record
    make.redacts_keys = True  # type: ignore[attr-defined]
    return make


def install() -> None:
    """Wrap the record factory, once; calling it again does nothing."""
    factory = logging.getLogRecordFactory()
    if not getattr(factory, "redacts_keys", False):
        logging.setLogRecordFactory(_redacting_factory(factory))
