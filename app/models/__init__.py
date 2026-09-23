"""SQLAlchemy models. Imported so Alembic's autogenerate sees every table."""

from app.models.patient import Patient

__all__ = ["Patient"]
