"""
src/database/postgres_repository.py
==================================
Concrete PostgreSQL repository implementation using SQLAlchemy.
Inherits database-independent ORM behavior, allowing future dialect-specific enhancements.
"""

from __future__ import annotations

import logging
from .sqlite_repository import SQLiteRepository

logger = logging.getLogger(__name__)


class PostgresRepository(SQLiteRepository):
    """
    SQLAlchemy-based PostgreSQL repository.
    Inherits standard dialect-independent operations from SQLiteRepository.
    Dialect-specific configurations (like native ON CONFLICT upserting or JSONB optimizations)
    can be customized here without modifying the base logic.
    """
    pass
