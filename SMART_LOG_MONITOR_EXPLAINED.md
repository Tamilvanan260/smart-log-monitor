# Smart Log Monitoring & Alert System
## A to Z Project Explanation

> **Live URL:** https://smart-log-monitor-production.up.railway.app  
> **Tech:** Python · Flask · SQLite · Bootstrap · Chart.js · Watchdog · Pandas

---

## 1. What is this Project?

Smart Log Monitor is a **web application** that:

- Takes `.log` or `.txt` files from servers/applications
- Reads every line automatically
- Detects problems like errors, crashes, database failures
- Shows charts and dashboards
- Sends alerts when critical issues are found
- Lets multiple users monitor in real time

### Real World Use Case

```
Your Application runs on a server
        ↓
It generates log files like:
2026-05-09 09:04:22 ERROR  Database connection failed
2026-05-09 09:05:00 CRITICAL Out of memory
        ↓
Upload to Smart Log Monitor
        ↓
System auto-detects the problem
        ↓
Alert generated → You get notified
```
A **log file** is a simple **text file** where an application or system **automatically records everything that happens** while it is running.

---

## Simple Analogy
what is log file ?
Think of it like a **diary** that your application writes automatically:

```
2026-05-09 09:00:01 INFO     App started successfully
2026-05-09 09:01:10 WARNING  Memory usage is high: 80%
2026-05-09 09:02:33 ERROR    Failed to connect to database
2026-05-09 09:03:00 CRITICAL System out of memory — crashed
```

Every line = one event that happened.

---

## Real Life Comparisons

| Real Life | Log File |
|-----------|----------|
| Bank passbook | Records every transaction |
| CCTV footage | Records everything happening |
| Doctor's patient history | Records what happened and when |
| Flight black box | Records everything before a crash |

---

## Log Levels Explained

| Level | Meaning | Example |
|-------|---------|---------|
| `DEBUG` | Developer detail | Cache loaded for user123 |
| `INFO` | Normal activity | User logged in successfully |
| `WARNING` | Small issue, not breaking | Memory at 80% |
| `ERROR` | Something failed | Database connection failed |
| `CRITICAL` | System crashed | Out of memory — process killed |

---

## Who Uses Log Files?

| Person | Why They Need Logs |
|--------|--------------------|
| Web Developer | Find why website is broken |
| Database Admin | Track database errors |
| Security Team | Detect hacking attempts |
| System Admin | Monitor CPU, memory, disk |
| DevOps Engineer | Monitor server health |

---

## Where Log Files Come From

```
Your Application runs
        ↓
Every event gets recorded automatically
        ↓
Saved as  app.log  or  server.log  or  system.log
        ↓
You upload it to Smart Log Monitor
        ↓
System reads, analyses, and alerts you
```

---

## Example — What a Real Log File Looks Like

```
2026-05-09 08:00:01 INFO     Web server started on port 8080
2026-05-09 08:01:12 INFO     User john.doe logged in
2026-05-09 08:02:33 WARNING  Response time slow: 612ms
2026-05-09 08:03:11 ERROR    Database connection failed
2026-05-09 08:04:00 ERROR    Authentication failed: wrong password
2026-05-09 08:05:00 CRITICAL Server out of memory — shutting down
```

---

## One Line Definition

> **A log file is a text file that automatically records what an application does, when it does it, and what goes wrong — so developers can find and fix problems.**

---
---

## 2. Why This Project?

### Problem

- Developers have hundreds of log files
- Manually reading logs is time-consuming
- Critical errors get missed
- No central place to monitor all logs

### Solution

- Upload once → System reads everything
- Auto-detects 11 critical patterns
- Real-time alerts with severity levels
- One dashboard for all logs

---

## 3. Full Tech Stack — Why Each Tool Was Chosen

---

### 3.1 Python 3.10

**Why Python?**
- Simple syntax → easy to maintain
- Best libraries for data processing
- Strong community support
- Ideal for backend + data analysis

**Where used in this project:**
- All backend logic
- File parsing
- Pattern matching
- Database operations

---

### 3.2 Flask (Web Framework)

**Why Flask and not Django?**

| Flask | Django |
|-------|--------|
| Lightweight | Heavy |
| Flexible structure | Fixed structure |
| Easy to learn | Complex for small projects |
| Perfect for this size project | Overkill for this project |

**Where used:**
- Creating all web pages (routes)
- Handling file uploads
- Managing user sessions
- Building REST API endpoints

**Key Flask concepts used:**
```python
# Blueprint — separates code into modules
main_bp = Blueprint("main", __name__)
api_bp  = Blueprint("api",  __name__, url_prefix="/api")
auth_bp = Blueprint("auth", __name__)

# Route — maps URL to function
@main_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# Application Factory Pattern
def create_app(env="default"):
    app = Flask(__name__)
    return app
```

---

### 3.3 SQLite (Database)

**Why SQLite?**
- Zero configuration — no server needed
- File-based — stores as `logs.db`
- Perfect for small to medium projects
- Built into Python

**Why not MySQL or PostgreSQL?**
- No need to install a separate database server
- Easy to deploy anywhere
- Good enough for this project's data size

**Tables created:**

| Table | Purpose |
|-------|---------|
| `users` | Login accounts |
| `log_files` | Uploaded file metadata |
| `parsed_logs` | Each log line parsed |
| `log_entries` | Legacy format lines |
| `system_alerts` | Auto-generated alerts |
| `watched_files` | Real-time monitor tracking |

---

### 3.4 Flask-SQLAlchemy (ORM)

**What is ORM?**
ORM = Object Relational Mapper
- Write Python code instead of SQL queries
- Maps Python classes to database tables

**Why SQLAlchemy?**
- No need to write raw SQL
- Easy to switch databases later
- Prevents SQL injection attacks

**Example:**
```python
# Instead of SQL:
# SELECT * FROM parsed_logs WHERE level = 'ERROR'

# We write Python:
ParsedLog.query.filter_by(level="ERROR").all()
```

**Models defined:**
```python
class ParsedLog(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    timestamp   = db.Column(db.DateTime, nullable=False)
    level       = db.Column(db.String(20), nullable=False)
    message     = db.Column(db.Text, nullable=False)
    source_file = db.Column(db.String(255), nullable=False)
    severity    = db.Column(db.String(20), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
```

---

### 3.5 Werkzeug (Password Security)

**Why Werkzeug?**
- Built into Flask
- Industry-standard password hashing
- Prevents storing plain text passwords

**Methods used:**
```python
from werkzeug.security import generate_password_hash, check_password_hash

# When creating user — hash the password
password_hash = generate_password_hash("admin123")
# Stores: pbkdf2:sha256:600000$... (not the actual password)

# When logging in — check the hash
check_password_hash(stored_hash, "admin123")  # Returns True/False
```

**Why hashing?**
- Even if database is hacked, passwords are safe
- Cannot reverse a hash to get original password

---

### 3.6 Watchdog (Real-Time File Monitoring)

**What is Watchdog?**
- Python library that watches files/folders for changes
- Like a security guard watching your files

**Why Watchdog?**
- Detects when new lines are added to a log file
- Works in the background (separate thread)
- No polling needed — event-driven

**How it works:**
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class LogEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        # This fires automatically when file changes
        # Read new lines and save to database
        self._process_new_lines()

observer = Observer()
observer.schedule(handler, path=watch_dir, recursive=False)
observer.start()  # Runs in background thread
```

**Real-time flow:**
```
Log file gets new line added
        ↓
Watchdog detects file change (within 1 second)
        ↓
Handler reads only NEW lines (from last offset)
        ↓
Parses and saves to database
        ↓
Browser polls every 3 seconds
        ↓
New line appears on screen
```

**Duplicate Prevention:**
```python
# Tracks byte position in file
last_offset = 0

# Only reads from where it left off
file.seek(last_offset)
new_content = file.read()
last_offset = file.tell()  # Save new position
```

---

### 3.7 Pandas (Data Export)

**What is Pandas?**
- Python library for data manipulation
- Like Excel but in Python

**Why Pandas for export?**
- Converts database records to DataFrame
- Exports to CSV or Excel in 2 lines of code
- Handles large datasets efficiently

**How export works:**
```python
import pandas as pd

# Get data from database
rows = ParsedLog.query.filter_by(level="ERROR").all()

# Convert to DataFrame
df = pd.DataFrame([{
    "timestamp": r.timestamp,
    "level":     r.level,
    "message":   r.message,
} for r in rows])

# Export to CSV
df.to_csv("errors.csv", index=False)

# Export to Excel
df.to_excel("errors.xlsx", index=False)
```

---

### 3.8 OpenPyXL (Excel Files)

**Why OpenPyXL?**
- Required by Pandas to write `.xlsx` files
- Auto-fits column widths
- Supports multiple sheets in one file

**Used for:**
- Summary report with 3 sheets:
  - Sheet 1: Log counts by file
  - Sheet 2: Alert counts by category
  - Sheet 3: Top 20 critical errors

---

### 3.9 Bootstrap 5 (Frontend UI)

**Why Bootstrap?**
- Ready-made CSS components
- Responsive — works on mobile and desktop
- Professional look without custom CSS
- Free and open source

**Components used:**
- `navbar` — top navigation bar
- `card` — stat cards and chart containers
- `table` — log entries display
- `badge` — level labels (ERROR, WARNING)
- `modal` — popups
- `dropdown` — export menu
- `pagination` — page navigation
- `alert` — flash messages

---

### 3.10 Bootstrap Icons

**Why Bootstrap Icons?**
- Free icon library
- Works with Bootstrap
- 1800+ icons

**Used for:**
```html
<i class="bi bi-bell-fill"></i>        <!-- Alert bell -->
<i class="bi bi-cloud-upload"></i>     <!-- Upload button -->
<i class="bi bi-speedometer2"></i>     <!-- Dashboard -->
<i class="bi bi-broadcast"></i>        <!-- Live monitor -->
<i class="bi bi-fire"></i>             <!-- Critical alert -->
```

---

### 3.11 Chart.js (Data Visualisation)

**Why Chart.js?**
- Free JavaScript charting library
- Beautiful responsive charts
- Easy to integrate with Flask

**3 Charts built:**

#### Chart 1 — Doughnut Chart (Log Count by Level)
```javascript
new Chart(ctx, {
    type: "doughnut",
    data: {
        labels: ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        datasets: [{ data: [12, 45, 8, 5, 2] }]
    }
})
```

#### Chart 2 — Line Chart (Error & Warning Trend)
```javascript
new Chart(ctx, {
    type: "line",
    data: {
        labels: ["2026-04-01", "2026-04-02", ...],
        datasets: [
            { label: "Errors",   data: [3, 0, 7, ...] },
            { label: "Warnings", data: [1, 2, 0, ...] }
        ]
    }
})
```

#### Chart 3 — Horizontal Bar (Level Breakdown)
```javascript
new Chart(ctx, {
    type: "bar",
    options: { indexAxis: "y" },  // Makes it horizontal
    data: { labels: ["DEBUG","INFO","WARNING","ERROR","CRITICAL"] }
})
```

---

### 3.12 Jinja2 (HTML Templates)

**What is Jinja2?**
- Template engine built into Flask
- Mix Python variables inside HTML

**Why Jinja2?**
- Reuse HTML across pages (base template)
- Display database data in HTML
- Conditional rendering

**Template inheritance used:**
```html
<!-- base.html — master layout -->
<html>
  <body>
    <nav>...</nav>
    {% block content %}{% endblock %}
    <footer>...</footer>
  </body>
</html>

<!-- dashboard.html — extends base -->
{% extends "base.html" %}
{% block content %}
  <h1>Dashboard</h1>
  {% for log in logs %}
    <p>{{ log.message }}</p>
  {% endfor %}
{% endblock %}
```

---

### 3.13 Railway (Cloud Deployment)

**Why Railway?**
- Free hosting for small projects
- Auto-detects Flask and deploys
- Gives HTTPS URL automatically
- No server setup needed

**Deployment flow:**
```
Push code to GitHub
        ↓
Railway pulls from GitHub
        ↓
Installs requirements.txt
        ↓
Runs python app.py
        ↓
Live at https://smart-log-monitor.railway.app
```

---

## 4. Project Architecture

```
User (Browser)
      ↓
Flask Routes (routes.py)
      ↓
      ├── Auth Check (auth.py)
      │         ↓
      ├── Parser (parser.py)
      │         ↓
      ├── Alert Engine (alerts.py)
      │         ↓
      ├── Monitor (monitor.py) ← Watchdog thread
      │         ↓
      ├── Export (export.py)
      │         ↓
      └── Models (models.py)
                ↓
           SQLite Database
```

---

## 5. Log Parsing — How It Works

### Strict Parser (parser.py)

**Supported format:**
```
YYYY-MM-DD HH:MM:SS LEVEL Message
```

**Regex pattern used:**
```python
_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})"
    r"\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"\s+(?P<message>.+)$",
    re.IGNORECASE,
)
```

**Step by step:**
```
Input:  "2026-04-13 10:04:22 ERROR  Database failed"
        ↓
Regex extracts:
  timestamp = "2026-04-13 10:04:22"
  level     = "ERROR"
  message   = "Database failed"
        ↓
Saved to ParsedLog table
        ↓
Alert engine checks message for patterns
```

### Fallback Parser (log_parser.py)

When strict parser finds 0 matches, fallback handles:
- Python logging format
- Apache/Nginx format
- Simple prefix format (ERROR: message)

---

## 6. Alert System — How It Works

### 11 Detection Patterns across 6 Categories

| Category | Pattern | Severity |
|----------|---------|---------|
| Database | `database connection failed` | CRITICAL |
| Database | `query failed`, `deadlock` | HIGH |
| Timeout | `request timed out`, `gateway timeout` | HIGH |
| Timeout | `service unavailable` | MEDIUM |
| Authentication | `authentication failed`, `invalid credentials` | HIGH |
| Authentication | `too many failed login attempts` | CRITICAL |
| Server | `out of memory`, `disk space below` | CRITICAL |
| Server | `high memory usage`, `cpu spike` | HIGH |
| Server | `process killed`, `segmentation fault` | CRITICAL |
| Network | `connection reset`, `ssl error` | MEDIUM |
| Storage | `no space left on device`, `disk read error` | HIGH |

### Alert Severity Levels

```
CRITICAL → Red    → Immediate action needed
HIGH     → Orange → Action needed soon
MEDIUM   → Yellow → Worth investigating
LOW      → Grey   → Informational
```

### How alert is created:

```python
def detect_patterns(message):
    for pattern in PATTERNS:
        if pattern.regex.search(message):
            return pattern  # Match found!

# For each log line:
matches = detect_patterns(log.message)
if matches:
    alert = SystemAlert(
        alert_type = matches.name,
        severity   = matches.severity,
        message    = log.message,
        status     = "open"
    )
    db.session.add(alert)
```

---

## 7. Authentication System

### Session-Based Authentication

**How login works:**
```
User enters username + password
        ↓
check_password_hash(stored_hash, entered_password)
        ↓
If correct → save to Flask session
    session["user_id"]  = user.id
    session["username"] = user.username
    session["role"]     = user.role
        ↓
Every page checks session before showing content
```

### Two Roles

```python
# Admin — full access
@admin_required
def monitor():
    ...

# Both roles — view only
@login_required
def dashboard():
    ...
```

### Decorators used:

```python
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated
```

---

## 8. REST API Endpoints

Flask also exposes JSON APIs for the frontend JavaScript:

| Endpoint | Returns | Used by |
|----------|---------|---------|
| `/api/stats` | Dashboard counts | Stat cards |
| `/api/charts/level-distribution` | Level counts | Doughnut chart |
| `/api/charts/combined-trend` | Daily error/warning | Line chart |
| `/api/alerts/summary` | Alert stats | Dashboard |
| `/api/monitor/live-feed` | New log rows | Live feed |
| `/api/monitor/status` | Active monitors | Nav dot |

**Example response:**
```json
GET /api/charts/level-distribution

{
  "labels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
  "counts": [12, 45, 8, 5, 2]
}
```

---

## 9. File Structure Explained

```
smart_log_monitor/
│
├── app.py              → Application factory (starts everything)
├── config.py           → Settings (database URL, secret key, etc.)
├── extensions.py       → db = SQLAlchemy() shared instance
├── requirements.txt    → All Python packages needed
│
├── modules/            → All Python logic
│   ├── models.py       → Database table definitions
│   ├── auth.py         → Login, logout, user management
│   ├── parser.py       → Strict log line parser
│   ├── log_parser.py   → Fallback multi-format parser
│   ├── alerts.py       → Pattern detection engine
│   ├── monitor.py      → Watchdog real-time watcher
│   ├── export.py       → CSV and Excel download
│   └── routes.py       → All web pages and API routes
│
├── templates/          → HTML pages (Jinja2)
│   ├── base.html       → Master layout (navbar, footer)
│   ├── login.html      → Login page
│   ├── dashboard.html  → Main dashboard with charts
│   ├── upload.html     → File upload page
│   ├── alerts.html     → Alerts management page
│   ├── monitor.html    → Live monitoring page
│   └── admin_users.html→ User management
│
├── static/
│   ├── css/style.css   → Dark theme custom styles
│   └── js/
│       ├── main.js     → Alert badge, monitor dot
│       ├── charts.js   → Chart.js chart rendering
│       └── live_feed.js→ 3-second polling for live logs
│
├── uploads/            → Uploaded log files stored here
└── instance/
    └── logs.db         → SQLite database file
```

---

## 10. Key Concepts Used

### Application Factory Pattern
```python
# Instead of creating app at module level,
# we use a function — allows multiple configs

def create_app(env="development"):
    app = Flask(__name__)
    app.config.from_object(config_map[env])
    db.init_app(app)
    return app
```

### Blueprint Pattern
```python
# Splits routes into logical groups
main_bp = Blueprint("main", __name__)   # Web pages
api_bp  = Blueprint("api",  __name__)   # JSON APIs
auth_bp = Blueprint("auth", __name__)   # Login/logout
```

### Context Processor
```python
# Injects data into EVERY template automatically
@app.context_processor
def inject_globals():
    return {
        "current_user":       get_current_user(),
        "unread_alert_count": SystemAlert.unread_count(),
    }
```

### Custom Jinja2 Filter
```python
# Highlights search keyword in results
@app.template_filter("highlight")
def highlight_filter(text, term):
    # Wraps matched text in <mark> tags
    return Markup(re.sub(term, f"<mark>{term}</mark>", text))
```

---

## 11. Security Measures

| Security Feature | How Implemented |
|-----------------|----------------|
| Password hashing | Werkzeug `generate_password_hash` |
| Session signing | Flask SECRET_KEY |
| XSS prevention | Jinja2 auto-escaping + markupsafe |
| CSRF mitigation | SESSION_COOKIE_SAMESITE = "Lax" |
| Route protection | `@login_required` decorator |
| Admin protection | `@admin_required` decorator |
| File validation | Extension + size check before save |
| Secure cookies | SESSION_COOKIE_HTTPONLY = True |

---

## 12. Summary Table

| What | Why | Tool Used |
|------|-----|-----------|
| Web framework | Handle HTTP requests, routing | Flask |
| Database | Store logs, alerts, users | SQLite + SQLAlchemy |
| Password security | Hash passwords safely | Werkzeug |
| Real-time monitoring | Watch files for changes | Watchdog |
| Data export | CSV and Excel files | Pandas + OpenPyXL |
| Frontend UI | Responsive design | Bootstrap 5 |
| Charts | Visualise log data | Chart.js |
| HTML templates | Dynamic web pages | Jinja2 |
| Deployment | Live on the internet | Railway |
| Log parsing | Extract structured data | Python Regex (re) |
| Alert detection | Find critical patterns | Regex pattern matching |
| Authentication | Login system | Flask Sessions |

---

## 13. What Makes This Project Unique

1. **Dual Parser** — Strict format + fallback for any log format
2. **11 Detection Patterns** — Covers real-world failure scenarios
3. **Live Monitoring** — Files watched in real time using threads
4. **Role-Based Access** — Admin and Viewer roles
5. **Export Reports** — CSV and Excel with pandas
6. **REST API** — Full JSON API for frontend charts
7. **Dark Theme UI** — Professional production-ready design
8. **Email Alerts** — SMTP notification support
9. **Deployed Live** — Real production URL on Railway

---

## 14. How to Run Locally

```bash
# 1. Clone or extract project
cd smart_log_monitor

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python app.py

# 5. Open browser
http://127.0.0.1:5000
# Login: admin / admin123
```

---

*Project by Tamilvanan I — BSc AI & ML, Sri Krishna Adithya College of Arts and Science, Coimbatore — 2026*
