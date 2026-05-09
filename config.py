"""
config.py
=========
Application configuration for the Smart Log Monitoring & Alert System.

Three environments are provided:
  development  — debug mode, local SQLite database
  production   — no debug, SECRET_KEY must come from the environment
  testing      — file-based SQLite so test-client requests share state

All sensitive values are read from environment variables.  A ``.env`` file
in the project root is loaded automatically when ``python-dotenv`` is installed.
"""

import os

# Absolute path to the project root directory
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration — all shared settings."""

    # ── Security ──────────────────────────────────────────────────────────────
    # Override via SECRET_KEY environment variable before deploying.
    SECRET_KEY             = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SESSION_COOKIE_HTTPONLY = True          # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE = "Lax"        # mitigates CSRF via cross-site requests
    SESSION_COOKIE_SECURE   = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = 86_400 * 7  # sessions live for 7 days

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI     = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'logs.db')}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # suppresses a deprecation warning

    # ── File uploads ──────────────────────────────────────────────────────────
    UPLOAD_FOLDER      = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024       # 16 MB hard cap
    ALLOWED_EXTENSIONS = {"log", "txt"}          # strict parser only supports these

    # ── Default admin account ─────────────────────────────────────────────────
    # Used only to seed the very first admin when the database is empty.
    # Always override via environment variables in production.
    DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    # ── Email alert notifications (all optional) ──────────────────────────────
    # Set ALERT_EMAIL_ENABLED=true and configure SMTP to enable.
    ALERT_EMAIL_ENABLED      = os.environ.get("ALERT_EMAIL_ENABLED",  "false").lower() == "true"
    ALERT_EMAIL_FROM         = os.environ.get("ALERT_EMAIL_FROM",     "")
    ALERT_EMAIL_TO           = os.environ.get("ALERT_EMAIL_TO",       "")  # comma-separated
    ALERT_SMTP_HOST          = os.environ.get("ALERT_SMTP_HOST",      "smtp.gmail.com")
    ALERT_SMTP_PORT          = int(os.environ.get("ALERT_SMTP_PORT",  "587"))
    ALERT_SMTP_USER          = os.environ.get("ALERT_SMTP_USER",      "")
    ALERT_SMTP_PASSWORD      = os.environ.get("ALERT_SMTP_PASSWORD",  "")
    ALERT_SMTP_TLS           = os.environ.get("ALERT_SMTP_TLS",       "true").lower() == "true"
    ALERT_EMAIL_MIN_SEVERITY = os.environ.get("ALERT_EMAIL_MIN_SEVERITY", "high")


class DevelopmentConfig(Config):
    """Local development — debug mode enabled."""
    DEBUG   = True
    TESTING = False


class ProductionConfig(Config):
    """Production — debug off, secret key must come from the environment."""
    DEBUG   = False
    TESTING = False
    # Explicitly require the environment variable; will be None if missing,
    # which causes Flask to raise at startup (intentional).
    SECRET_KEY = os.environ.get("SECRET_KEY")


class TestingConfig(Config):
    """
    Automated tests.

    Uses a named temp file instead of ``sqlite:///:memory:`` so that requests
    made through Flask's test client (which each push a fresh app context)
    all see the same data.
    """
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:////tmp/test_smart_log_monitor.db"


# Map string names to config classes (used by create_app)
config_map: dict = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
    "default":     DevelopmentConfig,
}
