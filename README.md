# Smart Log Monitoring & Alert System

A production-ready web application built with Flask for uploading, parsing,
monitoring, and analysing application log files in real time.

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Technology Stack](#technology-stack)
4. [Folder Structure](#folder-structure)
5. [Installation](#installation)
6. [Configuration](#configuration)
7. [Usage](#usage)
8. [Log Format](#log-format)
9. [User Roles](#user-roles)
10. [API Reference](#api-reference)
11. [Email Alerts](#email-alerts)
12. [Running in Production](#running-in-production)

---

## Overview

Smart Log Monitor ingests `.log` and `.txt` files, extracts structured data
from each line, detects critical patterns (database failures, timeouts,
authentication failures, server overloads), and fires alerts with configurable
email notifications.  A live-monitoring mode watches files on disk and surfaces
new lines in the browser within seconds — no page refresh required.

---

## Features

| Category            | What's included                                                    |
|---------------------|--------------------------------------------------------------------|
| **Upload & Parse**  | Drag-and-drop upload; strict and multi-format fallback parsers     |
| **Dashboard**       | Live stat cards, Chart.js doughnut + line + bar charts             |
| **Filter & Search** | Filter by level, source file, keyword — all filters composable     |
| **Pattern Alerts**  | 11 regex rules across 6 categories; severity LOW → CRITICAL        |
| **Email Alerts**    | Optional SMTP notifications for HIGH / CRITICAL alerts             |
| **Live Monitor**    | Watchdog-based tail; new lines appear in the UI within 3 seconds   |
| **Export**          | CSV and Excel (.xlsx) download for logs, alerts, and summary       |
| **Authentication**  | Session-based login; admin and viewer roles                        |
| **User Management** | Admin can create, edit, disable, and delete user accounts          |
| **REST API**        | JSON endpoints for stats, charts, alerts, and monitor status       |

---

## Technology Stack

| Layer          | Library / Tool                         |
|----------------|----------------------------------------|
| Web framework  | Flask 3.x                              |
| ORM            | Flask-SQLAlchemy 3.x + SQLAlchemy 2.x  |
| Database       | SQLite (file-based, zero configuration)|
| File monitoring| watchdog 6.x                           |
| Data export    | pandas 2.x + openpyxl 3.x             |
| Frontend       | Bootstrap 5.3, Bootstrap Icons, Chart.js 4.x |
| Auth           | werkzeug `generate_password_hash` / `check_password_hash` |
| Python         | 3.10+                                  |

---

## Folder Structure

```
smart_log_monitor/
│
├── app.py                      # Application factory & entry point
├── config.py                   # Environment-based configuration
├── extensions.py               # Shared Flask-SQLAlchemy instance
├── requirements.txt            # Python dependencies
├── README.md
│
├── modules/
│   ├── __init__.py
│   ├── models.py               # SQLAlchemy ORM models
│   ├── auth.py                 # Authentication, decorators, user management
│   ├── parser.py               # Strict-format log parser (primary)
│   ├── log_parser.py           # Multi-format fallback parser (legacy)
│   ├── alerts.py               # Pattern detection & alert engine
│   ├── monitor.py              # Real-time watchdog file monitor
│   ├── export.py               # CSV / Excel export engine
│   └── routes.py               # All Flask route handlers (main_bp, api_bp)
│
├── templates/
│   ├── base.html               # Master layout with navbar
│   ├── login.html              # Authentication page
│   ├── home.html               # Public landing page
│   ├── dashboard.html          # Main dashboard with charts
│   ├── upload.html             # File upload page
│   ├── logs.html               # Uploaded files list
│   ├── log_detail.html         # Legacy log entry viewer
│   ├── parsed_results.html     # Strict-format entry viewer
│   ├── alerts.html             # Alert centre with filters
│   ├── monitor.html            # Live monitoring page
│   ├── admin_users.html        # User management list
│   ├── admin_user_form.html    # Create / edit user form
│   └── 403.html                # Access-denied page
│
├── static/
│   ├── css/style.css           # Custom dark-theme styles
│   └── js/
│       ├── main.js             # Global utilities (alert badge, tab sync)
│       ├── charts.js           # Chart.js dashboard charts
│       └── live_feed.js        # Real-time live log feed polling
│
├── uploads/                    # Uploaded log files (auto-created)
└── instance/
    └── logs.db                 # SQLite database (auto-created)
```

---

## Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/your-org/smart-log-monitor.git
cd smart-log-monitor

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the development server
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

The SQLite database (`instance/logs.db`) and the `uploads/` folder are created
automatically on first run.

### Default credentials

| Username | Password  | Role  |
|----------|-----------|-------|
| `admin`  | `admin123`| Admin |

**Change the default password immediately** — see [Configuration](#configuration).

---

## Configuration

All settings are read from environment variables.  Create a `.env` file in the
project root (loaded automatically by `python-dotenv`):

```dotenv
# .env  —  never commit this file to version control

# Required in production
SECRET_KEY=change-me-to-a-long-random-string

# Override default admin credentials (used only on first run)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=my-secure-password

# Database (default: sqlite in instance/)
DATABASE_URL=sqlite:///instance/logs.db

# Enable email alerts
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_FROM=monitor@example.com
ALERT_EMAIL_TO=oncall@example.com
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=monitor@example.com
ALERT_SMTP_PASSWORD=app-password-here
ALERT_EMAIL_MIN_SEVERITY=high    # low | medium | high | critical
```

### Environment selection

```bash
# Development (default) — debug mode, hot reload
FLASK_ENV=development python app.py

# Production
FLASK_ENV=production python app.py
```

---

## Usage

### 1. Upload a log file

Navigate to **Upload Log File** in the navbar.  Drop a `.log` or `.txt` file
(max 16 MB) onto the upload zone.  The strict parser runs first; if no lines
match, the multi-format fallback parser is used automatically.

### 2. View the dashboard

The dashboard shows:
- Stat cards — total logs, INFO / WARNING / ERROR / CRITICAL counts, open alerts
- **Log Count by Level** doughnut chart
- **Error & Warning Trend** line chart with 7 / 14 / 30 / 60-day switcher
- **Level Breakdown** horizontal bar chart
- Recent alerts panel
- Full filterable and searchable log table

### 3. Filter and export logs

Use the filter bar to narrow by level, source file, or keyword.  The **Export**
dropdown (top-right of the log table) downloads the current view as CSV or
Excel.

### 4. Manage alerts

Navigate to **Alerts** to see all pattern-matched alerts.  Filter by severity,
status, category, or keyword.  Acknowledge or resolve individual alerts, or
resolve all open alerts in one click.

### 5. Real-time monitoring

Navigate to **Live Monitor**.  Click **Start** next to an uploaded file.  The
system watches the file on disk; new lines appear in the live feed within
3 seconds of being appended.

Test it from the terminal:
```bash
echo "2026-05-08 12:00:00 ERROR  Something went wrong" >> uploads/your_file.log
```

### 6. Export reports

From the **Export** dropdown in the dashboard or alerts page:

| Export             | Format  | Contents                                              |
|--------------------|---------|-------------------------------------------------------|
| Filtered Logs      | CSV / Excel | Current log table view                            |
| Alerts             | CSV / Excel | Current alert table view                          |
| Full Summary       | CSV / Excel | Log counts by file, alert counts by category, top 20 errors |

### 7. User management

Admin users can manage accounts at **Admin → Manage Users**:
- Create new users with `admin` or `viewer` role
- Edit role, password, and active status
- Delete users (cannot delete your own account or the last admin)

---

## Log Format

The primary parser expects lines in this exact format:

```
YYYY-MM-DD HH:MM:SS LEVEL Message
```

Examples:

```
2026-04-13 10:01:12 INFO    Server started on port 5000
2026-04-13 10:03:10 WARNING High memory usage: 87%
2026-04-13 10:04:22 ERROR   Database connection failed after 3 retries
2026-04-13 10:05:00 CRITICAL Disk space below 5% — service halted
```

Valid levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

Lines that do not match are skipped (count reported in the flash message).
Files with zero strict-format matches fall back to the multi-format parser,
which also handles Python `logging`, Apache/Nginx, and plain-text formats.

---

## User Roles

| Permission                 | Admin | Viewer |
|----------------------------|-------|--------|
| View dashboard & charts    | ✅    | ✅     |
| View logs & parsed results | ✅    | ✅     |
| View alerts                | ✅    | ✅     |
| Upload log files           | ✅    | ❌     |
| Start / stop monitoring    | ✅    | ❌     |
| Acknowledge / resolve alerts | ✅  | ❌     |
| Export CSV / Excel         | ✅    | ❌     |
| Manage users               | ✅    | ❌     |
| Delete log files           | ✅    | ❌     |

---

## API Reference

All API endpoints require authentication.  Unauthenticated requests return:

```json
{"error": "Authentication required"}
```

with HTTP status `401`.

| Method | Endpoint                             | Description                         |
|--------|--------------------------------------|-------------------------------------|
| GET    | `/api/stats`                         | Dashboard aggregate statistics      |
| GET    | `/api/logs`                          | List of uploaded log files          |
| GET    | `/api/logs/<id>/parsed`              | Parsed entries for a file           |
| GET    | `/api/logs/<id>/parsed/summary`      | Level + severity counts for a file  |
| GET    | `/api/alerts/unread-count`           | Count of unread alerts              |
| GET    | `/api/alerts/summary`                | Full alert summary with recent list |
| GET    | `/api/charts/level-distribution`     | `{labels, counts}` for doughnut     |
| GET    | `/api/charts/combined-trend?days=30` | `{labels, errors, warnings}` trend  |
| GET    | `/api/charts/error-trend?days=30`    | `{labels, counts}` error trend      |
| GET    | `/api/charts/warning-trend?days=30`  | `{labels, counts}` warning trend    |
| GET    | `/api/monitor/status`                | Active watchdog observers           |
| GET    | `/api/monitor/live-feed?after_id=N`  | New log rows since `after_id`       |
| GET    | `/api/monitor/stats`                 | Per-file monitor summary            |

---

## Email Alerts

Email notifications are **disabled by default**.  To enable:

1. Set `ALERT_EMAIL_ENABLED=true` in your `.env` file
2. Configure `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, and SMTP credentials
3. Set `ALERT_EMAIL_MIN_SEVERITY` to the minimum severity that triggers email
   (`low` | `medium` | `high` | `critical` — default: `high`)

Emails are sent for alerts at or above the minimum severity when a new alert is
created during file upload or live monitoring.

**Gmail users:** create an [App Password](https://support.google.com/accounts/answer/185833)
and use that in `ALERT_SMTP_PASSWORD`.

---

## Running in Production

```bash
# Install gunicorn
pip install gunicorn

# Run with 4 worker processes
gunicorn "app:create_app('production')" \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log
```

Checklist before deploying:

- [ ] Set a strong `SECRET_KEY` (minimum 32 random characters)
- [ ] Change the default admin password via **Admin → Manage Users**
- [ ] Set `SESSION_COOKIE_SECURE=true` if serving over HTTPS
- [ ] Point `DATABASE_URL` to a persistent volume in containerised environments
- [ ] Configure SMTP credentials if email alerts are needed

---

## License

MIT — free to use, modify, and distribute.
