"""
modules/routes.py
=================
Flask Blueprints for all application routes.

Blueprints
----------
main_bp  — page routes returning HTML responses
api_bp   — JSON API routes under /api/
"""

from __future__ import annotations

import os
import uuid

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, jsonify, current_app,
)
from sqlalchemy import func, distinct
from werkzeug.utils import secure_filename

from extensions import db
from modules.models import LogFile, LogEntry, ParsedLog, WatchedFile, SystemAlert
from modules.log_parser import parse_and_store
from modules.parser import (
    FileValidationError,
    parse_file,
    store_parsed_result,
    validate_upload,
)
from modules.auth import login_required, admin_required, api_login_required, api_admin_required

# ── Blueprints ─────────────────────────────────────────────────────────────────

main_bp = Blueprint("main", __name__)
api_bp  = Blueprint("api",  __name__, url_prefix="/api")


# ── Private helpers ────────────────────────────────────────────────────────────

def _ext_allowed(filename: str) -> bool:
    """Return True when *filename* has an extension in the configured allow-list."""
    allowed = current_app.config.get("ALLOWED_EXTENSIONS", {"log", "txt"})
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def _dashboard_stats() -> dict:
    """
    Build the stat-card data for the dashboard in a single function.

    Combines counts from both the strict-format ``ParsedLog`` table and the
    legacy ``LogEntry`` table so that all uploaded files are represented.
    """
    pl_counts = dict(
        db.session.query(ParsedLog.level, func.count(ParsedLog.id))
        .group_by(ParsedLog.level)
        .all()
    )
    le_counts = dict(
        db.session.query(LogEntry.level, func.count(LogEntry.id))
        .group_by(LogEntry.level)
        .all()
    )

    def _combined(level: str) -> int:
        return pl_counts.get(level, 0) + le_counts.get(level, 0)

    latest_critical = (
        ParsedLog.query
        .filter_by(level="CRITICAL")
        .order_by(ParsedLog.timestamp.desc())
        .first()
    )

    return {
        "total_files":     LogFile.query.count(),
        "total_logs":      ParsedLog.query.count() + LogEntry.query.count(),
        "total_debug":     _combined("DEBUG"),
        "total_info":      _combined("INFO"),
        "total_warning":   _combined("WARNING"),
        "total_error":     _combined("ERROR"),
        "total_critical":  _combined("CRITICAL"),
        "unread_alerts":   SystemAlert.unread_count(),
        "latest_critical": latest_critical,
    }


# ── Home ───────────────────────────────────────────────────────────────────────

@main_bp.route("/")
def home():
    return render_template("home.html")


# ── Dashboard ──────────────────────────────────────────────────────────────────

@main_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Main dashboard.

    Displays:
      - Stat cards: Total Logs, INFO, WARNING, ERROR, CRITICAL, Files
      - Latest Critical Error panel
      - Full parsed log table with three filters:
          · level    (dropdown)
          · keyword  (search box)
          · source   (dropdown — populated from distinct source_file values)
      - Pagination (50 rows per page)
    """
    # ── Filter params ──────────────────────────────────────────────────────
    level_filter  = request.args.get("level",  "").strip().upper()
    search_query  = request.args.get("q",      "").strip()
    source_filter = request.args.get("source", "").strip()
    page          = request.args.get("page", 1, type=int)
    per_page      = 50

    # ── Build query ────────────────────────────────────────────────────────
    query = ParsedLog.query

    if level_filter:
        query = query.filter(ParsedLog.level == level_filter)

    if search_query:
        query = query.filter(ParsedLog.message.ilike(f"%{search_query}%"))

    if source_filter:
        query = query.filter(ParsedLog.source_file == source_filter)

    logs_page = query.order_by(ParsedLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # ── Distinct source files for the filter dropdown ──────────────────────
    source_files = [
        row[0] for row in
        db.session.query(distinct(ParsedLog.source_file))
        .order_by(ParsedLog.source_file)
        .all()
    ]

    stats         = _dashboard_stats()
    recent_alerts = SystemAlert.query.order_by(SystemAlert.created_at.desc()).limit(5).all()

    from modules.alerts import get_alert_summary
    alert_summary = get_alert_summary(limit_recent=5)

    return render_template(
        "dashboard.html",
        stats=stats,
        logs_page=logs_page,
        source_files=source_files,
        level_filter=level_filter,
        search_query=search_query,
        source_filter=source_filter,
        recent_alerts=recent_alerts,
        alert_summary=alert_summary,
    )


# ── Upload ─────────────────────────────────────────────────────────────────────

@main_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """
    Log file upload page.

    POST flow:
      1.  Validate file presence and extension.
      2.  Save to uploads/ with a UUID-prefixed unique name.
      3.  Run validate_upload() for size / extension / empty checks.
      4.  Create a LogFile record (status = pending).
      5.  Run the strict-format parser (modules/parser.py).
            - Matched lines   → stored as ParsedLog rows.
            - No matches      → fall back to legacy parser (log_parser.py).
            - Read error      → mark status=error.
      6.  Generate alerts from level counts.
      7.  Redirect to dashboard.
    """
    if request.method != "POST":
        return render_template("upload.html")

    # ── 1. File presence & extension ───────────────────────────────────────
    if "log_file" not in request.files:
        flash("No file part found in the request.", "danger")
        return redirect(request.url)

    file = request.files["log_file"]
    if not file or file.filename == "":
        flash("No file selected.", "warning")
        return redirect(request.url)

    if not _ext_allowed(file.filename):
        flash("Invalid file type. Only .log and .txt files are accepted.", "danger")
        return redirect(request.url)

    # ── 2. Save to disk ────────────────────────────────────────────────────
    original_name = secure_filename(file.filename)
    unique_name   = f"{uuid.uuid4().hex}_{original_name}"
    save_path     = os.path.join(current_app.config["UPLOAD_FOLDER"], unique_name)
    file.save(save_path)
    file_size = os.path.getsize(save_path)

    # ── 3. Pre-parse validation ────────────────────────────────────────────
    try:
        validate_upload(original_name, file_size)
    except FileValidationError as exc:
        os.remove(save_path)
        flash(str(exc), "danger")
        return redirect(request.url)

    # ── 4. Persist LogFile record ──────────────────────────────────────────
    log_file = LogFile(
        filename=unique_name,
        original_name=original_name,
        file_size=file_size,
        status="pending",
    )
    db.session.add(log_file)
    db.session.commit()

    # ── 5. Strict-format parse ─────────────────────────────────────────────
    parse_result = parse_file(save_path, original_name)

    if parse_result.has_errors:
        flash(f"Could not read '{original_name}': {parse_result.errors[0]}", "danger")
        log_file.status = "error"
        db.session.commit()
        return redirect(url_for("main.logs"))

    if parse_result.parsed:
        parsed_count = store_parsed_result(parse_result, log_file.id, original_name)

        # Pattern-based alert detection via alerts engine
        from modules.alerts import evaluate_batch
        new_parsed_ids = [
            row.id for row in
            ParsedLog.query.filter_by(log_file_id=log_file.id)
            .order_by(ParsedLog.id.desc())
            .limit(parsed_count)
            .all()
        ]
        alert_count = evaluate_batch(new_parsed_ids, current_app._get_current_object())

        log_file.status = "analyzed"
        db.session.commit()

        skip_count = len(parse_result.skipped_lines)
        alert_msg  = f", {alert_count} alert(s) generated" if alert_count else ""
        if skip_count:
            flash(
                f"'{original_name}' parsed: {parsed_count} entries stored, "
                f"{skip_count} line(s) skipped (unrecognised format){alert_msg}.",
                "warning",
            )
        else:
            flash(
                f"'{original_name}' analysed — {parsed_count} entries stored{alert_msg}.",
                "success",
            )
    else:
        # Zero strict-format matches — fall back to legacy parser
        try:
            counts = parse_and_store(log_file, save_path)
            flash(
                f"'{original_name}' processed with the fallback parser — "
                f"{counts.get('ERROR', 0)} error(s), "
                f"{counts.get('CRITICAL', 0)} critical entries.",
                "warning",
            )
        except Exception as exc:
            log_file.status = "error"
            db.session.commit()
            flash(f"Parsing failed: {exc}", "danger")
            return redirect(url_for("main.logs"))

    # Redirect to dashboard so user sees the new data immediately
    return redirect(url_for("main.dashboard"))


# ── Parsed results (per-file detail view) ─────────────────────────────────────

@main_bp.route("/logs/<int:file_id>/parsed")
@login_required
def parsed_results(file_id: int):
    """Detail view — ParsedLog entries for a single uploaded file."""
    log_file     = LogFile.query.get_or_404(file_id)
    page         = request.args.get("page", 1, type=int)
    level_filter = request.args.get("level", "").upper()
    search_query = request.args.get("q", "").strip()

    query = ParsedLog.query.filter_by(log_file_id=file_id)

    if level_filter:
        query = query.filter_by(level=level_filter)
    if search_query:
        query = query.filter(ParsedLog.message.ilike(f"%{search_query}%"))

    entries      = query.order_by(ParsedLog.timestamp).paginate(page=page, per_page=50)
    level_counts = ParsedLog.level_counts_for_file(file_id)
    sev_counts   = ParsedLog.severity_counts_for_file(file_id)

    return render_template(
        "parsed_results.html",
        log_file=log_file,
        entries=entries,
        level_counts=level_counts,
        sev_counts=sev_counts,
        level_filter=level_filter,
        search_query=search_query,
    )


# ── Log list / detail / delete ─────────────────────────────────────────────────

@main_bp.route("/logs")
@login_required
def logs():
    page  = request.args.get("page", 1, type=int)
    files = LogFile.query.order_by(LogFile.uploaded_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    return render_template("logs.html", files=files)


@main_bp.route("/logs/<int:file_id>")
@login_required
def log_detail(file_id: int):
    """Legacy LogEntry viewer kept for backward compatibility."""
    log_file     = LogFile.query.get_or_404(file_id)
    page         = request.args.get("page", 1, type=int)
    level_filter = request.args.get("level", "")

    query = LogEntry.query.filter_by(log_file_id=file_id)
    if level_filter:
        query = query.filter_by(level=level_filter.upper())

    entries = query.order_by(LogEntry.line_number).paginate(
        page=page, per_page=50, error_out=False
    )
    level_counts = {
        lvl: LogEntry.query.filter_by(log_file_id=file_id, level=lvl).count()
        for lvl in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    }

    return render_template(
        "log_detail.html",
        log_file=log_file,
        entries=entries,
        level_counts=level_counts,
        level_filter=level_filter,
    )


@main_bp.route("/logs/<int:file_id>/delete", methods=["POST"])
@admin_required
def delete_log(file_id: int):
    log_file = LogFile.query.get_or_404(file_id)
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], log_file.filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    db.session.delete(log_file)
    db.session.commit()
    flash(f"'{log_file.original_name}' deleted.", "success")
    return redirect(url_for("main.logs"))


# ── Alerts ─────────────────────────────────────────────────────────────────────

@main_bp.route("/alerts")
@login_required
def alerts():
    """
    Alert centre — shows SystemAlert rows with filtering and pagination.
    Visiting marks all alerts as read.
    """
    page            = request.args.get("page",     1,    type=int)
    severity_filter = request.args.get("severity", "").strip().lower()
    status_filter   = request.args.get("status",   "").strip().lower()
    category_filter = request.args.get("category", "").strip()
    search_query    = request.args.get("q",         "").strip()

    query = SystemAlert.query

    if severity_filter:
        query = query.filter_by(severity=severity_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)
    if search_query:
        query = query.filter(SystemAlert.message.ilike(f"%{search_query}%"))

    all_alerts = query.order_by(SystemAlert.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )

    # Mark all unread as read on page visit
    SystemAlert.mark_all_read()
    db.session.commit()

    from modules.alerts import get_alert_summary, CATEGORIES
    alert_summary = get_alert_summary(limit_recent=0)

    return render_template(
        "alerts.html",
        alerts=all_alerts,
        severity_filter=severity_filter,
        status_filter=status_filter,
        category_filter=category_filter,
        search_query=search_query,
        alert_summary=alert_summary,
        categories=CATEGORIES,
    )


@main_bp.route("/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@admin_required
def alert_acknowledge(alert_id: int):
    """Mark a single alert as acknowledged."""
    alert = SystemAlert.query.get_or_404(alert_id)
    from modules.alerts import AlertStatus
    alert.status  = AlertStatus.ACKNOWLEDGED
    alert.is_read = True
    db.session.commit()
    flash(f"Alert #{alert_id} acknowledged.", "success")
    return redirect(request.referrer or url_for("main.alerts"))


@main_bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@admin_required
def alert_resolve(alert_id: int):
    """Mark a single alert as resolved."""
    alert = SystemAlert.query.get_or_404(alert_id)
    from modules.alerts import AlertStatus
    alert.status  = AlertStatus.RESOLVED
    alert.is_read = True
    db.session.commit()
    flash(f"Alert #{alert_id} resolved.", "success")
    return redirect(request.referrer or url_for("main.alerts"))


@main_bp.route("/alerts/resolve-all", methods=["POST"])
@admin_required
def alerts_resolve_all():
    """Bulk-resolve all open alerts."""
    from modules.alerts import AlertStatus
    SystemAlert.query.filter_by(status=AlertStatus.OPEN).update({
        "status":  AlertStatus.RESOLVED,
        "is_read": True,
    })
    db.session.commit()
    flash("All open alerts resolved.", "success")
    return redirect(url_for("main.alerts"))


# ── JSON API ───────────────────────────────────────────────────────────────────

@api_bp.route("/stats")
@api_login_required
def api_stats():
    """Dashboard statistics as JSON."""
    stats = _dashboard_stats()
    # Make latest_critical serialisable
    lc = stats.get("latest_critical")
    stats["latest_critical"] = lc.to_dict() if lc else None
    return jsonify(stats)


@api_bp.route("/logs")
@api_login_required
def api_logs():
    files = LogFile.query.order_by(LogFile.uploaded_at.desc()).limit(20).all()
    return jsonify([f.to_dict() for f in files])


@api_bp.route("/logs/<int:file_id>/entries")
@api_login_required
def api_entries(file_id: int):
    level   = request.args.get("level", "")
    query   = LogEntry.query.filter_by(log_file_id=file_id)
    if level:
        query = query.filter_by(level=level.upper())
    entries = query.order_by(LogEntry.line_number).limit(200).all()
    return jsonify([e.to_dict() for e in entries])


@api_bp.route("/logs/<int:file_id>/parsed")
@api_login_required
def api_parsed(file_id: int):
    level = request.args.get("level", "")
    limit = min(request.args.get("limit", 200, type=int), 500)
    query = ParsedLog.query.filter_by(log_file_id=file_id)
    if level:
        query = query.filter_by(level=level.upper())
    rows = query.order_by(ParsedLog.timestamp).limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route("/logs/<int:file_id>/parsed/summary")
@api_login_required
def api_parsed_summary(file_id: int):
    LogFile.query.get_or_404(file_id)
    return jsonify({
        "level_counts":    ParsedLog.level_counts_for_file(file_id),
        "severity_counts": ParsedLog.severity_counts_for_file(file_id),
    })


@api_bp.route("/alerts/unread-count")
@api_login_required
def api_unread_alerts():
    count = SystemAlert.unread_count()
    return jsonify({"unread": count})


@api_bp.route("/alerts/summary")
@api_login_required
def api_alert_summary():
    """JSON alert summary used by the dashboard alert panel."""
    from modules.alerts import get_alert_summary
    s = get_alert_summary(limit_recent=10)
    return jsonify({
        "total":       s.total,
        "critical":    s.critical,
        "high":        s.high,
        "medium":      s.medium,
        "low":         s.low,
        "open_count":  s.open_count,
        "unread":      s.unread,
        "by_category": s.by_category,
        "recent":      [a.to_dict() for a in s.recent],
    })


# ── Chart data endpoints ───────────────────────────────────────────────────────

@api_bp.route("/charts/level-distribution")
@api_login_required
def api_chart_level_distribution():
    """
    Returns log counts grouped by level for the doughnut / bar chart.

    Response shape:
        {
          "labels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
          "counts": [12, 45, 8, 5, 2]
        }
    """
    # Combine ParsedLog + legacy LogEntry counts
    pl = dict(
        db.session.query(ParsedLog.level, func.count(ParsedLog.id))
        .group_by(ParsedLog.level)
        .all()
    )
    le = dict(
        db.session.query(LogEntry.level, func.count(LogEntry.id))
        .group_by(LogEntry.level)
        .all()
    )

    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    counts = [pl.get(lvl, 0) + le.get(lvl, 0) for lvl in levels]

    return jsonify({"labels": levels, "counts": counts})


@api_bp.route("/charts/error-trend")
@api_login_required
def api_chart_error_trend():
    """
    Returns daily ERROR counts over the last N days for the line chart.

    Query param:
        days  (int, default 30) — look-back window, max 90

    Response shape:
        {
          "labels": ["2026-04-01", "2026-04-02", ...],
          "counts": [3, 0, 7, ...]
        }
    """
    from datetime import date, timedelta

    days  = min(request.args.get("days", 30, type=int), 90)
    today = date.today()
    since = today - timedelta(days=days)

    # Aggregate by date string (SQLite strftime works on datetime columns)
    rows = (
        db.session.query(
            func.strftime("%Y-%m-%d", ParsedLog.timestamp).label("day"),
            func.count(ParsedLog.id).label("cnt"),
        )
        .filter(ParsedLog.level == "ERROR")
        .filter(func.strftime("%Y-%m-%d", ParsedLog.timestamp) >= since.isoformat())
        .group_by("day")
        .order_by("day")
        .all()
    )

    row_map  = {r.day: r.cnt for r in rows}
    all_days = [
        (since + timedelta(days=i)).isoformat()
        for i in range(days + 1)
    ]
    counts = [row_map.get(d, 0) for d in all_days]

    return jsonify({"labels": all_days, "counts": counts})


@api_bp.route("/charts/warning-trend")
@api_login_required
def api_chart_warning_trend():
    """
    Returns daily WARNING counts over the last N days for the line chart.

    Query param:
        days  (int, default 30) — look-back window, max 90

    Response shape:
        {
          "labels": ["2026-04-01", "2026-04-02", ...],
          "counts": [1, 0, 4, ...]
        }
    """
    from datetime import date, timedelta

    days  = min(request.args.get("days", 30, type=int), 90)
    today = date.today()
    since = today - timedelta(days=days)

    rows = (
        db.session.query(
            func.strftime("%Y-%m-%d", ParsedLog.timestamp).label("day"),
            func.count(ParsedLog.id).label("cnt"),
        )
        .filter(ParsedLog.level == "WARNING")
        .filter(func.strftime("%Y-%m-%d", ParsedLog.timestamp) >= since.isoformat())
        .group_by("day")
        .order_by("day")
        .all()
    )

    row_map  = {r.day: r.cnt for r in rows}
    all_days = [
        (since + timedelta(days=i)).isoformat()
        for i in range(days + 1)
    ]
    counts = [row_map.get(d, 0) for d in all_days]

    return jsonify({"labels": all_days, "counts": counts})


@api_bp.route("/charts/combined-trend")
@api_login_required
def api_chart_combined_trend():
    """
    Returns daily ERROR + WARNING counts on a shared timeline.
    Single fetch lets the front-end draw both series on one chart.

    Query param:
        days  (int, default 30) — look-back window, max 90

    Response shape:
        {
          "labels":   ["2026-04-01", ...],
          "errors":   [3, 0, 7, ...],
          "warnings": [1, 2, 0, ...]
        }
    """
    from datetime import date, timedelta

    days  = min(request.args.get("days", 30, type=int), 90)
    today = date.today()
    since = today - timedelta(days=days)

    rows = (
        db.session.query(
            func.strftime("%Y-%m-%d", ParsedLog.timestamp).label("day"),
            ParsedLog.level,
            func.count(ParsedLog.id).label("cnt"),
        )
        .filter(ParsedLog.level.in_(["ERROR", "WARNING"]))
        .filter(func.strftime("%Y-%m-%d", ParsedLog.timestamp) >= since.isoformat())
        .group_by("day", ParsedLog.level)
        .order_by("day")
        .all()
    )

    lookup: dict = {}
    for row in rows:
        lookup.setdefault(row.day, {})[row.level] = row.cnt

    all_days = [
        (since + timedelta(days=i)).isoformat()
        for i in range(days + 1)
    ]
    errors   = [lookup.get(d, {}).get("ERROR",   0) for d in all_days]
    warnings = [lookup.get(d, {}).get("WARNING", 0) for d in all_days]

    return jsonify({"labels": all_days, "errors": errors, "warnings": warnings})


# ── Export routes ──────────────────────────────────────────────────────────────

@main_bp.route("/export/logs")
@admin_required
def export_logs():
    """
    Download parsed log entries as CSV or Excel.

    Query params (all optional, mirror the dashboard filter):
        level   — log level filter (DEBUG / INFO / WARNING / ERROR / CRITICAL)
        source  — source filename filter
        q       — keyword search on message
        fmt     — 'csv' (default) or 'excel'
        limit   — max rows (default 50 000, max 100 000)
    """
    from modules.export import export_logs as _export

    level  = request.args.get("level",  "").strip().upper() or None
    source = request.args.get("source", "").strip() or None
    q      = request.args.get("q",      "").strip() or None
    fmt    = request.args.get("fmt",    "csv").strip().lower()
    limit  = min(request.args.get("limit", 50_000, type=int), 100_000)

    if fmt not in ("csv", "excel"):
        fmt = "csv"

    return _export(level=level, source=source, q=q, fmt=fmt, limit=limit)


@main_bp.route("/export/alerts")
@admin_required
def export_alerts():
    """
    Download system alerts as CSV or Excel.

    Query params (all optional, mirror the alerts page filter):
        severity — low / medium / high / critical
        status   — open / acknowledged / resolved / email_sent
        category — alert category
        q        — keyword search on message
        fmt      — 'csv' (default) or 'excel'
    """
    from modules.export import export_alerts as _export

    severity = request.args.get("severity", "").strip().lower() or None
    status   = request.args.get("status",   "").strip().lower() or None
    category = request.args.get("category", "").strip() or None
    q        = request.args.get("q",        "").strip() or None
    fmt      = request.args.get("fmt",      "csv").strip().lower()

    if fmt not in ("csv", "excel"):
        fmt = "csv"

    return _export(severity=severity, status=status,
                   category=category, q=q, fmt=fmt)


@main_bp.route("/export/summary")
@admin_required
def export_summary():
    """
    Download a full system summary report.

    Query params:
        fmt — 'csv' (default) or 'excel'
              Excel produces a multi-sheet workbook (requires openpyxl).
              Falls back to CSV automatically if openpyxl is not installed.
    """
    from modules.export import export_summary as _export

    fmt = request.args.get("fmt", "csv").strip().lower()
    if fmt not in ("csv", "excel"):
        fmt = "csv"

    return _export(fmt=fmt)


# ── Real-time monitor routes ───────────────────────────────────────────────────

@main_bp.route("/monitor")
@admin_required
def monitor():
    """
    Live monitoring page.
    Shows all watched files and lets users start/stop monitoring.
    """
    from modules.models import WatchedFile
    from modules.monitor import LogFileMonitor

    # All files available for monitoring (only analyzed ones make sense)
    available_files = (
        LogFile.query
        .filter_by(status="analyzed")
        .order_by(LogFile.uploaded_at.desc())
        .all()
    )

    # Enrich WatchedFile rows with live observer status
    watched_rows = WatchedFile.query.order_by(WatchedFile.started_at.desc()).all()
    active_ids   = {e["log_file_id"] for e in LogFileMonitor.list_active()}
    for w in watched_rows:
        w._observer_alive = w.log_file_id in active_ids

    return render_template(
        "monitor.html",
        available_files=available_files,
        watched_rows=watched_rows,
        active_ids=active_ids,
    )


@main_bp.route("/monitor/start/<int:file_id>", methods=["POST"])
@admin_required
def monitor_start(file_id: int):
    """Start real-time monitoring for a log file."""
    import os as _os
    from flask import current_app
    from modules.monitor import LogFileMonitor

    log_file = LogFile.query.get_or_404(file_id)
    abs_path = _os.path.join(current_app.config["UPLOAD_FOLDER"], log_file.filename)

    if not _os.path.isfile(abs_path):
        flash(f"File '{log_file.original_name}' not found on disk.", "danger")
        return redirect(url_for("main.monitor"))

    if LogFileMonitor.is_active(file_id):
        flash(f"'{log_file.original_name}' is already being monitored.", "warning")
        return redirect(url_for("main.monitor"))

    ok = LogFileMonitor.start(
        flask_app=current_app._get_current_object(),
        abs_path=abs_path,
        log_file_id=file_id,
        source_filename=log_file.original_name,
    )
    if ok:
        flash(f"Started monitoring '{log_file.original_name}'.", "success")
    else:
        flash(f"Could not start monitor for '{log_file.original_name}'.", "danger")

    return redirect(url_for("main.monitor"))


@main_bp.route("/monitor/stop/<int:file_id>", methods=["POST"])
@admin_required
def monitor_stop(file_id: int):
    """Stop real-time monitoring for a log file."""
    from modules.monitor import LogFileMonitor
    from modules.models import WatchedFile

    log_file = LogFile.query.get_or_404(file_id)
    LogFileMonitor.stop(file_id)

    # Mark as inactive in DB
    watched = WatchedFile.query.filter_by(log_file_id=file_id).first()
    if watched:
        watched.is_active = False
        db.session.commit()

    flash(f"Stopped monitoring '{log_file.original_name}'.", "info")
    return redirect(url_for("main.monitor"))


# ── Live-feed API endpoints ────────────────────────────────────────────────────

@api_bp.route("/monitor/status")
@api_login_required
def api_monitor_status():
    """
    Returns live status of all active monitors.

    Response shape:
        [
          {
            "log_file_id": 3,
            "watch_path":  "/uploads/uuid_server.log",
            "observer_alive": true
          }, ...
        ]
    """
    from modules.monitor import LogFileMonitor
    return jsonify(LogFileMonitor.list_active())


@api_bp.route("/monitor/live-feed")
@api_login_required
def api_live_feed():
    """
    Returns the N most recent ParsedLog entries across ALL actively-monitored
    files, ordered newest-first.  Used by the live-feed panel to auto-refresh.

    Query params:
        limit     (int, default 50, max 200)
        after_id  (int, default 0)  — return only rows with id > after_id
                                       (client sends the last id it saw)
    """
    from modules.models import WatchedFile
    from modules.monitor import LogFileMonitor

    limit    = min(request.args.get("limit",    50,  type=int), 200)
    after_id = request.args.get("after_id", 0,  type=int)

    # Only serve rows from files that *have* a WatchedFile row
    watched_file_ids = [
        row[0]
        for row in db.session.query(WatchedFile.log_file_id).all()
    ]

    if not watched_file_ids:
        return jsonify({"rows": [], "max_id": 0})

    query = (
        ParsedLog.query
        .filter(ParsedLog.log_file_id.in_(watched_file_ids))
    )
    if after_id > 0:
        query = query.filter(ParsedLog.id > after_id)

    rows   = query.order_by(ParsedLog.id.desc()).limit(limit).all()
    max_id = rows[0].id if rows else after_id

    # Active monitor ids for the UI status dots
    active_ids = {e["log_file_id"] for e in LogFileMonitor.list_active()}

    return jsonify({
        "rows":       [r.to_dict() for r in rows],
        "max_id":     max_id,
        "active_ids": list(active_ids),
    })


@api_bp.route("/monitor/stats")
@api_login_required
def api_monitor_stats():
    """
    Returns per-file summary for all watched files.

    Response shape:
        [
          {
            "log_file_id":     3,
            "source_filename": "server.log",
            "is_active":       true,
            "last_seen_at":    "2026-05-03 10:12:44",
            "lines_processed": 142,
            "total_entries":   139,
            "error_count":     4,
            "critical_count":  1
          }, ...
        ]
    """
    from modules.models import WatchedFile
    from modules.monitor import LogFileMonitor

    watched_rows = WatchedFile.query.order_by(WatchedFile.started_at.desc()).all()
    active_ids   = {e["log_file_id"] for e in LogFileMonitor.list_active()}
    result       = []

    for w in watched_rows:
        fid  = w.log_file_id
        total   = ParsedLog.query.filter_by(log_file_id=fid).count()
        errors  = ParsedLog.query.filter_by(log_file_id=fid, level="ERROR").count()
        crits   = ParsedLog.query.filter_by(log_file_id=fid, level="CRITICAL").count()
        row_dict = w.to_dict()
        row_dict.update({
            "is_active":      fid in active_ids,
            "observer_alive": fid in active_ids,
            "total_entries":  total,
            "error_count":    errors,
            "critical_count": crits,
        })
        result.append(row_dict)

    return jsonify(result)
