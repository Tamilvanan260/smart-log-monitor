"""
modules/models.py
=================
SQLAlchemy database models for the Smart Log Monitoring & Alert System.

Models
------
User        — authentication accounts with role-based access control
LogFile     — metadata record for every uploaded file
LogEntry    — legacy multi-format parsed entries (backward compatibility)
ParsedLog   — strict-format entries (YYYY-MM-DD HH:MM:SS LEVEL Message)
WatchedFile — real-time monitor state per watched log file
SystemAlert — pattern-matched alert records
Alert       — legacy alert model (kept for backward compatibility)
"""

from __future__ import annotations

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


# ── User ───────────────────────────────────────────────────────────────────────

class User(db.Model):
    """
    Authentication account.

    Roles
    -----
    admin   — full access: dashboard, monitor, upload, alerts, export, manage users
    viewer  — read-only: logs list, alerts view, parsed results

    Password storage
    ----------------
    Plaintext passwords are never stored.  ``set_password()`` calls
    werkzeug's ``generate_password_hash()`` (scrypt by default, argon2 or
    pbkdf2 on older builds) and stores only the resulting hash.
    ``check_password()`` compares via constant-time ``check_password_hash()``.
    """

    __tablename__ = "users"

    id            = db.Column(db.Integer,     primary_key=True)
    username      = db.Column(db.String(80),  nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20),  nullable=False, default="viewer")
    is_active     = db.Column(db.Boolean,     nullable=False, default=True)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime,    nullable=True)

    # ── Password helpers ───────────────────────────────────────────────────

    def set_password(self, plaintext: str) -> None:
        """Hash *plaintext* and store the result."""
        self.password_hash = generate_password_hash(plaintext)

    def check_password(self, plaintext: str) -> bool:
        """Return True if *plaintext* matches the stored hash."""
        return check_password_hash(self.password_hash, plaintext)

    # ── Role helpers ───────────────────────────────────────────────────────

    @property
    def is_admin(self) -> bool:
        """True when this account has admin role."""
        return self.role == "admin"

    # ── Repr / serialisation ───────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<User {self.username!r} role={self.role}>"

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "username":      self.username,
            "role":          self.role,
            "is_active":     self.is_active,
            "created_at":    self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "last_login_at": (
                self.last_login_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.last_login_at else None
            ),
        }



# ── LogFile ────────────────────────────────────────────────────────────────────

class LogFile(db.Model):
    """Metadata for a single uploaded log file."""

    __tablename__ = "log_files"

    id            = db.Column(db.Integer,     primary_key=True)
    filename      = db.Column(db.String(255), nullable=False)           # UUID-prefixed disk name
    original_name = db.Column(db.String(255), nullable=False)           # original filename
    file_size     = db.Column(db.Integer,     nullable=False)           # bytes
    uploaded_at   = db.Column(db.DateTime,    default=datetime.utcnow)
    status        = db.Column(db.String(50),  default="pending")        # pending|analyzed|error

    # Relationships — cascade deletes keep child rows in sync
    entries     = db.relationship("LogEntry",  backref="log_file", lazy=True, cascade="all, delete-orphan")
    parsed_logs = db.relationship("ParsedLog", backref="log_file", lazy=True, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<LogFile {self.original_name!r}>"

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "filename":      self.filename,
            "original_name": self.original_name,
            "file_size":     self.file_size,
            "uploaded_at":   self.uploaded_at.strftime("%Y-%m-%d %H:%M:%S"),
            "status":        self.status,
            "entry_count":   len(self.entries),
            "parsed_count":  len(self.parsed_logs),
        }


# ── LogEntry (legacy) ──────────────────────────────────────────────────────────

class LogEntry(db.Model):
    """
    Single line produced by the legacy multi-format parser (log_parser.py).
    Kept for backward compatibility with files that don't use the strict format.
    """

    __tablename__ = "log_entries"

    id          = db.Column(db.Integer,     primary_key=True)
    log_file_id = db.Column(db.Integer,     db.ForeignKey("log_files.id"), nullable=False)
    line_number = db.Column(db.Integer,     nullable=False)
    level       = db.Column(db.String(20),  nullable=False, default="INFO")
    message     = db.Column(db.Text,        nullable=False)
    timestamp   = db.Column(db.String(100), nullable=True)
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<LogEntry [{self.level}] line {self.line_number}>"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "line_number": self.line_number,
            "level":       self.level,
            "message":     self.message,
            "timestamp":   self.timestamp,
            "created_at":  self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


# ── ParsedLog ──────────────────────────────────────────────────────────────────

class ParsedLog(db.Model):
    """
    Single log record produced by modules/parser.py (strict format only).

    Strict input format:
        YYYY-MM-DD HH:MM:SS LEVEL Message
    Example:
        2026-04-13 10:04:22 ERROR Database connection failed

    Fields
    ------
    id          — auto-increment primary key
    log_file_id — FK to LogFile (nullable for standalone imports)
    timestamp   — datetime of the log event (indexed)
    level       — DEBUG | INFO | WARNING | ERROR | CRITICAL (indexed)
    message     — log body, max 2 000 chars
    source_file — original filename for fast querying without a JOIN (indexed)
    severity    — low | medium | high | critical
    created_at  — row insertion time (UTC)
    """

    __tablename__ = "parsed_logs"

    id          = db.Column(db.Integer,     primary_key=True)
    log_file_id = db.Column(db.Integer,     db.ForeignKey("log_files.id"), nullable=True)
    timestamp   = db.Column(db.DateTime,    nullable=False, index=True)
    level       = db.Column(db.String(20),  nullable=False, index=True)
    message     = db.Column(db.Text,        nullable=False)
    source_file = db.Column(db.String(255), nullable=False, index=True)
    severity    = db.Column(db.String(20),  nullable=False)
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ParsedLog [{self.level}] {self.timestamp}>"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "log_file_id": self.log_file_id,
            "timestamp":   self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "level":       self.level,
            "message":     self.message,
            "source_file": self.source_file,
            "severity":    self.severity,
            "created_at":  self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ── Class-level query helpers ──────────────────────────────────────────

    @classmethod
    def level_counts_for_file(cls, log_file_id: int) -> dict:
        """Return {level: count} for all entries belonging to a file."""
        from sqlalchemy import func
        rows = (
            db.session.query(cls.level, func.count(cls.id))
            .filter(cls.log_file_id == log_file_id)
            .group_by(cls.level)
            .all()
        )
        base = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}
        for level, count in rows:
            base[level] = count
        return base

    @classmethod
    def severity_counts_for_file(cls, log_file_id: int) -> dict:
        """Return {severity: count} for all entries belonging to a file."""
        from sqlalchemy import func
        rows = (
            db.session.query(cls.severity, func.count(cls.id))
            .filter(cls.log_file_id == log_file_id)
            .group_by(cls.severity)
            .all()
        )
        return dict(rows)


# ── WatchedFile ───────────────────────────────────────────────────────────────

class WatchedFile(db.Model):
    """
    Tracks a log file that is actively watched by the real-time monitor.

    Key fields
    ----------
    log_file_id     — FK to LogFile; one WatchedFile per LogFile.
    abs_path        — absolute path on disk used by the watchdog handler.
    source_filename — original filename shown in the UI.
    last_offset     — byte position up to which lines have been processed.
                      Initialised to the file size at watch-start so existing
                      content is not re-parsed.  Updated atomically after each
                      successful batch insert.
    lines_processed — running count of non-blank lines seen (informational).
    is_active       — False once the user stops the monitor.
    last_seen_at    — wall-clock time of the most recent modification event.
    started_at      — when monitoring began.
    """

    __tablename__ = "watched_files"

    id              = db.Column(db.Integer,     primary_key=True)
    log_file_id     = db.Column(db.Integer,     db.ForeignKey("log_files.id"),
                                nullable=False, unique=True, index=True)
    abs_path        = db.Column(db.String(512), nullable=False)
    source_filename = db.Column(db.String(255), nullable=False)
    last_offset     = db.Column(db.Integer,     nullable=False, default=0)
    lines_processed = db.Column(db.Integer,     nullable=False, default=0)
    is_active       = db.Column(db.Boolean,     nullable=False, default=False)
    last_seen_at    = db.Column(db.DateTime,    nullable=True)
    started_at      = db.Column(db.DateTime,    default=datetime.utcnow)

    # Convenience back-reference to the parent LogFile
    log_file = db.relationship(
        "LogFile",
        backref=db.backref("watched_file", uselist=False, lazy=True),
    )

    def __repr__(self) -> str:
        status = "active" if self.is_active else "stopped"
        return f"<WatchedFile [{status}] {self.source_filename!r}>"

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "log_file_id":      self.log_file_id,
            "source_filename":  self.source_filename,
            "last_offset":      self.last_offset,
            "lines_processed":  self.lines_processed,
            "is_active":        self.is_active,
            "last_seen_at":     (
                self.last_seen_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.last_seen_at else None
            ),
            "started_at":       self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "observer_alive":   False,   # filled in by routes that know monitor state
        }


# ── SystemAlert ────────────────────────────────────────────────────────────────

class SystemAlert(db.Model):
    """
    A pattern-matched alert generated by modules/alerts.py.

    Replaces and extends the legacy ``Alert`` model for all new detections.
    The legacy ``Alert`` table is kept for backward compatibility.

    Fields
    ------
    id          — auto-increment primary key
    log_id      — FK to ParsedLog (the specific line that triggered this alert)
    log_file_id — FK to LogFile (for linking back to the file)
    alert_type  — machine-readable rule name, e.g. "db_connection_failed"
    category    — human-readable grouping: Database / Timeout / Authentication / Server / …
    severity    — low | medium | high | critical
    message     — truncated log body prefixed with the rule label
    source_file — original filename (denormalised for fast display)
    status      — open | acknowledged | resolved | email_sent
    is_read     — simple read/unread flag for the navbar badge
    sent_at     — when the email notification was dispatched (nullable)
    created_at  — row insertion time (UTC)
    """

    __tablename__ = "system_alerts"

    id          = db.Column(db.Integer,     primary_key=True)
    log_id      = db.Column(db.Integer,     db.ForeignKey("parsed_logs.id"), nullable=True,  index=True)
    log_file_id = db.Column(db.Integer,     db.ForeignKey("log_files.id"),   nullable=True,  index=True)
    alert_type  = db.Column(db.String(80),  nullable=False, index=True)
    category    = db.Column(db.String(50),  nullable=False, index=True)
    severity    = db.Column(db.String(20),  nullable=False, index=True)
    message     = db.Column(db.Text,        nullable=False)
    source_file = db.Column(db.String(255), nullable=False, default="")
    status      = db.Column(db.String(30),  nullable=False, default="open", index=True)
    is_read     = db.Column(db.Boolean,     nullable=False, default=False)
    sent_at     = db.Column(db.DateTime,    nullable=True)
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow, index=True)

    # Relationships
    parsed_log = db.relationship(
        "ParsedLog",
        backref=db.backref("system_alerts", lazy=True),
        foreign_keys=[log_id],
    )

    def __repr__(self) -> str:
        return f"<SystemAlert [{self.severity.upper()}] {self.alert_type}>"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "log_id":      self.log_id,
            "log_file_id": self.log_file_id,
            "alert_type":  self.alert_type,
            "category":    self.category,
            "severity":    self.severity,
            "message":     self.message,
            "source_file": self.source_file,
            "status":      self.status,
            "is_read":     self.is_read,
            "sent_at":     self.sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.sent_at else None,
            "created_at":  self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ── Class-level helpers ────────────────────────────────────────────────

    @classmethod
    def unread_count(cls) -> int:
        """Fast count used for the navbar badge."""
        from sqlalchemy import or_
        return cls.query.filter(
            cls.status.in_(["open", "acknowledged"])
        ).filter_by(is_read=False).count()

    @classmethod
    def mark_all_read(cls) -> None:
        """Mark every unread alert as read (called when the alerts page is visited)."""
        cls.query.filter_by(is_read=False).update({"is_read": True})


# ── Alert (legacy) ─────────────────────────────────────────────────────────────

class Alert(db.Model):
    """Legacy alert model — kept for backward compatibility. New code uses SystemAlert."""

    __tablename__ = "alerts"

    id          = db.Column(db.Integer,    primary_key=True)
    log_file_id = db.Column(db.Integer,    db.ForeignKey("log_files.id"), nullable=True)
    alert_type  = db.Column(db.String(50), nullable=False)  # critical_found|error_spike|warning_spike
    severity    = db.Column(db.String(20), nullable=False)  # low|medium|high|critical
    message     = db.Column(db.Text,       nullable=False)
    is_read     = db.Column(db.Boolean,    default=False)
    created_at  = db.Column(db.DateTime,   default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Alert [{self.severity}] {self.alert_type}>"

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "log_file_id": self.log_file_id,
            "alert_type":  self.alert_type,
            "severity":    self.severity,
            "message":     self.message,
            "is_read":     self.is_read,
            "created_at":  self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
