"""
modules/parser.py
=================
Dedicated parser for the canonical log format:

    YYYY-MM-DD HH:MM:SS LEVEL Message

Example lines:
    2026-04-13 10:01:12 INFO  Server started
    2026-04-13 10:03:10 WARNING High memory usage
    2026-04-13 10:04:22 ERROR Database connection failed

Design goals
------------
- Strict format only: any line that doesn't match is recorded in
  ParseResult.skipped_lines so callers can report partial success.
- Zero side-effects: this module never touches the database directly.
  Persistence is handled by store_parsed_result() which the caller
  invokes after deciding the result is acceptable.
- Python 3.10 compatible throughout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

# ── Constants ──────────────────────────────────────────────────────────────────

# Canonical set of supported log levels (ascending severity)
VALID_LEVELS: tuple = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Map each level to a human-readable severity bucket stored in the DB
SEVERITY_MAP: dict = {
    "DEBUG":    "low",
    "INFO":     "low",
    "WARNING":  "medium",
    "ERROR":    "high",
    "CRITICAL": "critical",
}

# File extensions accepted by this parser
ALLOWED_EXTENSIONS: frozenset = frozenset({"log", "txt"})

# Hard cap on stored message length (prevents DB bloat)
MAX_MESSAGE_LEN: int = 2_000

# Maximum file size accepted (16 MB)
MAX_FILE_BYTES: int = 16 * 1024 * 1024

# Compiled regex — strict format: YYYY-MM-DD HH:MM:SS LEVEL message
_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})"  # date + time
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"          # level keyword
    r"\s+(?P<message>.+)$",                                     # rest of line
    re.IGNORECASE,
)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ParsedLine:
    """A single successfully parsed log line."""
    line_number: int       # 1-based position in the file
    timestamp:   datetime  # parsed event datetime
    level:       str       # normalised uppercase level
    message:     str       # log body, capped at MAX_MESSAGE_LEN
    severity:    str       # low / medium / high / critical
    raw:         str       # original text for audit / debugging


@dataclass
class ParseResult:
    """
    Aggregate result returned by parse_file().

    Fields
    ------
    source_file   : original filename (display label — not a path)
    parsed        : lines that matched the strict format
    skipped_lines : (line_number, raw_text) for non-blank, unmatched lines
    errors        : file-level read errors — if non-empty, don't store anything
    """
    source_file:   str
    parsed:        list = field(default_factory=list)   # list[ParsedLine]
    skipped_lines: list = field(default_factory=list)   # list[tuple[int, str]]
    errors:        list = field(default_factory=list)   # list[str]

    @property
    def total_lines(self) -> int:
        """Total non-blank lines seen."""
        return len(self.parsed) + len(self.skipped_lines)

    @property
    def has_errors(self) -> bool:
        """True when a file-level error prevented reading."""
        return bool(self.errors)

    @property
    def counts(self) -> dict:
        """Per-level counts across all successfully parsed entries."""
        result = {lvl: 0 for lvl in VALID_LEVELS}
        for entry in self.parsed:
            result[entry.level] = result.get(entry.level, 0) + 1
        return result

    @property
    def success_rate(self) -> float:
        """Percentage of non-blank lines that matched the strict format."""
        if self.total_lines == 0:
            return 0.0
        return round(len(self.parsed) / self.total_lines * 100, 1)


# ── Validation ─────────────────────────────────────────────────────────────────

class FileValidationError(ValueError):
    """
    Raised when an uploaded file cannot be accepted before parsing.
    Always carries a message suitable for direct display in the UI.
    """


def validate_upload(filename: str, file_size: int) -> None:
    """
    Validate a file before opening it.

    Checks (in order):
      1. Filename is non-empty.
      2. Extension is .log or .txt.
      3. File is not zero bytes.
      4. File does not exceed 16 MB.

    Raises FileValidationError with a descriptive message on any failure.
    """
    if not filename:
        raise FileValidationError("No filename provided.")

    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed_str = ", ".join(f".{e}" for e in sorted(ALLOWED_EXTENSIONS))
        raise FileValidationError(
            f"Unsupported file type '.{ext}'. Accepted types: {allowed_str}."
        )

    if file_size == 0:
        raise FileValidationError("The uploaded file is empty (0 bytes).")

    if file_size > MAX_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise FileValidationError(
            f"File is too large ({size_mb:.1f} MB). Maximum allowed size is 16 MB."
        )


# ── Core parsing ───────────────────────────────────────────────────────────────

def _parse_single_line(raw: str, line_number: int) -> Optional[ParsedLine]:
    """
    Try to parse one raw text line.

    Returns a ParsedLine on success, or None if the line is blank or
    does not match the strict YYYY-MM-DD HH:MM:SS LEVEL Message format.
    """
    stripped = raw.strip()
    if not stripped:
        return None

    match = _LINE_RE.match(stripped)
    if not match:
        return None

    level = match.group("level").upper()
    if level not in VALID_LEVELS:
        return None  # belt-and-braces; regex already enforces this

    try:
        ts = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None  # malformed date component

    message = match.group("message").strip()[:MAX_MESSAGE_LEN]

    return ParsedLine(
        line_number=line_number,
        timestamp=ts,
        level=level,
        message=message,
        severity=SEVERITY_MAP[level],
        raw=stripped,
    )


def _iter_file_lines(filepath: str) -> Iterator[tuple]:
    """
    Yield (1-based line_number, raw_line) for every line in the file.
    Uses UTF-8 with errors='replace' so corrupt bytes never crash parsing.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line_number, raw in enumerate(fh, start=1):
            yield line_number, raw


def parse_file(filepath: str, source_filename: str) -> ParseResult:
    """
    Parse an entire log file and return a structured ParseResult.

    Processing rules
    ----------------
    - Blank / whitespace-only lines  →  silently ignored.
    - Lines matching the strict format  →  appended to ParseResult.parsed.
    - Non-blank lines that don't match  →  recorded in skipped_lines
      (first 200 chars stored to bound memory usage).
    - If the file cannot be opened  →  one entry in ParseResult.errors;
      parsed will be empty.

    Parameters
    ----------
    filepath        : Absolute path to the file in uploads/.
    source_filename : Original user-facing filename (for display + DB).

    Returns
    -------
    ParseResult — always returned, even on read failure (check .has_errors).
    """
    result = ParseResult(source_file=source_filename)

    try:
        for line_number, raw in _iter_file_lines(filepath):
            stripped = raw.strip()
            if not stripped:
                continue  # blank line — ignore silently

            parsed_line = _parse_single_line(raw, line_number)
            if parsed_line is not None:
                result.parsed.append(parsed_line)
            else:
                result.skipped_lines.append((line_number, stripped[:200]))

    except OSError as exc:
        result.errors.append(f"Could not read file: {exc}")

    return result


# ── Database persistence ───────────────────────────────────────────────────────

def store_parsed_result(
    parse_result: ParseResult,
    log_file_id:  int,
    source_file:  str,
) -> int:
    """
    Bulk-insert all ParsedLine records into the parsed_logs table.

    Intentionally separate from parse_file() so callers can inspect the
    result before committing anything to the database.

    Parameters
    ----------
    parse_result : Returned by parse_file().
    log_file_id  : Primary key of the parent LogFile row.
    source_file  : Original filename stored on each ParsedLog row.

    Returns
    -------
    int — number of rows inserted.

    Notes
    -----
    The caller is responsible for db.session.commit() (or rollback).
    """
    from extensions import db
    from modules.models import ParsedLog

    if not parse_result.parsed:
        return 0

    rows = [
        ParsedLog(
            log_file_id=log_file_id,
            timestamp=entry.timestamp,
            level=entry.level,
            message=entry.message,
            source_file=source_file,
            severity=entry.severity,
        )
        for entry in parse_result.parsed
    ]

    db.session.bulk_save_objects(rows)
    db.session.flush()  # make rows visible within the current transaction
    return len(rows)
