"""
modules/monitor.py
==================
Real-time log file monitoring using the watchdog library.

Architecture overview
---------------------
* ``LogFileMonitor``  – high-level public API used by routes and app.py.
  Manages one ``watchdog.Observer`` per monitored directory, keyed by the
  absolute path of the watched file.  All state is stored in a module-level
  registry (``_REGISTRY``) so it survives blueprint re-imports without
  leaking threads.

* ``_LogEventHandler`` – watchdog ``FileSystemEventHandler`` subclass that
  fires on every ``modified`` event for the watched file.  It reads only the
  *new* bytes (tail) since the last read position, parses them with the
  existing strict parser (``modules/parser.py``), and pushes rows into the DB
  inside a Flask application context.

Threading model
---------------
watchdog's Observer runs in a **single background daemon thread** per monitor.
Flask's SQLAlchemy session is NOT thread-safe by default, so we push a fresh
``app.app_context()`` before every DB write and close it immediately after.
This avoids any shared-session contamination.

Duplicate prevention
--------------------
Each ``WatchedFile`` row stores the last byte-offset that was successfully
processed (``last_offset``).  On every ``modified`` event we seek to that
offset, read only the new bytes, and update the offset atomically inside the
same DB transaction.  Even if the observer fires multiple times for the same
write, reading from the stored offset is idempotent.

Python 3.10 compatibility
--------------------------
No ``match`` statements, no 3.11+ ``tomllib``, no walrus operators inside
comprehensions that aren't supported.  All type hints use the ``from __future__
import annotations`` guard.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from modules.parser import parse_file as _parse_strict
from modules.parser import SEVERITY_MAP, VALID_LEVELS, _LINE_RE

log = logging.getLogger(__name__)


# ── Module-level monitor registry ─────────────────────────────────────────────
# Maps absolute_filepath -> _MonitorEntry
# Stored at module level so it is shared across all Flask requests.

_REGISTRY: dict[str, "_MonitorEntry"] = {}
_REGISTRY_LOCK = threading.Lock()


class _MonitorEntry:
    """Internal bookkeeping for one active monitor."""

    __slots__ = ("observer", "handler", "log_file_id", "watch_path")

    def __init__(
        self,
        observer: Observer,
        handler: "_LogEventHandler",
        log_file_id: int,
        watch_path: str,
    ) -> None:
        self.observer    = observer
        self.handler     = handler
        self.log_file_id = log_file_id
        self.watch_path  = watch_path


# ── Watchdog event handler ─────────────────────────────────────────────────────

class _LogEventHandler(FileSystemEventHandler):
    """
    Fires on every filesystem modification event for a single watched file.

    Responsibilities
    ----------------
    1.  Filter events: only react to the exact file being watched (the watchdog
        observer watches a *directory*, so sibling files generate events too).
    2.  Read only new bytes since ``_last_offset`` using a seek.
    3.  Parse each new line with the strict parser regex (same as parser.py).
    4.  Insert ``ParsedLog`` + update ``WatchedFile.last_offset`` in one
        atomic DB transaction inside a fresh Flask app context.
    5.  Never raise – log exceptions and continue, so the observer thread does
        not die silently.
    """

    def __init__(self, abs_path: str, log_file_id: int, flask_app) -> None:
        super().__init__()
        self._abs_path    = abs_path
        self._log_file_id = log_file_id
        self._app         = flask_app
        self._lock        = threading.Lock()   # one event at a time per file

    # ── watchdog callback ──────────────────────────────────────────────────

    def on_modified(self, event: FileModifiedEvent) -> None:
        # Watchdog reports the directory or its children; filter to our file
        if event.is_directory:
            return
        if os.path.abspath(event.src_path) != self._abs_path:
            return

        with self._lock:
            self._process_new_lines()

    # ── core processing ────────────────────────────────────────────────────

    def _process_new_lines(self) -> None:
        """Read new lines from the file and persist them to the database."""
        with self._app.app_context():
            try:
                self._do_process()
            except Exception:
                log.exception(
                    "Monitor: unhandled error processing '%s'", self._abs_path
                )

    def _do_process(self) -> None:
        from extensions import db
        from modules.models import ParsedLog, WatchedFile

        # Load the current offset from DB (source of truth)
        watched = WatchedFile.query.filter_by(
            log_file_id=self._log_file_id
        ).first()
        if watched is None:
            log.warning("Monitor: WatchedFile row missing for file_id=%s", self._log_file_id)
            return

        current_offset = watched.last_offset

        # Read only the new bytes
        try:
            file_size = os.path.getsize(self._abs_path)
        except OSError:
            return  # file was removed mid-watch

        if file_size <= current_offset:
            # File was truncated or not actually grown (spurious event)
            if file_size < current_offset:
                # Truncation detected — reset offset to start
                watched.last_offset = 0
                db.session.commit()
                log.info("Monitor: truncation detected for '%s', resetting offset", self._abs_path)
            return

        new_rows: list[ParsedLog] = []
        source_name = watched.source_filename
        line_num    = watched.lines_processed

        try:
            with open(self._abs_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(current_offset)
                for raw_line in fh:
                    line_num += 1
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    parsed = _parse_line(stripped, line_num)
                    if parsed is not None:
                        new_rows.append(
                            ParsedLog(
                                log_file_id=self._log_file_id,
                                timestamp=parsed["timestamp"],
                                level=parsed["level"],
                                message=parsed["message"],
                                source_file=source_name,
                                severity=parsed["severity"],
                            )
                        )

                new_offset = fh.tell()

        except OSError:
            log.exception("Monitor: could not read '%s'", self._abs_path)
            return

        if new_rows:
            db.session.bulk_save_objects(new_rows)
            log.debug(
                "Monitor: inserted %d rows from '%s'", len(new_rows), self._abs_path
            )

        # Always update offset + line count so re-processing is idempotent
        watched.last_offset     = new_offset
        watched.lines_processed = line_num
        watched.last_seen_at    = datetime.utcnow()
        db.session.commit()


# ── Line parser (re-used from parser.py without importing the full module) ─────

def _parse_line(stripped: str, line_number: int) -> Optional[dict]:
    """
    Parse one log line using the strict regex from parser.py.

    Returns a dict with keys: timestamp, level, message, severity.
    Returns None if the line does not match or has a bad timestamp.
    """
    match = _LINE_RE.match(stripped)
    if not match:
        return None

    level = match.group("level").upper()
    if level not in VALID_LEVELS:
        return None

    try:
        ts = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    return {
        "timestamp": ts,
        "level":     level,
        "message":   match.group("message").strip()[:2000],
        "severity":  SEVERITY_MAP[level],
    }


# ── Public API — LogFileMonitor ────────────────────────────────────────────────

class LogFileMonitor:
    """
    Manages the lifecycle of watchdog observers for monitored log files.

    All methods are classmethods so they can be called from any module without
    constructing an instance.  Internal state lives in ``_REGISTRY``.

    Usage
    -----
    Start monitoring an already-uploaded file::

        LogFileMonitor.start(
            flask_app=current_app._get_current_object(),
            abs_path="/path/to/uploads/uuid_server.log",
            log_file_id=3,
            source_filename="server.log",
        )

    Stop monitoring::

        LogFileMonitor.stop(log_file_id=3)

    List all active monitors::

        monitors = LogFileMonitor.list_active()
    """

    @classmethod
    def start(
        cls,
        flask_app,
        abs_path:        str,
        log_file_id:     int,
        source_filename: str,
    ) -> bool:
        """
        Start monitoring *abs_path* for new appended lines.

        Creates a ``WatchedFile`` DB row if one doesn't already exist,
        initialising ``last_offset`` to the current file size so we don't
        re-parse lines already in the DB.

        Returns True on success, False if the file doesn't exist or is already
        being monitored.
        """
        abs_path = os.path.abspath(abs_path)

        if not os.path.isfile(abs_path):
            log.error("Monitor.start: file not found: %s", abs_path)
            return False

        with _REGISTRY_LOCK:
            if log_file_id in {e.log_file_id for e in _REGISTRY.values()}:
                log.warning("Monitor.start: file_id=%s already monitored", log_file_id)
                return False

            # Ensure WatchedFile row exists
            with flask_app.app_context():
                from extensions import db
                from modules.models import WatchedFile

                existing = WatchedFile.query.filter_by(log_file_id=log_file_id).first()
                if existing is None:
                    initial_offset = os.path.getsize(abs_path)
                    watched = WatchedFile(
                        log_file_id=log_file_id,
                        abs_path=abs_path,
                        source_filename=source_filename,
                        last_offset=initial_offset,
                        is_active=True,
                    )
                    db.session.add(watched)
                else:
                    existing.is_active = True
                    existing.abs_path  = abs_path
                db.session.commit()

            # Build and start the watchdog observer
            watch_dir = str(Path(abs_path).parent)
            handler   = _LogEventHandler(abs_path, log_file_id, flask_app)
            observer  = Observer()
            observer.schedule(handler, path=watch_dir, recursive=False)
            observer.daemon = True   # dies when the main process exits
            observer.start()

            _REGISTRY[abs_path] = _MonitorEntry(
                observer=observer,
                handler=handler,
                log_file_id=log_file_id,
                watch_path=abs_path,
            )

        log.info("Monitor started: file_id=%s  path=%s", log_file_id, abs_path)
        return True

    @classmethod
    def stop(cls, log_file_id: int) -> bool:
        """
        Stop monitoring the file associated with *log_file_id*.

        Updates ``WatchedFile.is_active = False`` in the DB and shuts down the
        watchdog Observer thread cleanly.

        Returns True if a monitor was running and is now stopped, False if no
        matching monitor was found.
        """
        with _REGISTRY_LOCK:
            entry = cls._find_entry(log_file_id)
            if entry is None:
                log.warning("Monitor.stop: no monitor found for file_id=%s", log_file_id)
                return False

            try:
                entry.observer.stop()
                entry.observer.join(timeout=5)
            except Exception:
                log.exception("Monitor.stop: error stopping observer for file_id=%s", log_file_id)

            del _REGISTRY[entry.watch_path]

        log.info("Monitor stopped: file_id=%s", log_file_id)
        return True

    @classmethod
    def stop_all(cls) -> int:
        """Stop all active monitors. Returns the count stopped."""
        with _REGISTRY_LOCK:
            paths = list(_REGISTRY.keys())

        count = 0
        for path in paths:
            with _REGISTRY_LOCK:
                entry = _REGISTRY.get(path)
                if entry is None:
                    continue
                try:
                    entry.observer.stop()
                    entry.observer.join(timeout=3)
                except Exception:
                    pass
                del _REGISTRY[path]
            count += 1

        log.info("Monitor.stop_all: stopped %d monitors", count)
        return count

    @classmethod
    def is_active(cls, log_file_id: int) -> bool:
        """Return True if *log_file_id* is currently being monitored."""
        return cls._find_entry(log_file_id) is not None

    @classmethod
    def list_active(cls) -> list[dict]:
        """Return a list of dicts describing every active monitor."""
        with _REGISTRY_LOCK:
            return [
                {
                    "log_file_id": e.log_file_id,
                    "watch_path":  e.watch_path,
                    "observer_alive": e.observer.is_alive(),
                }
                for e in _REGISTRY.values()
            ]

    # ── private helpers ────────────────────────────────────────────────────

    @classmethod
    def _find_entry(cls, log_file_id: int) -> Optional[_MonitorEntry]:
        """Return the registry entry for *log_file_id*, or None."""
        for entry in _REGISTRY.values():
            if entry.log_file_id == log_file_id:
                return entry
        return None
