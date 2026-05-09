"""
modules/export.py
=================
Export engine for the Smart Log Monitoring & Alert System.

Provides functions that build pandas DataFrames from SQLAlchemy queries
and return Flask ``Response`` objects ready for browser download.

Supported formats
-----------------
* CSV   — plain text, universally compatible, UTF-8 with BOM for Excel compat
* Excel — .xlsx via openpyxl (optional; falls back to CSV if not installed)

Public API
----------
``export_logs(filters)``     → Flask Response (CSV or Excel)
``export_alerts(filters)``   → Flask Response (CSV or Excel)
``export_summary()``         → Flask Response (CSV) — overall system summary

All functions must be called inside a Flask application context.

Design notes
------------
* No file is written to disk — everything is streamed via ``io.BytesIO``.
* Filters are passed as plain dicts so routes stay thin.
* Python 3.10 compatible throughout.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from flask import Response, current_app

log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utc_stamp() -> str:
    """Return a compact UTC timestamp string suitable for filenames."""
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def _csv_response(df: pd.DataFrame, filename: str) -> Response:
    """
    Serialise a DataFrame to CSV and return a Flask download Response.

    Uses UTF-8-SIG (BOM) so Excel opens it correctly without an import wizard.
    """
    buf = io.StringIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    csv_bytes = buf.getvalue().encode("utf-8-sig")

    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(csv_bytes)),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _excel_response(df: pd.DataFrame, filename: str, sheet_name: str = "Data") -> Response:
    """
    Serialise a DataFrame to .xlsx and return a Flask download Response.

    Raises ImportError if openpyxl is not installed; caller should fall back
    to _csv_response in that case.
    """
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)

        # Auto-fit column widths (best-effort)
        ws = writer.sheets[sheet_name]
        for col_idx, col in enumerate(df.columns, start=1):
            max_len = max(
                len(str(col)),
                df[col].astype(str).str.len().max() if len(df) else 0,
            )
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = (
                min(max_len + 4, 60)
            )

    xlsx_bytes = buf.getvalue()
    return Response(
        xlsx_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(xlsx_bytes)),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _best_response(df: pd.DataFrame, base_name: str,
                   fmt: str, sheet_name: str = "Data") -> Response:
    """
    Return CSV or Excel response depending on *fmt* ('csv' | 'excel').
    Falls back to CSV if openpyxl is unavailable.
    """
    if fmt == "excel":
        try:
            import openpyxl  # noqa: F401
            return _excel_response(df, f"{base_name}.xlsx", sheet_name)
        except ImportError:
            log.warning("openpyxl not installed — falling back to CSV")

    return _csv_response(df, f"{base_name}.csv")


# ── Log export ─────────────────────────────────────────────────────────────────

def export_logs(
    level:   Optional[str] = None,
    source:  Optional[str] = None,
    q:       Optional[str] = None,
    fmt:     str = "csv",
    limit:   int = 50_000,
) -> Response:
    """
    Export ParsedLog rows that match the given filters.

    Parameters
    ----------
    level   : filter by log level (DEBUG / INFO / WARNING / ERROR / CRITICAL)
    source  : filter by source filename
    q       : keyword substring match on message
    fmt     : 'csv' or 'excel'
    limit   : maximum rows exported (safety cap, default 50 000)

    Returns
    -------
    Flask ``Response`` — triggers a browser file download.
    """
    from modules.models import ParsedLog

    query = ParsedLog.query

    if level:
        query = query.filter(ParsedLog.level == level.upper())
    if source:
        query = query.filter(ParsedLog.source_file == source)
    if q:
        query = query.filter(ParsedLog.message.ilike(f"%{q}%"))

    rows = query.order_by(ParsedLog.timestamp.desc()).limit(limit).all()

    if not rows:
        # Return an empty CSV with headers rather than a 404
        df = pd.DataFrame(columns=[
            "id", "timestamp", "level", "severity",
            "message", "source_file", "log_file_id", "created_at",
        ])
    else:
        df = pd.DataFrame([
            {
                "id":          r.id,
                "timestamp":   r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "level":       r.level,
                "severity":    r.severity,
                "message":     r.message,
                "source_file": r.source_file,
                "log_file_id": r.log_file_id,
                "created_at":  r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for r in rows
        ])

    # Build a descriptive filename
    parts = ["logs"]
    if level:
        parts.append(level.lower())
    if source:
        # Sanitise source filename for use in the download filename
        safe_src = "".join(c if c.isalnum() or c in "-_." else "_" for c in source)
        parts.append(safe_src)
    parts.append(_utc_stamp())

    base_name = "_".join(parts)
    return _best_response(df, base_name, fmt, sheet_name="Logs")


# ── Alert export ───────────────────────────────────────────────────────────────

def export_alerts(
    severity: Optional[str] = None,
    status:   Optional[str] = None,
    category: Optional[str] = None,
    q:        Optional[str] = None,
    fmt:      str = "csv",
    limit:    int = 50_000,
) -> Response:
    """
    Export SystemAlert rows that match the given filters.

    Parameters
    ----------
    severity : filter by severity (low / medium / high / critical)
    status   : filter by status (open / acknowledged / resolved / email_sent)
    category : filter by alert category (Database / Timeout / …)
    q        : keyword substring match on message
    fmt      : 'csv' or 'excel'
    limit    : maximum rows exported (safety cap)

    Returns
    -------
    Flask ``Response`` — triggers a browser file download.
    """
    from modules.models import SystemAlert

    query = SystemAlert.query

    if severity:
        query = query.filter(SystemAlert.severity == severity.lower())
    if status:
        query = query.filter(SystemAlert.status == status.lower())
    if category:
        query = query.filter(SystemAlert.category == category)
    if q:
        query = query.filter(SystemAlert.message.ilike(f"%{q}%"))

    rows = query.order_by(SystemAlert.created_at.desc()).limit(limit).all()

    if not rows:
        df = pd.DataFrame(columns=[
            "id", "log_id", "log_file_id", "alert_type", "category",
            "severity", "message", "source_file", "status",
            "sent_at", "created_at",
        ])
    else:
        df = pd.DataFrame([
            {
                "id":          r.id,
                "log_id":      r.log_id,
                "log_file_id": r.log_file_id,
                "alert_type":  r.alert_type,
                "category":    r.category,
                "severity":    r.severity,
                "message":     r.message,
                "source_file": r.source_file,
                "status":      r.status,
                "sent_at":     r.sent_at.strftime("%Y-%m-%d %H:%M:%S") if r.sent_at else "",
                "created_at":  r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for r in rows
        ])

    parts = ["alerts"]
    if severity:
        parts.append(severity.lower())
    if category:
        safe_cat = "".join(c if c.isalnum() else "_" for c in category)
        parts.append(safe_cat)
    if status:
        parts.append(status.lower())
    parts.append(_utc_stamp())

    base_name = "_".join(parts)
    return _best_response(df, base_name, fmt, sheet_name="Alerts")


# ── Full system summary export ─────────────────────────────────────────────────

def export_summary(fmt: str = "csv") -> Response:
    """
    Export a multi-section system summary:
      Sheet 1 (or CSV section) — Log level counts per source file
      Sheet 2                  — Alert counts by category and severity
      Sheet 3                  — Top 20 most recent critical/error entries

    For CSV, the three sections are separated by blank lines and section headers.
    For Excel, each section gets its own worksheet.
    """
    from sqlalchemy import func
    from extensions import db
    from modules.models import ParsedLog, SystemAlert

    # ── Section 1: Log counts by source file + level ─────────────────────
    level_rows = (
        db.session.query(
            ParsedLog.source_file,
            ParsedLog.level,
            func.count(ParsedLog.id).label("count"),
        )
        .group_by(ParsedLog.source_file, ParsedLog.level)
        .order_by(ParsedLog.source_file, ParsedLog.level)
        .all()
    )

    if level_rows:
        df_levels_raw = pd.DataFrame(level_rows, columns=["source_file", "level", "count"])
        df_logs = df_levels_raw.pivot_table(
            index="source_file",
            columns="level",
            values="count",
            fill_value=0,
        ).reset_index()
        df_logs.columns.name = None
        # Ensure all standard levels are present
        for lvl in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            if lvl not in df_logs.columns:
                df_logs[lvl] = 0
        col_order = ["source_file", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        df_logs = df_logs[[c for c in col_order if c in df_logs.columns]]
        df_logs["total"] = df_logs.select_dtypes("number").sum(axis=1)
    else:
        df_logs = pd.DataFrame(
            columns=["source_file", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "total"]
        )

    # ── Section 2: Alert counts by category + severity ────────────────────
    alert_rows = (
        db.session.query(
            SystemAlert.category,
            SystemAlert.severity,
            func.count(SystemAlert.id).label("count"),
        )
        .group_by(SystemAlert.category, SystemAlert.severity)
        .order_by(SystemAlert.category, SystemAlert.severity)
        .all()
    )

    if alert_rows:
        df_alerts_raw = pd.DataFrame(alert_rows, columns=["category", "severity", "count"])
        df_alerts = df_alerts_raw.pivot_table(
            index="category",
            columns="severity",
            values="count",
            fill_value=0,
        ).reset_index()
        df_alerts.columns.name = None
        for sev in ["low", "medium", "high", "critical"]:
            if sev not in df_alerts.columns:
                df_alerts[sev] = 0
        sev_order = ["category", "low", "medium", "high", "critical"]
        df_alerts = df_alerts[[c for c in sev_order if c in df_alerts.columns]]
        df_alerts["total"] = df_alerts.select_dtypes("number").sum(axis=1)
    else:
        df_alerts = pd.DataFrame(
            columns=["category", "low", "medium", "high", "critical", "total"]
        )

    # ── Section 3: Top 20 most recent critical/error entries ──────────────
    top_errors = (
        ParsedLog.query
        .filter(ParsedLog.level.in_(["CRITICAL", "ERROR"]))
        .order_by(ParsedLog.timestamp.desc())
        .limit(20)
        .all()
    )
    df_top = pd.DataFrame([
        {
            "timestamp":   r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "level":       r.level,
            "severity":    r.severity,
            "message":     r.message,
            "source_file": r.source_file,
        }
        for r in top_errors
    ]) if top_errors else pd.DataFrame(
        columns=["timestamp", "level", "severity", "message", "source_file"]
    )

    base_name = f"summary_{_utc_stamp()}"

    if fmt == "excel":
        try:
            import openpyxl  # noqa: F401
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_logs.to_excel(writer,   index=False, sheet_name="Log Counts")
                df_alerts.to_excel(writer, index=False, sheet_name="Alert Counts")
                df_top.to_excel(writer,    index=False, sheet_name="Top Errors")
            return Response(
                buf.getvalue(),
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition": f'attachment; filename="{base_name}.xlsx"',
                },
            )
        except ImportError:
            log.warning("openpyxl not installed — falling back to CSV for summary")

    # CSV fallback — three sections in one file separated by blank lines
    buf = io.StringIO()
    buf.write("# Smart Log Monitoring — System Summary\n")
    buf.write(f"# Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")

    buf.write("## SECTION 1: Log Counts by Source File\n")
    df_logs.to_csv(buf, index=False, encoding="utf-8-sig")

    buf.write("\n## SECTION 2: Alert Counts by Category\n")
    df_alerts.to_csv(buf, index=False, encoding="utf-8-sig")

    buf.write("\n## SECTION 3: Top 20 Recent Critical / Error Entries\n")
    df_top.to_csv(buf, index=False, encoding="utf-8-sig")

    csv_bytes = buf.getvalue().encode("utf-8-sig")
    return Response(
        csv_bytes,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{base_name}.csv"',
            "Content-Length": str(len(csv_bytes)),
        },
    )
