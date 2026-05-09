"""
extensions.py
Initialises Flask extensions as standalone objects to avoid circular imports.
Import these into app.py and modules as needed.
"""

from flask_sqlalchemy import SQLAlchemy

# Single shared SQLAlchemy instance
db = SQLAlchemy()
