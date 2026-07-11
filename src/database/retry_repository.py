"""
src/database/retry_repository.py
================================
Provides a high-level state manager for retry queues and failed tasks.
Integrates with the underlying active repository to run state transactions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from .repository import BaseRepository
from .database_manager import RetryRecordModel, FailedRecordModel, CompletedContactModel, utcnow
from .transaction_manager import TransactionManager

logger = logging.getLogger(__name__)


class RetryRepository:
    """
    Coordinates state-transitions for transient failures, retries, and absolute failures.
    """

    def __init__(self, repo: BaseRepository) -> None:
        self.repo = repo
        self.conn_mgr = repo.conn_mgr

    def persist_failure(self, record: Dict[str, Any], error_message: str) -> None:
        """Stores a record in the failed_records table immediately."""
        logger.info(f"[RetryRepository] Logging permanent failure for website: {record.get('website')}")
        self.repo.save_failed_batch([record], [error_message])

    def persist_retry(self, record: Dict[str, Any], error_message: str, max_retries: int = 3) -> None:
        """Stores or increments a record in the retry queue."""
        logger.info(f"[RetryRepository] Logging retry attempt for website: {record.get('website')}")
        self.repo.save_retry_batch([record], [error_message], max_retries=max_retries)

    def fetch_pending_retries(self) -> List[Dict[str, Any]]:
        """Returns all records that are ready to be retried."""
        return self.repo.get_pending_retries()

    def process_retry_success(self, retry_id: int) -> None:
        """Marks a retry task as completed successfully in the retry records table."""
        with TransactionManager(self.conn_mgr) as session:
            row = session.query(RetryRecordModel).filter(RetryRecordModel.id == retry_id).first()
            if row:
                row.status = "completed"
                row.updated_at = utcnow()
                logger.info(f"[RetryRepository] Retry ID {retry_id} marked as completed.")

    def process_retry_failure(self, retry_id: int, error_message: str) -> None:
        """
        Increments the retry counter for a retry task.
        If it exceeds max_retries, transitions the record to 'failed' status
        and clones it into the failed_records table.
        """
        with TransactionManager(self.conn_mgr) as session:
            row = session.query(RetryRecordModel).filter(RetryRecordModel.id == retry_id).first()
            if row:
                row.retry_count += 1
                row.last_error = error_message
                row.updated_at = utcnow()

                if row.retry_count >= row.max_retries:
                    row.status = "failed"
                    # Clone to failed records
                    failed_row = FailedRecordModel(
                        npi=row.npi,
                        company_name=row.company_name,
                        website=row.website,
                        error_message=f"Max retries ({row.max_retries}) exceeded. Last error: {error_message}",
                        raw_data=row.raw_data,
                        failed_at=utcnow()
                    )
                    session.add(failed_row)
                    logger.warning(
                        f"[RetryRepository] Retry ID {retry_id} (website={row.website}) exceeded "
                        f"max retries ({row.max_retries}). Moved to failed_records."
                    )
                else:
                    row.status = "pending"
                    logger.info(
                        f"[RetryRepository] Retry ID {retry_id} (website={row.website}) failed. "
                        f"Incremented attempt to {row.retry_count}/{row.max_retries}."
                    )
