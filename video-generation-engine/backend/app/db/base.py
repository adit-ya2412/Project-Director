"""SQLAlchemy declarative base. Every ORM model in app/models/ inherits
from this, and this is the metadata Alembic's env.py autogenerates against."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
