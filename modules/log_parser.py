"""
modules/log_parser.py
=====================
Legacy multi-format log parser — fallback for files that do not follow the
strict ``YYYY-MM-DD HH:MM:SS LEVEL Message`` format.

Supported formats
-----------------
* Python logging  —  ``2024-01-15 10:23:45,123 - ERROR - message``
* Apache / Nginx  —  ``[Mon Jan 15 10:23:45 2024] [error] message``
* Simple prefix   —  ``ERROR: message``
* Plain text      —  keyword scan to infer level; stored as INFO fallback

This module writes ``LogEntry`` rows (the legacy table).  New uploads that
match the strict format are handled by ``modules/parser.py`` instead, which
writes ``ParsedLog`` rows.  ``parse_and_store()`` is called from
``modules/routes.py`` only when the strict parser finds zero matching lines.
"""

import re
import os

from extensions import db
from modules.models import LogFile, LogEntry

# ── Format patterns ───────────────────────────────────────────────────────────

_PATTERNS = {
    "python": re.compile(
        r"(?P<timestamp>\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}[,.]?\d*)"
        r"\s*[-–]\s*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
        r"\s*[-–]\s*(?P<message>.+)"
    ),
    "apache": re.compile(
        r"\[(?P<timestamp>[^\]]+)\]\s+\[(?P<level>debug|info|notice|warn|error|crit|alert|emerg)\]"
        r"\s+(?P<message>.+)",
        re.IGNORECASE,
    ),
    "simple": re.compile(
        r"^(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\s*[:\-]\s*(?P<message>.+)",
        re.IGNORECASE,
    ),
}

# Normalise raw level strings to the standard five
_LEVEL_MAP: dict[str, str] = {
    "warn":     "WARNING",
    "fatal":    "CRITICAL",
    "notice":   "INFO",
    "crit":     "CRITICAL",
    "alert":    "CRITICAL",
    "emerg":    "CRITICAL",
    "debug":    "DEBUG",
    "info":     "INFO",
    "error":    "ERROR",
    "critical": "CRITICAL",
    "warning":  "WARNING",
}


def _normalise_level(raw: str) -> str:
    """Return the canonical uppercase level name for *raw*."""
    return _LEVEL_MAP.get(raw.strip().lower(), "INFO")


def _parse_line(line: str) -> dict | None:
    """
    Try each known format against *line*.

    Returns a dict with keys ``level``, ``message``, and ``timestamp``
    (timestamp may be ``None``), or ``None`` for blank lines.
    """
    line = line.strip()
    if not line:
        return None

    for _name, pattern in _PATTERNS.items():
        match = pattern.match(line)
        if match:
            groups = match.groupdict()
            return {
                "level":     _normalise_level(groups.get("level", "INFO")),
                "message":   groups.get("message", line).strip(),
                "timestamp": groups.get("timestamp"),
            }

    # Keyword fallback — scan the line for a recognisable level word
    upper = line.upper()
    level = "INFO"
    for keyword in ("CRITICAL", "ERROR", "WARNING", "DEBUG"):
        if keyword in upper:
            level = keyword
            break

    return {"level": level, "message": line, "timestamp": None}


def parse_and_store(log_file: LogFile, filepath: str) -> dict:
    """
    Parse *filepath* using multi-format heuristics and persist every line as a
    ``LogEntry`` row linked to *log_file*.

    Returns a ``{level: count}`` dict covering all five standard levels.

    Notes
    -----
    * File is read as UTF-8, replacing undecodable bytes with ``?``.
    * Messages are capped at 1 000 characters before insertion.
    * All rows are bulk-saved in one ``bulk_save_objects`` call for efficiency.
    * On any exception the session is rolled back and the file is marked as
      ``"error"``; the exception is then re-raised for the caller to handle.
    """
    counts: dict[str, int] = {k: 0 for k in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")}
    entries: list[LogEntry] = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line_number, raw_line in enumerate(fh, start=1):
                parsed = _parse_line(raw_line)
                if parsed is None:
                    continue
                level = parsed["level"]
                counts[level] = counts.get(level, 0) + 1
                entries.append(LogEntry(
                    log_file_id=log_file.id,
                    line_number=line_number,
                    level=level,
                    message=parsed["message"][:1_000],
                    timestamp=parsed.get("timestamp"),
                ))

        db.session.bulk_save_objects(entries)
        log_file.status = "analyzed"
        db.session.commit()

    except Exception:
        db.session.rollback()
        log_file.status = "error"
        db.session.commit()
        raise

    return counts
