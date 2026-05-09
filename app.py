"""
app.py
======
Application factory for the Smart Log Monitoring & Alert System.

Usage
-----
Development::

    python app.py

Production (gunicorn example)::

    gunicorn "app:create_app('production')" --workers 2 --bind 0.0.0.0:8000

Environment variables
---------------------
FLASK_ENV      — 'development' | 'production' | 'testing'  (default: development)
SECRET_KEY     — signing key for sessions (REQUIRED in production)
DATABASE_URL   — SQLAlchemy URI  (default: sqlite:///instance/logs.db)
PORT           — TCP port for the built-in dev server  (default: 5000)
ADMIN_USERNAME — default admin username created on first run  (default: admin)
ADMIN_PASSWORD — default admin password created on first run  (default: admin123)
"""

import os
import re
from markupsafe import Markup, escape as _escape

from flask import Flask
from config import config_map
from extensions import db


def create_app(env: str = "default") -> Flask:
    """
    Application factory.

    Parameters
    ----------
    env : str
        Configuration environment name — one of 'development', 'production',
        'testing', or 'default'  (default maps to DevelopmentConfig).

    Returns
    -------
    Flask
        A fully configured, ready-to-run Flask application instance.
    """
    app = Flask(__name__, instance_relative_config=True)

    # ── 1. Load configuration ─────────────────────────────────────────────────
    app.config.from_object(config_map[env])

    # ── 2. Ensure required directories exist ──────────────────────────────────
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.instance_path, exist_ok=True)

    # ── 3. Initialise Flask-SQLAlchemy ────────────────────────────────────────
    db.init_app(app)

    # ── 4. Register blueprints ────────────────────────────────────────────────
    from modules.routes import main_bp, api_bp
    from modules.auth   import auth_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)

    # ── 5. Context processor — data available in every template ───────────────
    @app.context_processor
    def inject_template_globals() -> dict:
        """
        Inject auth state and unread alert count into every Jinja2 template
        so the navbar can display the username and badge without each route
        having to fetch them explicitly.
        """
        from modules.auth import get_current_user
        try:
            from modules.models import SystemAlert
            unread = SystemAlert.unread_count()
        except Exception:
            unread = 0
        return {
            "current_user":       get_current_user(),
            "unread_alert_count": unread,
        }

    # ── 6. Custom Jinja2 filters ──────────────────────────────────────────────
    @app.template_filter("highlight")
    def highlight_filter(text: str, term: str) -> Markup:
        """
        Wrap every occurrence of *term* in ``<mark>`` tags for search
        result highlighting.  HTML-escapes input first to prevent XSS.
        """
        if not term:
            return Markup(_escape(text))
        escaped_text = str(_escape(text))
        escaped_term = re.escape(str(_escape(term)))
        highlighted  = re.sub(
            f"({escaped_term})",
            r'<mark class="search-highlight">\1</mark>',
            escaped_text,
            flags=re.IGNORECASE,
        )
        return Markup(highlighted)

    # ── 7. Create database tables and seed default data ───────────────────────
    with app.app_context():
        from modules import models  # noqa: F401 — registers all models with SQLAlchemy
        db.create_all()
        from modules.auth import seed_default_admin
        seed_default_admin(app)

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _env = os.environ.get("FLASK_ENV", "development")
    application = create_app(_env)
    application.run(
        host  = "0.0.0.0",
        port  = int(os.environ.get("PORT", 5000)),
        debug = (_env == "development"),
    )
