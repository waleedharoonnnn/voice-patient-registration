"""SQLAlchemy models. Imported so Alembic's autogenerate sees every table."""

from app.models.appointment import Appointment
from app.models.call_log import CallLog
from app.models.patient import Patient
from app.models.provider import Provider

__all__ = ["Appointment", "CallLog", "Patient", "Provider"]
