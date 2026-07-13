"""
src/database/database_manager.py
================================
Defines database schemas (SQLAlchemy models) and table administration tools.
Exposes a factory method to instantiate the correct repository interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON
from .connection_manager import Base, ConnectionManager

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Returns a timezone-naive datetime representing UTC time."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =============================================================================
# Database Models
# =============================================================================

class CompletedContactModel(Base):
    """Stores validated, complete business profiles."""
    __tablename__ = "completed_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    npi = Column(String(50), nullable=True, index=True)
    business_name = Column(String(255), nullable=True, index=True)
    official_website = Column(String(500), nullable=True, unique=True, index=True)
    
    # Store lists and dicts as JSON. Handled natively in PG, text-based in SQLite.
    emails = Column(JSON, nullable=True)
    phones = Column(JSON, nullable=True)
    social_links = Column(JSON, nullable=True)
    
    address = Column(Text, nullable=True)
    pages_visited = Column(JSON, nullable=True)
    extraction_method = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    errors = Column(JSON, nullable=True)
    provenance = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class FailedRecordModel(Base):
    """Stores records that failed scraping or validation entirely."""
    __tablename__ = "failed_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    npi = Column(String(50), nullable=True, index=True)
    company_name = Column(String(255), nullable=True)
    website = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)
    failed_at = Column(DateTime, default=utcnow, nullable=False)


class RetryRecordModel(Base):
    """Stores transiently failed records scheduled for subsequent retry attempts."""
    __tablename__ = "retry_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    npi = Column(String(50), nullable=True, index=True)
    company_name = Column(String(255), nullable=True)
    website = Column(String(500), nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    last_error = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)
    status = Column(String(50), default="pending", nullable=False)  # pending, processing, completed, failed
    next_retry_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CheckpointModel(Base):
    """Stores ingestion batch tracking information to allow recovery on restart."""
    __tablename__ = "processing_checkpoints"

    batch_id = Column(String(100), primary_key=True)
    last_processed_index = Column(Integer, default=0, nullable=False)
    total_records = Column(Integer, default=0, nullable=False)
    status = Column(String(50), default="in_progress", nullable=False)  # in_progress, completed, failed
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AuditTrailModel(Base):
    """Stores detailed audit logs for every processed record."""
    __tablename__ = "audit_trails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    row_number = Column(Integer, nullable=True)
    npi = Column(String(50), nullable=True, index=True)
    entity_name = Column(String(255), nullable=True)
    search_query = Column(Text, nullable=True)
    urls_visited = Column(JSON, nullable=True)
    selected_website = Column(String(500), nullable=True)
    contact_pages_crawled = Column(JSON, nullable=True)
    emails_extracted = Column(JSON, nullable=True)
    phones_extracted = Column(JSON, nullable=True)
    validation_results = Column(JSON, nullable=True)
    crawl_telemetry = Column(JSON, nullable=True)
    outcome = Column(String(50), nullable=True)
    reason_code = Column(String(100), nullable=True)
    processing_duration_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


# =============================================================================
# Database Manager Orchestrator
# =============================================================================

class DatabaseManager:
    """
    Orchestrates ORM schema setup and provides the repository factory.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self.conn_mgr = connection_manager

    def create_tables(self) -> None:
        """Creates all registered schemas in the database."""
        logger.info("[DatabaseManager] Creating database tables...")
        Base.metadata.create_all(bind=self.conn_mgr.engine)
        logger.info("[DatabaseManager] All tables created successfully.")

    def drop_all_tables(self) -> None:
        """Drops all tables from the database (useful for reset or tests)."""
        logger.warning("[DatabaseManager] Dropping ALL database tables...")
        Base.metadata.drop_all(bind=self.conn_mgr.engine)
        logger.info("[DatabaseManager] All tables dropped.")

    def get_repository(self) -> Any:
        """
        Factory method to resolve the concrete repository instance.
        Lazy imports repositories to avoid circular dependency loops.
        """
        engine_type = self.conn_mgr.engine_type
        if engine_type == "postgres":
            from .postgres_repository import PostgresRepository
            return PostgresRepository(self.conn_mgr)
        else:
            from .sqlite_repository import SQLiteRepository
            return SQLiteRepository(self.conn_mgr)
