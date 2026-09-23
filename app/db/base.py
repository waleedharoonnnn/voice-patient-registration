"""Declarative base shared by all SQLAlchemy models (added in a later batch)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ORM models. No models are defined yet (see CLAUDE.md §3)."""
