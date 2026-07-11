"""
src/database/
=============
Persistence Layer responsible for database operations, connection management,
transaction isolation, bulk writes, retries, and interruptions handling.
"""

from __future__ import annotations

from .connection_manager import Base, ConnectionManager
from .database_manager import DatabaseManager, CompletedContactModel, FailedRecordModel, RetryRecordModel, CheckpointModel
from .repository import BaseRepository
from .sqlite_repository import SQLiteRepository
from .postgres_repository import PostgresRepository
from .transaction_manager import TransactionManager
from .bulk_writer import BulkWriter, DatabaseMetrics
from .retry_repository import RetryRepository

__all__ = [
    "Base",
    "ConnectionManager",
    "DatabaseManager",
    "CompletedContactModel",
    "FailedRecordModel",
    "RetryRecordModel",
    "CheckpointModel",
    "BaseRepository",
    "SQLiteRepository",
    "PostgresRepository",
    "TransactionManager",
    "BulkWriter",
    "DatabaseMetrics",
    "RetryRepository",
]
