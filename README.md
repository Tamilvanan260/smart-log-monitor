# Smart Log Monitor & Alert System

A full-stack, production-ready **Flask** web application for uploading,
parsing, real-time monitoring, and alerting on structured log files.
Features role-based access control, pattern-based alert detection,
and CSV/Excel export.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Technology Stack](#technology-stack)
4. [Project Structure](#project-structure)
5. [Core Modules](#core-modules)
6. [Database Schema](#database-schema)
7. [API Reference](#api-reference)
8. [Authentication and Authorization](#authentication-and-authorization)
9. [Alert System](#alert-system)
10. [Real-Time Monitoring](#real-time-monitoring)
11. [Export System](#export-system)
12. [Templates](#templates)
13. [Environment Variables](#environment-variables)
14. [Running the Application](#running-the-application)
15. [Deployment](#deployment)
16. [Log Format Reference](#log-format-reference)

---

## Project Overview

Smart Log Monitor is a web-based log analysis and monitoring platform
designed to ingest structured log files, detect anomalies through regex
pattern matching, monitor live files in real-time, and send email
notifications for critical issues.

### Key Capabilities

| Capability | Description |
|---|---|
| **File Upload & Parse** | Upload `.log` / `.txt` files up to 16 MB; parsed with strict or fallback parser |
| **Pattern-Based Alerting** | 10+ regex rules: Database, Timeout, Auth, Server, Network, Storage |
| **Real-Time Monitoring** | Tail-based file watching using the `watchdog` library |
| **Role-Based Access** | Two roles: `admin` (full access) and `viewer` (read-only) |
| **Interactive Dashboard** | Live charts, log table with search/filter/pagination |
| **Export** | Download log data and alerts as CSV or Excel (.xlsx) |
| **Email Notifications** | SMTP alerts for CRITICAL and HIGH severity events |

---

## Architecture Diagram

```
Browser (User)
    |
    v
+--------------------------------------------------------------+
|                     Flask Application                        |
|                                                              |
|  +-----------+   +-----------+   +------------------+       |
|  |  auth_bp  |   |  main_bp  |   |     api_bp       |       |
|  |  /login   |   | /dashboard|   |  /api/stats      |       |
|  |  /logout  |   |  /upload  |   |  /api/logs       |       |
|  | /admin/.. |   |  /alerts  |   |  /api/charts/... |       |
|  +-----+-----+   +-----+-----+   +--------+---------+       |
|        |               |                   |                 |
|        +---------------+-------------------+                 |
|                        |                                      |
|  +----------+  +-------+-------+  +--------------------+     |
|  | auth.py  |  | parser.py     |  | alerts.py          |     |
|  |          |  | log_parser.py |  | monitor.py         |     |
|  |          |  | export.py     |  |                    |     |
|  +----------+  +-------+-------+  +----------+---------+     |
|                        |                      |              |
|               +--------+------+    +----------+-----------+  |
|               | SQLAlchemy    |    | watchdog Observer    |  |
|               |   (ORM)       |    | (Background Thread)  |  |
|               +--------+------+    +---------------------+   |
|                        |                                      |
+------------------------|--------------------------------------+
                         |
                 +-------+------+
                 |  SQLite DB   |
                 | (logs.db)    |
                 +--------------+
```

---

## Technology Stack

### Backend

| Library | Version | Purpose |
|---|---|---|
| **Flask** | 3.0.3 | Web framework (WSGI) |
| **Flask-SQLAlchemy** | 3.1.1 | ORM for database operations |
| **SQLAlchemy** | 2.0.30 | SQL toolkit and query engine |
| **Werkzeug** | 3.0.3 | WSGI utilities, password hashing |
| **watchdog** | 6.0.0 | Real-time filesystem event monitoring |
| **pandas** | 2.3.3 | DataFrame-based export (CSV / Excel) |
| **openpyxl** | optional | Excel (.xlsx) write support |
| **gunicorn** | 25.1.0 | WSGI production server |
| **python-dotenv** | 1.0.1 | Load `.env` environment variables |

### Frontend

| Technology | Purpose |
|---|---|
| **Jinja2** | Server-side HTML templating |
| **Vanilla CSS** | Custom styles per template |
| **Chart.js** | Interactive bar/line/doughnut charts on dashboard |
| **Vanilla JavaScript** | AJAX calls, UI interactions |

### Storage

| Store | Purpose |
|---|---|
| **SQLite** (`instance/logs.db`) | Default database for all relational data |
| **`uploads/` directory** | Raw uploaded log files (UUID-prefixed on disk) |

---

## Project Structure

```
smart_log_monitor/
+-- app.py                    # Application factory -- create_app()
+-- config.py                 # Config classes (Dev / Prod / Test)
+-- extensions.py             # Shared SQLAlchemy instance (db)
+-- Procfile                  # Heroku / Railway deployment declaration
+-- runtime.txt               # Python runtime version pin
+-- requirements.txt          # Full dependency lockfile
|
+-- modules/
+--   __init__.py             # Package marker
+--   models.py               # ORM models: User, LogFile, ParsedLog, WatchedFile, SystemAlert
+--   auth.py                 # Session auth: decorators, login/logout, user CRUD
+--   parser.py               # Strict-format log parser (primary)
+--   log_parser.py           # Legacy multi-format fallback parser
+--   alerts.py               # Pattern-based alert detection engine
+--   monitor.py              # Real-time watchdog-based file monitor
+--   export.py               # CSV/Excel export engine (pandas)
+--   routes.py               # All Flask Blueprints and route handlers
|
+-- templates/
+--   base.html               # Master layout (navbar, flash messages)
+--   home.html               # Landing page
+--   login.html              # Login form
+--   dashboard.html          # Main analytics view with charts
+--   upload.html             # File upload page
+--   logs.html               # Uploaded files list
+--   log_detail.html         # Legacy LogEntry viewer
+--   parsed_results.html     # ParsedLog per-file detail view
+--   alerts.html             # Alert centre
+--   monitor.html            # Real-time monitor control panel
+--   admin_users.html        # User management list
+--   admin_user_form.html    # Create/Edit user form
+--   403.html                # Forbidden error page
|
+-- static/
+--   css/                    # Per-page stylesheets
+--   js/                     # Per-page JavaScript files
|
+-- uploads/                  # Runtime: uploaded log files stored here
+-- instance/
+--   logs.db                 # Runtime: SQLite database (auto-created)
```

---

## Core Modules

---

### `app.py` -- Application Factory

**Pattern:** Flask Application Factory

#### `create_app(env: str = "default") -> Flask`

Builds and returns a fully configured Flask app in 7 steps:

| Step | Action |
|---|---|
| 1 | Load config class from `config_map[env]` |
| 2 | Create `uploads/` and `instance/` directories |
| 3 | Initialize `db` (Flask-SQLAlchemy) via `db.init_app(app)` |
| 4 | Register blueprints: `main_bp`, `api_bp`, `auth_bp` |
| 5 | Register context processor `inject_template_globals` |
| 6 | Register Jinja2 `highlight` filter |
| 7 | `db.create_all()` then seed default admin account |

#### `inject_template_globals()` -- Context Processor

Automatically injects into every Jinja2 template:

- `current_user` -- logged-in `User` ORM object or `None`
- `unread_alert_count` -- integer for the navbar badge

#### `highlight(text, term)` -- Jinja2 Filter

Wraps all occurrences of `term` in `<mark class="search-highlight">` tags.
XSS-safe via `markupsafe.escape`. Used in templates as:
```jinja
{{ entry.message | highlight(search_query) }}
```

---

### `config.py` -- Configuration

Three config classes all inherit from base `Config`:

| Class | DEBUG | TESTING | Database |
|---|---|---|---|
| `DevelopmentConfig` | `True` | `False` | `instance/logs.db` (SQLite) |
| `ProductionConfig` | `False` | `False` | `DATABASE_URL` env var |
| `TestingConfig` | -- | `True` | `/tmp/test_smart_log_monitor.db` |

#### Key Config Settings

| Setting | Default | Description |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key-...` | Flask session signing key |
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///instance/logs.db` | Database URL |
| `UPLOAD_FOLDER` | `./uploads` | Uploaded files directory |
| `MAX_CONTENT_LENGTH` | `16 MB` | Upload size hard cap |
| `ALLOWED_EXTENSIONS` | `{"log", "txt"}` | Permitted file extensions |
| `DEFAULT_ADMIN_USERNAME` | `admin` | Auto-seeded on first run |
| `DEFAULT_ADMIN_PASSWORD` | `admin123` | Auto-seeded on first run |
| `ALERT_EMAIL_ENABLED` | `False` | Email alert master switch |
| `PERMANENT_SESSION_LIFETIME` | `604800 s (7 days)` | Session expiry duration |
| `SESSION_COOKIE_HTTPONLY` | `True` | JS cannot read session cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` | CSRF mitigation |

---

### `extensions.py` -- Flask Extensions

Instantiates Flask extensions before `create_app()` to avoid circular imports.

```python
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()   # bound to app via db.init_app(app) in app.py
```

All modules import `db` here: `from extensions import db`

---

### `modules/models.py` -- Database Models

Seven SQLAlchemy ORM models:

#### `User` -- Table: `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | Integer | PK, auto-increment |
| `username` | String(80) | NOT NULL, UNIQUE, indexed |
| `password_hash` | String(256) | NOT NULL |
| `role` | String(20) | NOT NULL, default='viewer' |
| `is_active` | Boolean | NOT NULL, default=True |
| `created_at` | DateTime | default=utcnow |
| `last_login_at` | DateTime | nullable |

**Methods:**

```python
user.set_password("plaintext")    # -> None  -- hashes and stores
user.check_password("plaintext")  # -> bool  -- constant-time compare
user.is_admin                     # @property -> bool
user.to_dict()                    # -> dict  -- JSON-serializable
```

#### `LogFile` -- Table: `log_files`

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `filename` | String(255) | UUID-prefixed disk name |
| `original_name` | String(255) | User-facing filename |
| `file_size` | Integer | Size in bytes |
| `uploaded_at` | DateTime | Upload timestamp |
| `status` | String(50) | `pending` / `analyzed` / `error` |

**Relationships (cascade delete):** `entries`, `parsed_logs`, `watched_file`

#### `ParsedLog` -- Table: `parsed_logs`

| Column | Type | Indexed | Description |
|---|---|---|---|
| `id` | Integer PK | no | Auto-increment |
| `log_file_id` | Integer FK | yes | Parent LogFile (nullable) |
| `timestamp` | DateTime | yes | Log event datetime |
| `level` | String(20) | yes | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `message` | Text | no | Log body, max 2000 chars |
| `source_file` | String(255) | yes | Original filename (denormalized) |
| `severity` | String(20) | no | low / medium / high / critical |
| `created_at` | DateTime | no | Row insertion time (UTC) |

**Class Methods:**

```python
ParsedLog.level_counts_for_file(log_file_id)    # -> {level: count}
ParsedLog.severity_counts_for_file(log_file_id) # -> {severity: count}
```

#### `WatchedFile` -- Table: `watched_files`

| Column | Type | Description |
|---|---|---|
| `log_file_id` | Integer FK | One-to-one with LogFile (unique, indexed) |
| `abs_path` | String(512) | Full disk path for watchdog |
| `source_filename` | String(255) | Display name |
| `last_offset` | Integer | Byte position last processed (idempotency key) |
| `lines_processed` | Integer | Running count of lines seen |
| `is_active` | Boolean | False when monitoring stopped |
| `last_seen_at` | DateTime | Last modification event timestamp |
| `started_at` | DateTime | When monitoring began |

#### `SystemAlert` -- Table: `system_alerts`

| Column | Type | Indexed | Description |
|---|---|---|---|
| `id` | Integer PK | no | Auto-increment |
| `log_id` | Integer FK | yes | ParsedLog that triggered this alert |
| `log_file_id` | Integer FK | yes | Parent LogFile |
| `alert_type` | String(80) | yes | Machine-readable rule name |
| `category` | String(50) | yes | Database / Timeout / Auth / Server / ... |
| `severity` | String(20) | yes | low / medium / high / critical |
| `message` | Text | no | Truncated log body with rule label prefix |
| `source_file` | String(255) | no | Original filename (denormalized) |
| `status` | String(30) | yes | open / acknowledged / resolved / email_sent |
| `is_read` | Boolean | no | Unread flag for navbar badge |
| `sent_at` | DateTime | no | Email dispatch timestamp |
| `created_at` | DateTime | yes | Row insertion time (UTC) |

**Class Methods:**

```python
SystemAlert.unread_count()   # -> int  fast count for navbar badge
SystemAlert.mark_all_read()  # -> None  marks all unread as read
```

#### `LogEntry` (legacy) -- Table: `log_entries`

Kept for backward compatibility. New code always uses `ParsedLog`.

#### `Alert` (legacy) -- Table: `alerts`

Kept for backward compatibility. New code always uses `SystemAlert`.

---

### `modules/auth.py` -- Authentication

Session-based authentication using Flask's signed-cookie session.

#### Session Structure

```python
session["user_id"]  : int   # User.id
session["username"] : str   # For display (avoids extra DB hit)
session["role"]     : str   # For fast role checks
```

All three keys must be present for the session to be considered valid.

#### Core Functions

| Function | Signature | Description |
|---|---|---|
| `login_user` | `(user) -> None` | Writes user to session, updates `last_login_at` |
| `logout_user` | `() -> None` | Clears the Flask session completely |
| `get_current_user` | `() -> User or None` | Returns User ORM object; cached in `g` per-request |
| `is_logged_in` | `() -> bool` | True if current request has valid session |
| `is_admin` | `() -> bool` | True if logged-in user has admin role |

#### Route Decorators

| Decorator | Used On | Behavior |
|---|---|---|
| `@login_required` | HTML routes | Redirects to `/login` if unauthenticated |
| `@admin_required` | HTML routes | Redirects to `/login` or renders 403 for non-admins |
| `@api_login_required` | API routes | Returns `{"error": "Authentication required"}` + 401 |
| `@api_admin_required` | API routes | Returns 401 or 403 JSON |

#### `auth_bp` Blueprint Routes

| Method | URL | Access | Description |
|---|---|---|---|
| `GET/POST` | `/login` | Public | Login form and credential validation |
| `POST` | `/logout` | Login | Logout (POST-only prevents CSRF logout via links) |
| `GET` | `/admin/users` | Admin | List all users |
| `GET/POST` | `/admin/users/create` | Admin | Create a new user |
| `GET/POST` | `/admin/users/<id>/edit` | Admin | Edit an existing user |
| `POST` | `/admin/users/<id>/delete` | Admin | Delete a user |

#### Security Safeguards

- Cannot delete your own account
- Cannot demote or delete the last active admin
- `?next=` redirect validated as relative-only path (prevents open redirect)
- Session keys removed before re-writing on login (prevents session fixation)
- Role validated against DB on every `get_current_user()` call

#### `seed_default_admin(app)`

Creates the default admin **only if the users table is empty**. Credentials sourced from config/env vars.

---

### `modules/parser.py` -- Log Parser

The primary, strict-format parser.

#### Accepted Log Format

```
YYYY-MM-DD HH:MM:SS LEVEL Message text here
```

Valid examples:
```
2026-04-13 10:01:12 INFO  Server started on port 8080
2026-04-13 10:03:10 WARNING High memory usage: 85%
2026-04-13 10:04:22 ERROR Database connection failed: timeout
2026-04-13 10:05:00 CRITICAL Out of memory -- killing process
```

#### Core Regex

```python
_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"\s+(?P<message>.+)$",
    re.IGNORECASE,
)
```

#### Constants

| Constant | Value | Purpose |
|---|---|---|
| `VALID_LEVELS` | (DEBUG, INFO, WARNING, ERROR, CRITICAL) | Accepted log levels |
| `SEVERITY_MAP` | DEBUG/INFO -> low, WARNING -> medium, ERROR -> high, CRITICAL -> critical | Level to severity |
| `MAX_MESSAGE_LEN` | 2000 | Message truncation limit (chars) |
| `MAX_FILE_BYTES` | 16777216 | Upload size cap (16 MB) |
| `ALLOWED_EXTENSIONS` | frozenset({"log", "txt"}) | Accepted file extensions |

#### Data Classes

```python
@dataclass
class ParsedLine:
    line_number: int       # 1-based position in file
    timestamp:   datetime  # parsed event datetime
    level:       str       # normalized uppercase
    message:     str       # capped at MAX_MESSAGE_LEN
    severity:    str       # low / medium / high / critical
    raw:         str       # original text for auditing

@dataclass
class ParseResult:
    source_file:   str
    parsed:        list   # list[ParsedLine] -- matched lines
    skipped_lines: list   # list[tuple[int, str]] -- (line_num, raw_text)
    errors:        list   # list[str] -- file-level read errors

    # Computed properties:
    total_lines:   int    # parsed + skipped count
    has_errors:    bool   # True if any file-level error
    counts:        dict   # {level: count}
    success_rate:  float  # % of non-blank lines matched
```

#### Public API

```python
# Validate before parsing -- raises FileValidationError on failure
validate_upload(filename: str, file_size: int) -> None

# Parse an entire file -- zero side-effects, never touches the DB
parse_file(filepath: str, source_filename: str) -> ParseResult

# Persist parsed lines to DB (bulk insert)
# Caller is responsible for db.session.commit()
store_parsed_result(
    parse_result: ParseResult,
    log_file_id: int,
    source_file: str,
) -> int  # number of rows inserted
```

**Design Principles:** Zero side-effects, always returns ParseResult, non-blank unmatched lines recorded in `skipped_lines`, caller manages DB transactions.

---

### `modules/log_parser.py` -- Legacy Fallback Parser

Multi-format parser used automatically when the strict parser finds zero matches.

```python
parse_and_store(log_file: LogFile, filepath: str) -> dict[str, int]
# Returns {level: count} dict
# Writes LogEntry rows directly to the database
```

---

### `modules/alerts.py` -- Alert Detection Engine

A pure pattern-matching engine. No database writes inside this module; all inserts done by callers.

#### Severity Constants

```python
class Severity:
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"
    WEIGHT = {LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}
```

#### Alert Status Constants

```python
class AlertStatus:
    OPEN         = "open"           # newly created, not yet seen
    ACKNOWLEDGED = "acknowledged"   # seen by a human
    RESOLVED     = "resolved"       # manually closed
    EMAIL_SENT   = "email_sent"     # email notification dispatched
```

#### Pattern Registry

All patterns stored in `PATTERNS: list[_Pattern]`:

| Pattern Name | Label | Severity | Category |
|---|---|---|---|
| `db_connection_failed` | Database Connection Failed | CRITICAL | Database |
| `db_query_error` | Database Query Error | HIGH | Database |
| `request_timeout` | Request Timeout | HIGH | Timeout |
| `service_timeout` | Service Timeout | MEDIUM | Timeout |
| `auth_failed` | Authentication Failed | HIGH | Authentication |
| `auth_brute_force` | Possible Brute-Force Attack | CRITICAL | Authentication |
| `server_overload` | Server Overload | CRITICAL | Server |
| `high_resource_usage` | High Resource Usage | HIGH | Server |
| `service_crashed` | Service Crash / Restart | CRITICAL | Server |
| `network_error` | Network Error | MEDIUM | Network |
| `disk_error` | Disk / Storage Error | HIGH | Storage |

Each `_Pattern` dataclass holds a compiled `re.Pattern` with `re.IGNORECASE`.

#### Core Detection Functions

```python
# Scan message against ALL patterns
detect_patterns(message: str) -> list[_Pattern]
# Returns patterns sorted by descending severity (CRITICAL first)

# Build SystemAlert ORM instances (no DB writes)
build_alert_from_log(
    parsed_log_id: int,
    log_file_id: Optional[int],
    message: str,
    log_level: str,
    source_file: str,
) -> list  # list[SystemAlert] ready for session.add()

# Evaluate + persist ONE ParsedLog entry (real-time monitor)
evaluate_entry(parsed_log, flask_app) -> int  # count created

# Evaluate + persist a BATCH of ParsedLog ids (post-upload)
evaluate_batch(parsed_log_ids: list[int], flask_app) -> int
```

**De-duplication:** One `SystemAlert` per category per log message (highest severity wins).

**Generic Fallback:** For ERROR/CRITICAL lines matching no pattern, a `generic_error` / `General` alert is still raised.

#### `AlertSummary` Dataclass

```python
@dataclass
class AlertSummary:
    total, critical, high, medium, low: int
    open_count, unread: int
    by_category: dict   # {"Database": 5, ...}
    recent: list        # last N SystemAlert rows

get_alert_summary(limit_recent: int = 10) -> AlertSummary
```

#### `send_email_alert(alert, flask_app) -> bool`

Sends multi-part (plain text + HTML) SMTP email for CRITICAL/HIGH alerts.
Returns `True` if sent, `False` if disabled or failed.
Updates `alert.status = AlertStatus.EMAIL_SENT` on success.
Caller must call `db.session.commit()` after.

---

### `modules/monitor.py` -- Real-Time Monitor

Real-time log file tailing using `watchdog`. One background daemon thread per monitored file.

#### Threading Model

```
Main Thread (Flask request)
    |
    +-- LogFileMonitor.start() --> spawns Observer Thread (daemon)
    |                                     |
    |                           _LogEventHandler.on_modified()
    |                                     |
    |                           _do_process() [fresh app.app_context()]
    |                              +-- Read last_offset from DB
    |                              +-- file.seek(last_offset)
    |                              +-- Parse new lines with _LINE_RE
    |                              +-- Bulk insert ParsedLog rows
    |                              +-- Update WatchedFile.last_offset
```

Each DB write uses a fresh `app.app_context()` to avoid shared-session contamination.

#### `LogFileMonitor` -- Public API (all classmethods)

```python
LogFileMonitor.start(flask_app, abs_path, log_file_id, source_filename) -> bool
# True on success, False if already monitored or file not found

LogFileMonitor.stop(log_file_id: int) -> bool
# True if was running and now stopped, False if not found

LogFileMonitor.stop_all() -> int  # count of monitors stopped

LogFileMonitor.is_active(log_file_id: int) -> bool

LogFileMonitor.list_active() -> list[dict]
# [{log_file_id, watch_path, observer_alive}, ...]
```

**Idempotency:** `last_offset` is the source of truth. seek + read + update in one atomic transaction.

**Truncation:** Detected when `file_size < last_offset`; resets offset to 0 automatically.

---

### `modules/export.py` -- Export Engine

Generates downloadable files using pandas DataFrames. Nothing written to disk -- streamed via `io.BytesIO`.

#### Supported Formats

| Format | MIME Type | Library |
|---|---|---|
| CSV | `text/csv; charset=utf-8` | Built-in, UTF-8-SIG (BOM for Excel compat) |
| Excel (.xlsx) | `application/vnd.openxmlformats-...` | `openpyxl` (optional, falls back to CSV) |

#### Public Functions

```python
export_logs(level=None, source=None, q=None, fmt="csv", limit=50_000) -> Response
export_alerts(severity=None, status=None, category=None, q=None, fmt="csv") -> Response
export_summary(fmt="csv") -> Response  # 3-section report
```

**Summary Sections:** Log Counts (per-file pivot), Alert Counts (per-category pivot), Top Errors (20 most recent CRITICAL/ERROR rows).

---

### `modules/routes.py` -- Routes & Blueprints

Two Flask Blueprints: `main_bp` (HTML pages) and `api_bp` (JSON, url_prefix=/api).

#### HTML Routes (`main_bp`)

| Method | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/` | Public | Home / landing page |
| `GET` | `/dashboard` | Login | Main dashboard with charts and log table |
| `GET/POST` | `/upload` | Login | File upload page |
| `GET` | `/logs` | Login | Uploaded files list (paginated) |
| `GET` | `/logs/<id>` | Login | Legacy LogEntry viewer |
| `GET` | `/logs/<id>/parsed` | Login | ParsedLog per-file detail view |
| `POST` | `/logs/<id>/delete` | Admin | Delete file and all DB records |
| `GET` | `/alerts` | Login | Alert centre (marks all alerts as read) |
| `POST` | `/alerts/<id>/acknowledge` | Admin | Acknowledge a single alert |
| `POST` | `/alerts/<id>/resolve` | Admin | Resolve a single alert |
| `POST` | `/alerts/resolve-all` | Admin | Bulk-resolve all open alerts |
| `GET` | `/export/logs` | Admin | Download log CSV/Excel |
| `GET` | `/export/alerts` | Admin | Download alerts CSV/Excel |
| `GET` | `/export/summary` | Admin | Download system summary report |
| `GET` | `/monitor` | Admin | Real-time monitor control panel |

#### Upload Flow

```
POST /upload
    +-- 1. Validate file presence + extension (.log or .txt)
    +-- 2. Save to uploads/ with UUID-prefixed name
    +-- 3. validate_upload() -- size / empty checks
    +-- 4. Create LogFile record (status=pending)
    +-- 5. parse_file() -- strict-format parser
    |         +-- Has read errors?  --> mark status=error, redirect
    |         +-- Has parsed lines? --> store_parsed_result()
    |         |                         evaluate_batch() -> SystemAlerts
    |         |                         mark status=analyzed
    |         +-- Zero matches?    --> fallback to parse_and_store()
    +-- 6. Redirect to dashboard
```

---

## Database Schema

```
+------------+         +------------------+
|   users    |         |    log_files     |
+------------+         +------------------+
| id (PK)    |         | id (PK)          |
| username   |         | filename         |
| pass_hash  |         | original_name    |
| role       |         | file_size        |
| is_active  |         | uploaded_at      |
| created_at |         | status           |
+------------+         +--------+---------+
                                | 1
               +---------------+-----------+
              n|              1|           1|
    +----------+--+   +--------+--+  +-----+----------+
    | log_entries |   | parsed_logs|  | watched_files  |
    | (legacy)    |   +------------+  +----------------+
    +-------------+   | id (PK)    |  | log_file_id    |
                      | log_file_id|  | abs_path       |
                      | timestamp  |  | last_offset    |
                      | level      |  | is_active      |
                      | message    |  | lines_processed|
                      | source_file|  +----------------+
                      | severity   |
                      +------+-----+
                             | 1
                            n|
                     +-------+-----------+
                     |  system_alerts    |
                     +-------------------+
                     | id (PK)           |
                     | log_id (FK)       |
                     | log_file_id (FK)  |
                     | alert_type        |
                     | category          |
                     | severity          |
                     | message           |
                     | status            |
                     | is_read           |
                     | sent_at           |
                     | created_at        |
                     +-------------------+
```

---

## API Reference

All API routes protected by `@api_login_required` or `@api_admin_required`.

### Stats & Alerts

| Method | Endpoint | Auth | Response |
|---|---|---|---|
| `GET` | `/api/stats` | Login | Dashboard statistics dict |
| `GET` | `/api/alerts/unread-count` | Login | `{"unread": N}` |
| `GET` | `/api/alerts/summary` | Login | AlertSummary as JSON |

### Logs

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/logs` | Login | Last 20 uploaded files |
| `GET` | `/api/logs/<id>/entries` | Login | Legacy LogEntry rows |
| `GET` | `/api/logs/<id>/parsed` | Login | ParsedLog rows; `?level=` `?limit=` |
| `GET` | `/api/logs/<id>/parsed/summary` | Login | Level + severity counts |

### Charts

| Method | Endpoint | Query Params | Response Shape |
|---|---|---|---|
| `GET` | `/api/charts/level-distribution` | -- | `{labels, counts}` |
| `GET` | `/api/charts/error-trend` | `?days=30` (max 90) | `{labels, counts}` |
| `GET` | `/api/charts/warning-trend` | `?days=30` (max 90) | `{labels, counts}` |
| `GET` | `/api/charts/combined-trend` | `?days=30` (max 90) | `{labels, errors, warnings}` |

### Monitor (Admin Only)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/monitor/status` | List all active monitors |
| `POST` | `/api/monitor/start/<id>` | Start monitoring a file |
| `POST` | `/api/monitor/stop/<id>` | Stop monitoring a file |

---

## Authentication and Authorization

### Role Matrix

| Feature | Admin | Viewer |
|---|---|---|
| Dashboard | Yes | Yes |
| View Logs | Yes | Yes |
| View Alerts | Yes | Yes |
| Parsed Results | Yes | Yes |
| Upload Files | Yes | Yes |
| Delete Files | Yes | No |
| Monitor (start/stop) | Yes | No |
| Export CSV/Excel | Yes | No |
| Acknowledge/Resolve Alerts | Yes | No |
| Manage Users | Yes | No |

### Password Security

- Hashes via `werkzeug.security.generate_password_hash()` (scrypt by default)
- Compared via constant-time `check_password_hash()`
- Minimum password length: 8 characters (enforced in UI)

---

## Alert System

### Detection Flow

```
ParsedLog row created (after upload or monitor event)
    |
    v
detect_patterns(message) --> list[_Pattern] sorted by descending severity
    |
    +-- Pattern matched?
    |     +-- De-duplicate by category (highest severity per category)
    |           +-- Create SystemAlert ORM objects
    |
    +-- No match but level is ERROR or CRITICAL?
          +-- Create generic_error SystemAlert (category=General)

db.session.add(alerts)
db.session.commit()

For CRITICAL or HIGH severity:
    +-- send_email_alert() if ALERT_EMAIL_ENABLED=True
```

### Alert Lifecycle

```
OPEN  -->  ACKNOWLEDGED  -->  RESOLVED
  +-------------------------------------->  EMAIL_SENT (coexists with status)
```

### Email Configuration

```ini
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_FROM=noreply@yourdomain.com
ALERT_EMAIL_TO=admin@yourdomain.com,ops@yourdomain.com
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=your@gmail.com
ALERT_SMTP_PASSWORD=your-app-password
ALERT_SMTP_TLS=true
ALERT_EMAIL_MIN_SEVERITY=high
```

---

## Real-Time Monitoring

### How It Works

1. User clicks "Start Monitoring" for an uploaded file
2. `LogFileMonitor.start()` is called with the file's disk path
3. A `watchdog.Observer` daemon thread watches the file's parent directory
4. `_LogEventHandler.on_modified()` fires on every filesystem modification event
5. Only events for the exact watched file path are processed
6. New bytes read by seeking to `WatchedFile.last_offset`
7. Lines parsed with the same `_LINE_RE` regex used by `parser.py`
8. Valid lines bulk-inserted as `ParsedLog` rows
9. `WatchedFile.last_offset` updated atomically in the same DB transaction

### Truncation / Log Rotation

Detected when `file_size < last_offset`. `last_offset` reset to 0; next event re-processes from start.

### Stopping a Monitor

`LogFileMonitor.stop(log_file_id)`: calls `observer.stop()` + `observer.join(timeout=5)`, removes from `_REGISTRY`, sets `WatchedFile.is_active = False`.

---

## Export System

### CSV Export

- Encoding: UTF-8-SIG (BOM) for direct Excel compatibility
- No disk writes -- streamed via `io.StringIO` / `io.BytesIO`
- `Content-Disposition: attachment` triggers browser download
- Filename includes filter params and UTC timestamp

Example: `logs_error_server.log_20260716_104532.csv`

### Excel Export

- Requires `openpyxl` package
- Auto-fits column widths (max 60 chars per column)
- Falls back to CSV automatically if `openpyxl` not installed

---

## Templates

All extend `base.html` which provides: navbar, flash messages, and common head tags.

| Template | Route | Auth |
|---|---|---|
| `home.html` | `/` | Public |
| `login.html` | `/login` | Public |
| `dashboard.html` | `/dashboard` | Login |
| `upload.html` | `/upload` | Login |
| `logs.html` | `/logs` | Login |
| `log_detail.html` | `/logs/<id>` | Login |
| `parsed_results.html` | `/logs/<id>/parsed` | Login |
| `alerts.html` | `/alerts` | Login |
| `monitor.html` | `/monitor` | Admin |
| `admin_users.html` | `/admin/users` | Admin |
| `admin_user_form.html` | `/admin/users/create or /edit` | Admin |
| `403.html` | `(auto on 403)` | -- |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `FLASK_ENV` | No | development | `development` / `production` / `testing` |
| `SECRET_KEY` | YES in prod | dev-secret-key-... | Session signing key |
| `DATABASE_URL` | No | SQLite instance/logs.db | SQLAlchemy connection URI |
| `PORT` | No | 5000 | Dev server port |
| `SESSION_COOKIE_SECURE` | No | false | Set `true` when using HTTPS |
| `ADMIN_USERNAME` | No | admin | Default admin username (first run only) |
| `ADMIN_PASSWORD` | No | admin123 | Default admin password (first run only) |
| `ALERT_EMAIL_ENABLED` | No | false | Master switch for email alerts |
| `ALERT_EMAIL_FROM` | No | -- | Sender email address |
| `ALERT_EMAIL_TO` | No | -- | Recipients (comma-separated) |
| `ALERT_SMTP_HOST` | No | smtp.gmail.com | SMTP server hostname |
| `ALERT_SMTP_PORT` | No | 587 | SMTP port |
| `ALERT_SMTP_USER` | No | -- | SMTP authentication username |
| `ALERT_SMTP_PASSWORD` | No | -- | SMTP authentication password |
| `ALERT_SMTP_TLS` | No | true | Enable STARTTLS |
| `ALERT_EMAIL_MIN_SEVERITY` | No | high | Minimum severity for email alerts |

---

## Running the Application

### Development

```bash
# 1. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate    # Windows
# source venv/bin/activate  # Linux/macOS

# 2. Install core dependencies
pip install flask flask-sqlalchemy werkzeug watchdog pandas openpyxl python-dotenv gunicorn

# 3. Run
python app.py
```

Opens at **http://localhost:5000**. Default credentials: `admin` / `admin123`

### With .env File

```ini
FLASK_ENV=development
SECRET_KEY=replace-with-strong-random-string
ADMIN_USERNAME=myadmin
ADMIN_PASSWORD=mysecurepassword123
```

---

## Deployment

### Gunicorn

```bash
gunicorn "app:create_app('production')" \
  --workers 2 \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

> **Note:** Real-time monitoring uses per-worker background daemon threads. Use `--workers 1` for consistent monitor state across requests, or externalize state to Redis/Celery for multi-worker deployments.

### Heroku / Railway

`Procfile`:
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

### Production Checklist

- [ ] Set a strong random `SECRET_KEY`
- [ ] Set `FLASK_ENV=production`
- [ ] Set `SESSION_COOKIE_SECURE=true` (requires HTTPS)
- [ ] Change default admin credentials
- [ ] Configure `DATABASE_URL` (PostgreSQL recommended)
- [ ] Configure SMTP settings for email alerts
- [ ] Mount `UPLOAD_FOLDER` on persistent storage

---

## Log Format Reference

Strict parser accepts:

```
YYYY-MM-DD HH:MM:SS LEVEL Message text
```

| Component | Example | Notes |
|---|---|---|
| Timestamp | `2026-04-13 10:04:22` | `\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}` |
| Level | `ERROR` | DEBUG / INFO / WARNING / ERROR / CRITICAL (case-insensitive) |
| Message | `Database connection failed` | Any text; max 2000 chars stored |

**Example file:**
```
2026-04-13 10:01:12 INFO Server started on port 8080
2026-04-13 10:03:10 WARNING High memory usage detected: 85%
2026-04-13 10:04:22 ERROR Database connection failed: timeout after 30s
2026-04-13 10:05:00 CRITICAL Out of memory -- killing process
```

Lines not matching are counted as `skipped_lines`. If zero lines match, the legacy fallback parser is tried automatically.

---

*Smart Log Monitor & Alert System -- Flask 3.0.3 / SQLAlchemy 2.0.30 / Python 3.10+*
