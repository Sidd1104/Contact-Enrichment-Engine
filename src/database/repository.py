"""
src/database/repository.py
==========================
Defines the Abstract Repository Pattern interface.
Specifies operations for saving profiles, handling failures/retries, and checkpointing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from src.validator.business_profile_validator import BusinessProfile
from .connection_manager import ConnectionManager


class BaseRepository(ABC):
    """
    Abstract interface for persisting data, decoupling business logic from
    specific database engines (SQLite, PostgreSQL, etc.).
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self.conn_mgr = connection_manager

    @abstractmethod
    def save_completed_batch(
        self,
        profiles: List[BusinessProfile],
        raw_records: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[int, int]:
        """
        Saves a batch of completed/validated business profiles.
        Performs insert or update (upsert) depending on duplicates.
        Returns a tuple of (inserted_count, updated_count).
        """
        pass

    @abstractmethod
    def save_failed_batch(
        self,
        records: List[Dict[str, Any]],
        error_messages: List[str]
    ) -> int:
        """
        Saves a batch of records that failed processing.
        Returns the number of records saved to the failed table.
        """
        pass

    @abstractmethod
    def save_retry_batch(
        self,
        records: List[Dict[str, Any]],
        error_messages: List[str],
        max_retries: int = 3
    ) -> int:
        """
        Saves a batch of records scheduled for retry.
        Returns the number of records saved/updated in the retry table.
        """
        pass

    @abstractmethod
    def get_pending_retries(self) -> List[Dict[str, Any]]:
        """
        Retrieves all retry records with 'pending' status.
        """
        pass

    @abstractmethod
    def update_retry_status(
        self,
        npi: str,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """
        Updates the retry status ('pending', 'processing', 'completed', 'failed')
        and error logging for a specific NPI.
        """
        pass

    @abstractmethod
    def get_checkpoint(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the last saved index/progress of a processing batch.
        """
        pass

    @abstractmethod
    def save_checkpoint(
        self,
        batch_id: str,
        last_processed_index: int,
        total_records: int,
        status: str
    ) -> None:
        """
        Persists checkpoint state for interruption recovery.
        """
        pass

    @abstractmethod
    def find_by_website(self, website: str) -> Optional[BusinessProfile]:
        """
        Queries completed profiles by official website to locate potential duplicates.
        """
        pass

    @abstractmethod
    def find_by_npi(self, npi: str) -> Optional[BusinessProfile]:
        """
        Queries completed profiles by NPI.
        """
        pass

    @abstractmethod
    def get_all_completed(self) -> List[BusinessProfile]:
        """
        Retrieves all completed profiles in the database.
        """
        pass

    @abstractmethod
    def get_all_failed(self) -> List[Dict[str, Any]]:
        """
        Retrieves all failed records.
        """
        pass

    @abstractmethod
    def get_all_retries(self) -> List[Dict[str, Any]]:
        """
        Retrieves all retry records.
        """
        pass

    @abstractmethod
    def save_audit_trails(self, audit_records: List[Dict[str, Any]]) -> None:
        """
        Saves a batch of audit trail records to the database.
        """
        pass
