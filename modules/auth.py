"""
modules/auth.py
===============
Session-based authentication for the Smart Log Monitoring system.

Provides
--------
* ``login_required``   — decorator: any logged-in user
* ``admin_required``   — decorator: admin role only
* ``get_current_user`` — return the User ORM object for the session, or None
* ``login_user``       — write user identity to the Flask session
* ``logout_user``      — clear the Flask session
* ``auth_bp``          — Blueprint with /login and /logout routes

Session structure
-----------------
Flask's signed-cookie session stores only:
    session["user_id"]   : int    — User.id
    session["username"]  : str    — User.username (for display, avoids DB hit)
    session["role"]      : str    — User.role     (for fast role checks)

All three fields must be present for a session to be considered valid.

Python 3.10 compatible throughout.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime
from typing import Callable, Optional

from flask import (
    Blueprint, flash, g, redirect, render_template,
    request, session, url_for,
)

log = logging.getLogger(__name__)

# Blueprint — registered in app.py alongside main_bp and api_bp
auth_bp = Blueprint("auth", __name__)


# ── Session helpers ────────────────────────────────────────────────────────────

def login_user(user) -> None:
    """
    Write *user* identity into the Flask session and update last_login_at.

    Sets session values individually rather than calling session.clear()
    first, which can cause issues in some WSGI test environments.
    """
    from extensions import db

    # Remove any stale auth keys (avoid fixation without breaking cookies)
    session.pop("user_id",  None)
    session.pop("username", None)
    session.pop("role",     None)

    session["user_id"]  = user.id
    session["username"] = user.username
    session["role"]     = user.role
    session.permanent   = True  # respect PERMANENT_SESSION_LIFETIME from config
    session.modified    = True

    # Update last login timestamp
    user.last_login_at = datetime.utcnow()
    db.session.commit()

    log.info("User '%s' (id=%s, role=%s) logged in", user.username, user.id, user.role)


def logout_user() -> None:
    """Clear all session data, effectively logging the user out."""
    username = session.get("username", "<unknown>")
    session.clear()
    log.info("User '%s' logged out", username)


def get_current_user():
    """
    Return the User ORM object for the active session, or None.

    Results are cached in Flask's ``g`` object for the duration of the request
    so we only hit the database once per request.

    IMPORTANT: We only cache a positive result (a real User object).
    We never cache None, because the context processor runs early in the
    request cycle and can set g.current_user=None before the DB is ready,
    which would then be returned to route decorators incorrectly.
    """
    # Return cached positive result only
    cached = getattr(g, "current_user", _SENTINEL)
    if cached is not _SENTINEL and cached is not None:
        return cached

    user_id = session.get("user_id")
    if not user_id:
        return None

    from modules.models import User
    from extensions import db
    user = db.session.get(User, user_id)

    # Validate that the session role matches what's in the DB (catches
    # role changes that happen while the user is logged in).
    if user is None or not user.is_active or user.role != session.get("role"):
        session.clear()
        return None

    # Cache the positive result for this request
    g.current_user = user
    return user


def is_logged_in() -> bool:
    """Return True if the current request has a valid session."""
    return get_current_user() is not None


def is_admin() -> bool:
    """Return True if the logged-in user has the admin role."""
    user = get_current_user()
    return user is not None and user.is_admin


# Sentinel object used by get_current_user to distinguish "not cached" from "cached None"
_SENTINEL = object()


# ── Access decorators ──────────────────────────────────────────────────────────

def login_required(fn: Callable) -> Callable:
    """
    Route decorator — redirect to /login if the user is not authenticated.

    Usage::

        @main_bp.route("/dashboard")
        @login_required
        def dashboard():
            ...
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn: Callable) -> Callable:
    """
    Route decorator — require admin role.

    Unauthenticated users are redirected to /login.
    Authenticated non-admins receive a 403 page.

    Usage::

        @main_bp.route("/monitor")
        @admin_required
        def monitor():
            ...
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if not user.is_admin:
            log.warning(
                "Non-admin user '%s' tried to access admin route '%s'",
                user.username, request.path,
            )
            return render_template("403.html"), 403
        return fn(*args, **kwargs)

    return wrapper


def api_login_required(fn: Callable) -> Callable:
    """
    Lightweight decorator for JSON API routes.
    Returns 401 JSON instead of a redirect when unauthenticated.
    """
    from flask import jsonify

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)

    return wrapper


def api_admin_required(fn: Callable) -> Callable:
    """
    Lightweight decorator for admin-only JSON API routes.
    Returns 401 or 403 JSON instead of a redirect.
    """
    from flask import jsonify

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return jsonify({"error": "Authentication required"}), 401
        if not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)

    return wrapper


# ── Auth Blueprint routes ──────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Login page.

    GET  — render the login form.
    POST — validate credentials; on success redirect to ``next`` param or
           dashboard; on failure re-render with an error flash.
    """
    # Already logged in → go straight to dashboard
    if is_logged_in():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        from modules.models import User

        user = User.query.filter_by(username=username).first()

        if user is None or not user.is_active:
            flash("Invalid username or password.", "danger")
            return render_template("login.html", username=username), 401

        if not user.check_password(password):
            log.warning("Failed login attempt for username '%s' from %s",
                        username, request.remote_addr)
            flash("Invalid username or password.", "danger")
            return render_template("login.html", username=username), 401

        login_user(user)

        # Honour the ?next= redirect, but only for relative paths (security)
        next_url = request.form.get("next") or request.args.get("next", "")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)

        return redirect(url_for("main.dashboard"))

    return render_template("login.html", username="")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Log out the current user and redirect to the login page.
    POST-only to prevent CSRF logout via crafted links.
    """
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ── User management routes (admin only) ───────────────────────────────────────

@auth_bp.route("/admin/users")
@admin_required
def user_list():
    """Admin page: list all users."""
    from modules.models import User
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)


@auth_bp.route("/admin/users/create", methods=["GET", "POST"])
@admin_required
def user_create():
    """Admin page: create a new user."""
    if request.method == "POST":
        from modules.models import User
        from extensions import db

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role     = request.form.get("role", "viewer")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("admin_user_form.html", action="Create", user=None)

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("admin_user_form.html", action="Create", user=None)

        if User.query.filter_by(username=username).first():
            flash(f"Username '{username}' is already taken.", "danger")
            return render_template("admin_user_form.html", action="Create", user=None)

        if role not in ("admin", "viewer"):
            role = "viewer"

        new_user = User(username=username, role=role)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f"User '{username}' created with role '{role}'.", "success")
        return redirect(url_for("auth.user_list"))

    return render_template("admin_user_form.html", action="Create", user=None)


@auth_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    """Admin page: edit an existing user."""
    from modules.models import User
    from extensions import db

    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        new_role     = request.form.get("role", user.role)
        new_password = request.form.get("password", "").strip()
        is_active    = request.form.get("is_active") == "1"

        if new_role not in ("admin", "viewer"):
            new_role = "viewer"

        # Prevent the last admin from being demoted
        if user.is_admin and new_role != "admin":
            admin_count = User.query.filter_by(role="admin", is_active=True).count()
            if admin_count <= 1:
                flash("Cannot demote the last active admin.", "danger")
                return render_template("admin_user_form.html", action="Edit", user=user)

        user.role      = new_role
        user.is_active = is_active

        if new_password:
            if len(new_password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return render_template("admin_user_form.html", action="Edit", user=user)
            user.set_password(new_password)

        db.session.commit()
        flash(f"User '{user.username}' updated.", "success")

        # If the edited user is the current session user, refresh the session role
        if session.get("user_id") == user.id:
            session["role"] = user.role

        return redirect(url_for("auth.user_list"))

    return render_template("admin_user_form.html", action="Edit", user=user)


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id: int):
    """Admin action: delete a user (cannot delete yourself)."""
    from modules.models import User
    from extensions import db

    user = User.query.get_or_404(user_id)

    if user.id == session.get("user_id"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("auth.user_list"))

    # Prevent deleting the last admin
    if user.is_admin:
        admin_count = User.query.filter_by(role="admin", is_active=True).count()
        if admin_count <= 1:
            flash("Cannot delete the last active admin account.", "danger")
            return redirect(url_for("auth.user_list"))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{username}' deleted.", "success")
    return redirect(url_for("auth.user_list"))


# ── Seed helper (called from app factory) ─────────────────────────────────────

def seed_default_admin(app) -> None:
    """
    Create the default admin account if no users exist in the database.

    Called once from the app factory inside an app context.
    Credentials come from config:
        DEFAULT_ADMIN_USERNAME  (env: ADMIN_USERNAME,  default: 'admin')
        DEFAULT_ADMIN_PASSWORD  (env: ADMIN_PASSWORD,  default: 'admin123')
    """
    from modules.models import User
    from extensions import db

    if User.query.count() > 0:
        return  # users already exist — don't touch anything

    username = app.config.get("DEFAULT_ADMIN_USERNAME", "admin")
    password = app.config.get("DEFAULT_ADMIN_PASSWORD", "admin123")

    admin = User(username=username, role="admin")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    log.info(
        "Default admin account created — username: '%s'. "
        "Change this password immediately in production.",
        username,
    )
