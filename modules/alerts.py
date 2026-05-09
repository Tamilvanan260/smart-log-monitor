"""
modules/alerts.py
=================
Pattern-based alert detection engine for the Smart Log Monitoring system.

Responsibilities
----------------
1. Define keyword patterns for four alert categories (database, timeout,
   authentication, server overload) and map each to a severity level.
2. Scan any ParsedLog message against every pattern, returning Alert rows
   ready for insertion — without performing the INSERT itself (pure logic).
3. Provide ``evaluate_entry()`` for real-time one-at-a-time evaluation
   (called by the watchdog monitor) and ``evaluate_batch()`` for bulk
   post-parse evaluation.
4. Expose ``send_email_alert()`` for optional SMTP notification; the call
   is a no-op when email is not configured in Flask's app config.
5. Provide ``AlertSummary`` — a lightweight dataclass used by the dashboard
   to display aggregate alert statistics.

Design constraints
------------------
- Python 3.10 compatible (no match statements, no 3.11 syntax).
- No side-effects at import time.
- All database writes done by callers, not this module.
- Thread-safe: no mutable module-level state after import.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger(__name__)


# ── Severity constants ─────────────────────────────────────────────────────────

class Severity:
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"

    # Numeric weight for sorting / comparison
    WEIGHT = {LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}

    @classmethod
    def higher(cls, a: str, b: str) -> str:
        """Return whichever severity is higher."""
        return a if cls.WEIGHT.get(a, 0) >= cls.WEIGHT.get(b, 0) else b


# ── Alert status constants ─────────────────────────────────────────────────────

class AlertStatus:
    OPEN        = "open"       # newly created, not yet acknowledged
    ACKNOWLEDGED= "acknowledged"  # seen by a human
    RESOLVED    = "resolved"   # manually closed
    EMAIL_SENT  = "email_sent" # email notification dispatched


# ── Pattern registry ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Pattern:
    """A single detection rule."""
    name:        str          # internal identifier stored in alert_type
    label:       str          # human-readable label shown in the UI
    severity:    str          # one of Severity.*
    category:    str          # grouping label for the dashboard
    regex:       re.Pattern   # compiled, case-insensitive


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


# All detection patterns.
# Order matters: once any pattern matches a message, the most severe match wins.
PATTERNS: list[_Pattern] = [

    # ── Database ──────────────────────────────────────────────────────────────
    _Pattern(
        name="db_connection_failed",
        label="Database Connection Failed",
        severity=Severity.CRITICAL,
        category="Database",
        regex=_compile(
            r"(database\s+connection\s+(failed|refused|lost|dropped|error)|"
            r"db\s+conn(ection)?\s+(failed|refused|lost)|"
            r"could\s+not\s+connect\s+to\s+(database|db|postgres|mysql|sqlite|mongo)|"
            r"connection\s+pool\s+(exhausted|full|timeout)|"
            r"unable\s+to\s+connect\s+to\s+(the\s+)?(database|db))"
        ),
    ),
    _Pattern(
        name="db_query_error",
        label="Database Query Error",
        severity=Severity.HIGH,
        category="Database",
        regex=_compile(
            r"(sql\s+(error|exception|syntax\s+error)|"
            r"query\s+(failed|error|timeout)|"
            r"deadlock\s+(detected|found)|"
            r"table\s+.*\s+(not\s+found|does\s+not\s+exist)|"
            r"integrity\s+(error|constraint)\s+violation)"
        ),
    ),

    # ── Timeout ───────────────────────────────────────────────────────────────
    _Pattern(
        name="request_timeout",
        label="Request Timeout",
        severity=Severity.HIGH,
        category="Timeout",
        regex=_compile(
            r"(request\s+timed?\s*out|"
            r"connection\s+timed?\s*out|"
            r"operation\s+timed?\s*out|"
            r"gateway\s+timeout|"
            r"read\s+timeout|"
            r"write\s+timeout|"
            r"socket\s+timed?\s*out|"
            r"upstream\s+timed?\s*out)"
        ),
    ),
    _Pattern(
        name="service_timeout",
        label="Service Timeout",
        severity=Severity.MEDIUM,
        category="Timeout",
        regex=_compile(
            r"(service\s+(timed?\s*out|unavailable|not\s+responding)|"
            r"health\s+check\s+(failed|timeout)|"
            r"keepalive\s+timeout|"
            r"idle\s+connection\s+timeout)"
        ),
    ),

    # ── Authentication ────────────────────────────────────────────────────────
    _Pattern(
        name="auth_failed",
        label="Authentication Failed",
        severity=Severity.HIGH,
        category="Authentication",
        regex=_compile(
            r"(auth(entication)?\s+(failed|error|denied|rejected|unsuccessful)|"
            r"invalid\s+(credentials|password|token|api\s*key)|"
            r"login\s+(failed|error|denied)|"
            r"access\s+denied|"
            r"permission\s+denied|"
            r"unauthorized\s+(access|request)|"
            r"forbidden\s+(access|request)|"
            r"bad\s+credentials)"
        ),
    ),
    _Pattern(
        name="auth_brute_force",
        label="Possible Brute-Force Attack",
        severity=Severity.CRITICAL,
        category="Authentication",
        regex=_compile(
            r"(too\s+many\s+(failed\s+)?(login|auth(entication)?)\s+(attempts?|tries)|"
            r"brute.?force\s+(detected|attempt)|"
            r"account\s+(locked|blocked|suspended)\s+(due\s+to|after)\s+(failed|too\s+many)|"
            r"rate\s+limit\s+exceeded\s+(for\s+)?(login|auth))"
        ),
    ),

    # ── Server overload ───────────────────────────────────────────────────────
    _Pattern(
        name="server_overload",
        label="Server Overload",
        severity=Severity.CRITICAL,
        category="Server",
        regex=_compile(
            r"(server\s+overload(ed)?|"
            r"out\s+of\s+memory|"
            r"memory\s+(exhausted|full|limit\s+reached)|"
            r"disk\s+(space\s+)?(full|exhausted|critical|below\s+\d+%)|"
            r"cpu\s+(usage\s+)?(critical|at\s+\d{2,3}%|spike|overload)|"
            r"system\s+(overload|resource\s+(exhausted|critical)))"
        ),
    ),
    _Pattern(
        name="high_resource_usage",
        label="High Resource Usage",
        severity=Severity.HIGH,
        category="Server",
        regex=_compile(
            r"(high\s+(memory|cpu|disk|load|resource)\s+(usage|utilization)|"
            r"memory\s+usage\s+(above|exceeded?|at)\s+\d+%|"
            r"cpu\s+(load|usage)\s+(above|exceeded?|at)\s+\d+%|"
            r"load\s+average\s+(high|critical|above)|"
            r"swap\s+(usage\s+)?(high|critical|full))"
        ),
    ),
    _Pattern(
        name="service_crashed",
        label="Service Crash / Restart",
        severity=Severity.CRITICAL,
        category="Server",
        regex=_compile(
            r"(process\s+(killed|crashed|terminated|died)|"
            r"segmentation\s+fault|"
            r"kernel\s+(panic|oops)|"
            r"service\s+(crashed|restarting|failed\s+to\s+start)|"
            r"unhandled\s+exception\s+in\s+(worker|thread|process)|"
            r"fatal\s+error\s+in)"
        ),
    ),

    # ── Network ───────────────────────────────────────────────────────────────
    _Pattern(
        name="network_error",
        label="Network Error",
        severity=Severity.MEDIUM,
        category="Network",
        regex=_compile(
            r"(network\s+(error|unreachable|failure)|"
            r"connection\s+reset\s+by\s+peer|"
            r"broken\s+pipe|"
            r"host\s+(unreachable|not\s+found|down)|"
            r"dns\s+(error|failure|timeout|resolution\s+failed)|"
            r"ssl\s+(error|certificate|handshake\s+fail))"
        ),
    ),

    # ── Disk / Storage ────────────────────────────────────────────────────────
    _Pattern(
        name="disk_error",
        label="Disk / Storage Error",
        severity=Severity.HIGH,
        category="Storage",
        regex=_compile(
            r"(i/o\s+error|"
            r"disk\s+(read|write)\s+(error|failed)|"
            r"file\s+(not\s+found|permission\s+denied|read\s+error)|"
            r"no\s+space\s+left\s+on\s+device|"
            r"storage\s+(error|failure|unavailable))"
        ),
    ),
]

# Severity-to-patterns index for fast lookup
_PATTERNS_BY_SEVERITY: dict[str, list[_Pattern]] = {
    Severity.CRITICAL: [p for p in PATTERNS if p.severity == Severity.CRITICAL],
    Severity.HIGH:     [p for p in PATTERNS if p.severity == Severity.HIGH],
    Severity.MEDIUM:   [p for p in PATTERNS if p.severity == Severity.MEDIUM],
    Severity.LOW:      [p for p in PATTERNS if p.severity == Severity.LOW],
}

# Category list for the UI filter dropdown
CATEGORIES: list[str] = sorted({p.category for p in PATTERNS})


# ── Match result ───────────────────────────────────────────────────────────────

@dataclass
class PatternMatch:
    """Result of matching one pattern against one log message."""
    pattern:  _Pattern
    log_id:   int           # ParsedLog.id that triggered the match
    message:  str           # the message that matched


# ── Core detection ─────────────────────────────────────────────────────────────

def detect_patterns(message: str) -> list[_Pattern]:
    """
    Scan *message* against every registered pattern.

    Returns a list of all matching _Pattern objects, sorted by descending
    severity so callers can easily take the worst match.
    """
    matched: list[_Pattern] = []
    for pattern in PATTERNS:
        if pattern.regex.search(message):
            matched.append(pattern)

    # Sort: CRITICAL first, then HIGH, MEDIUM, LOW
    matched.sort(key=lambda p: Severity.WEIGHT.get(p.severity, 0), reverse=True)
    return matched


def build_alert_from_log(
    parsed_log_id:   int,
    log_file_id:     Optional[int],
    message:         str,
    log_level:       str,
    source_file:     str,
) -> list:
    """
    Evaluate a single ParsedLog message and return a list of
    ``SystemAlert`` ORM instances ready to be added to the session.

    Only the highest-severity pattern per category is returned
    (avoids duplicate alerts for the same message).

    Parameters
    ----------
    parsed_log_id : ParsedLog.id
    log_file_id   : LogFile.id (may be None)
    message       : the log body text
    log_level     : DEBUG / INFO / WARNING / ERROR / CRITICAL
    source_file   : original filename for display
    """
    from modules.models import SystemAlert

    matches = detect_patterns(message)
    if not matches:
        # For CRITICAL/ERROR log lines with no pattern match, still raise a
        # generic alert so nothing slips through the cracks.
        if log_level in ("CRITICAL", "ERROR"):
            sev = Severity.CRITICAL if log_level == "CRITICAL" else Severity.HIGH
            return [SystemAlert(
                log_id=parsed_log_id,
                log_file_id=log_file_id,
                alert_type="generic_error",
                category="General",
                severity=sev,
                message=f"[{log_level}] {message[:500]}",
                source_file=source_file,
                status=AlertStatus.OPEN,
            )]
        return []

    # De-duplicate: one alert per category, highest severity wins
    seen_categories: set[str] = set()
    alerts: list = []

    for pattern in matches:
        if pattern.category in seen_categories:
            continue
        seen_categories.add(pattern.category)

        alerts.append(SystemAlert(
            log_id=parsed_log_id,
            log_file_id=log_file_id,
            alert_type=pattern.name,
            category=pattern.category,
            severity=pattern.severity,
            message=(
                f"[{pattern.label}] {message[:500]}"
            ),
            source_file=source_file,
            status=AlertStatus.OPEN,
        ))

    return alerts


def evaluate_entry(parsed_log, flask_app) -> int:
    """
    Evaluate a single ParsedLog ORM instance and persist any new alerts.

    Designed for real-time use by the watchdog monitor — called inside an
    existing app context.

    Returns the number of new SystemAlert rows created.
    """
    from extensions import db

    new_alerts = build_alert_from_log(
        parsed_log_id=parsed_log.id,
        log_file_id=parsed_log.log_file_id,
        message=parsed_log.message,
        log_level=parsed_log.level,
        source_file=parsed_log.source_file,
    )

    if not new_alerts:
        return 0

    for alert in new_alerts:
        db.session.add(alert)

    db.session.commit()

    # Fire email for CRITICAL/HIGH alerts
    for alert in new_alerts:
        if alert.severity in (Severity.CRITICAL, Severity.HIGH):
            try:
                send_email_alert(alert, flask_app)
            except Exception:
                log.exception("evaluate_entry: email send failed for alert id=%s", alert.id)

    return len(new_alerts)


def evaluate_batch(parsed_log_ids: list[int], flask_app) -> int:
    """
    Evaluate a batch of ParsedLog rows (by id) and persist alerts.

    Used after a file upload is parsed.  Runs inside a single transaction
    per call for efficiency.

    Returns total number of SystemAlert rows created.
    """
    from extensions import db
    from modules.models import ParsedLog

    total = 0
    email_candidates: list = []

    for pid in parsed_log_ids:
        row = ParsedLog.query.get(pid)
        if row is None:
            continue

        new_alerts = build_alert_from_log(
            parsed_log_id=pid,
            log_file_id=row.log_file_id,
            message=row.message,
            log_level=row.level,
            source_file=row.source_file,
        )

        for alert in new_alerts:
            db.session.add(alert)
            if alert.severity in (Severity.CRITICAL, Severity.HIGH):
                email_candidates.append(alert)
        total += len(new_alerts)

    if total:
        db.session.commit()

    # Send emails outside the transaction
    for alert in email_candidates:
        try:
            send_email_alert(alert, flask_app)
        except Exception:
            log.exception("evaluate_batch: email send failed")

    return total


# ── Email notification ─────────────────────────────────────────────────────────

def send_email_alert(alert, flask_app) -> bool:
    """
    Send an SMTP email notification for a SystemAlert.

    Configuration keys (all optional — email is skipped if not set):
        ALERT_EMAIL_ENABLED   bool    (default False)
        ALERT_EMAIL_FROM      str
        ALERT_EMAIL_TO        str     (comma-separated for multiple recipients)
        ALERT_SMTP_HOST       str     (default "localhost")
        ALERT_SMTP_PORT       int     (default 587)
        ALERT_SMTP_USER       str
        ALERT_SMTP_PASSWORD   str
        ALERT_SMTP_TLS        bool    (default True)

    Returns True if the email was sent, False otherwise.
    Updates alert.status to AlertStatus.EMAIL_SENT and sets alert.sent_at.
    Caller is responsible for db.session.commit().
    """
    cfg = flask_app.config

    if not cfg.get("ALERT_EMAIL_ENABLED", False):
        return False

    from_addr  = cfg.get("ALERT_EMAIL_FROM")
    to_addrs   = [a.strip() for a in cfg.get("ALERT_EMAIL_TO", "").split(",") if a.strip()]
    smtp_host  = cfg.get("ALERT_SMTP_HOST", "localhost")
    smtp_port  = int(cfg.get("ALERT_SMTP_PORT", 587))
    smtp_user  = cfg.get("ALERT_SMTP_USER", "")
    smtp_pass  = cfg.get("ALERT_SMTP_PASSWORD", "")
    use_tls    = cfg.get("ALERT_SMTP_TLS", True)

    if not from_addr or not to_addrs:
        log.warning("send_email_alert: ALERT_EMAIL_FROM or ALERT_EMAIL_TO not configured")
        return False

    # Build the email
    subject = f"[{alert.severity.upper()}] {alert.category} Alert – Smart Log Monitor"

    body_text = (
        f"Smart Log Monitoring System — Alert Notification\n"
        f"{'=' * 55}\n\n"
        f"Severity  : {alert.severity.upper()}\n"
        f"Category  : {alert.category}\n"
        f"Type      : {alert.alert_type}\n"
        f"Source    : {alert.source_file}\n"
        f"Detected  : {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Message:\n{alert.message}\n\n"
        f"{'=' * 55}\n"
        f"Log in to the dashboard to review and acknowledge this alert.\n"
    )

    body_html = f"""
<html><body style="font-family:sans-serif;background:#f8f9fa;padding:20px;">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:8px;
            padding:24px;border-left:5px solid
            {'#dc3545' if alert.severity=='critical' else
             '#fd7e14' if alert.severity=='high' else
             '#ffc107' if alert.severity=='medium' else '#6c757d'};">
  <h2 style="margin-top:0;color:
    {'#dc3545' if alert.severity in ('critical','high') else '#212529'}">
    &#9888; {alert.category} Alert
  </h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
    <tr><td style="padding:4px 8px;color:#6c757d;width:100px;">Severity</td>
        <td style="padding:4px 8px;font-weight:bold;color:
          {'#dc3545' if alert.severity in ('critical','high') else '#212529'}">
          {alert.severity.upper()}</td></tr>
    <tr><td style="padding:4px 8px;color:#6c757d;">Category</td>
        <td style="padding:4px 8px;">{alert.category}</td></tr>
    <tr><td style="padding:4px 8px;color:#6c757d;">Type</td>
        <td style="padding:4px 8px;">{alert.alert_type}</td></tr>
    <tr><td style="padding:4px 8px;color:#6c757d;">Source</td>
        <td style="padding:4px 8px;">{alert.source_file}</td></tr>
    <tr><td style="padding:4px 8px;color:#6c757d;">Detected</td>
        <td style="padding:4px 8px;">{alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
  </table>
  <div style="background:#f8f9fa;border-radius:4px;padding:12px;
              font-family:monospace;font-size:13px;word-break:break-all;">
    {alert.message}
  </div>
  <p style="color:#6c757d;font-size:12px;margin-top:16px;margin-bottom:0;">
    Log in to your Smart Log Monitor dashboard to acknowledge this alert.
  </p>
</div>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(to_addrs)
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls(context=context)
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_addrs, msg.as_string())

        # Update alert status
        from extensions import db
        alert.status  = AlertStatus.EMAIL_SENT
        alert.sent_at = datetime.utcnow()
        # Do NOT commit here — caller manages the transaction

        log.info("Alert email sent to %s for alert id=%s", to_addrs, alert.id)
        return True

    except smtplib.SMTPException as exc:
        log.error("send_email_alert: SMTP error: %s", exc)
        return False
    except OSError as exc:
        log.error("send_email_alert: network error: %s", exc)
        return False


# ── Alert summary for dashboard ────────────────────────────────────────────────

@dataclass
class AlertSummary:
    """Aggregate counts used by the dashboard stat section."""
    total:         int = 0
    critical:      int = 0
    high:          int = 0
    medium:        int = 0
    low:           int = 0
    open_count:    int = 0
    unread:        int = 0
    by_category:   dict = field(default_factory=dict)
    recent:        list = field(default_factory=list)


def get_alert_summary(limit_recent: int = 10) -> AlertSummary:
    """
    Query the database and return an AlertSummary.
    Must be called inside a Flask application context.
    """
    from sqlalchemy import func
    from extensions import db
    from modules.models import SystemAlert

    summary = AlertSummary()

    # Totals by severity
    sev_rows = (
        db.session.query(SystemAlert.severity, func.count(SystemAlert.id))
        .group_by(SystemAlert.severity)
        .all()
    )
    for sev, count in sev_rows:
        summary.total += count
        if sev == Severity.CRITICAL:
            summary.critical = count
        elif sev == Severity.HIGH:
            summary.high = count
        elif sev == Severity.MEDIUM:
            summary.medium = count
        elif sev == Severity.LOW:
            summary.low = count

    # Open count
    summary.open_count = SystemAlert.query.filter_by(status=AlertStatus.OPEN).count()

    # Unread (open + acknowledged, not resolved)
    summary.unread = SystemAlert.query.filter(
        SystemAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED])
    ).count()

    # By category
    cat_rows = (
        db.session.query(SystemAlert.category, func.count(SystemAlert.id))
        .group_by(SystemAlert.category)
        .all()
    )
    summary.by_category = dict(cat_rows)

    # Recent alerts
    summary.recent = (
        SystemAlert.query
        .order_by(SystemAlert.created_at.desc())
        .limit(limit_recent)
        .all()
    )

    return summary
