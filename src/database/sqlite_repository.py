"""
src/database/sqlite_repository.py
================================
Concrete SQLite repository implementation using SQLAlchemy.
Supports batch persistence, duplicate merging, checkpoints, and retries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.orm import Session
from src.validator.business_profile_validator import BusinessProfile
from .repository import BaseRepository
from .connection_manager import ConnectionManager
from .database_manager import (
    CompletedContactModel,
    FailedRecordModel,
    RetryRecordModel,
    CheckpointModel,
    utcnow
)
from .transaction_manager import TransactionManager

logger = logging.getLogger(__name__)


class SQLiteRepository(BaseRepository):
    """
    SQLAlchemy-based SQLite repository implementation.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        super().__init__(connection_manager)

    def _convert_profile_to_dict(self, profile: BusinessProfile) -> Dict[str, Any]:
        """Converts a BusinessProfile Pydantic model to a dict suited for DB models."""
        return {
            "business_name": profile.business_name,
            "official_website": profile.official_website or None,
            "emails": profile.emails,
            "phones": profile.phones,
            "social_links": profile.social_links,
            "address": profile.address,
            "pages_visited": profile.pages_visited,
            "extraction_method": profile.extraction_method,
            "confidence": profile.confidence,
            "errors": profile.errors,
            "provenance": profile.provenance
        }

    def find_by_website(self, website: str) -> Optional[BusinessProfile]:
        """Finds a completed profile by website to check for duplicates."""
        if not website:
            return None
        session = self.conn_mgr.get_session()
        try:
            row = session.query(CompletedContactModel).filter(CompletedContactModel.official_website == website).first()
            if row:
                return BusinessProfile(**self._convert_row_to_dict(row))
            return None
        finally:
            session.close()

    def find_by_npi(self, npi: str) -> Optional[BusinessProfile]:
        """Finds a completed profile by NPI."""
        if not npi:
            return None
        session = self.conn_mgr.get_session()
        try:
            row = session.query(CompletedContactModel).filter(CompletedContactModel.npi == npi).first()
            if row:
                return BusinessProfile(**self._convert_row_to_dict(row))
            return None
        finally:
            session.close()

    def _convert_row_to_dict(self, row: CompletedContactModel) -> Dict[str, Any]:
        """Helper to serialize a database row back to BusinessProfile parameters."""
        return {
            "business_name": row.business_name or "",
            "official_website": row.official_website or "",
            "emails": row.emails or [],
            "phones": row.phones or [],
            "social_links": row.social_links or {},
            "address": row.address or "",
            "pages_visited": row.pages_visited or [],
            "extraction_method": row.extraction_method or "",
            "confidence": row.confidence or 0.0,
            "errors": row.errors or [],
            "provenance": row.provenance or {}
        }

    def save_completed_batch(
        self,
        profiles: List[BusinessProfile],
        raw_records: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[int, int]:
        """
        Saves completed contacts. If a record with the same NPI or website exists,
        updates the existing row. Performs duplicate detection and merging.
        Returns a tuple of (inserts_count, updates_count).
        """
        inserts = 0
        updates = 0
        raw_map = {}
        if raw_records:
            for rec in raw_records:
                web = rec.get("website", "")
                npi = rec.get("npi", "")
                if web:
                    raw_map[web] = rec
                if npi:
                    raw_map[npi] = rec

        with TransactionManager(self.conn_mgr) as session:
            for profile in profiles:
                # Resolve NPI from raw mapping or profile error context if embedded
                npi = None
                web = profile.official_website or None
                
                # Check raw records map
                if web and web in raw_map:
                    npi = raw_map[web].get("npi")
                
                # Try finding existing record
                existing: Optional[CompletedContactModel] = None
                if npi:
                    existing = session.query(CompletedContactModel).filter(CompletedContactModel.npi == npi).first()
                if not existing and web:
                    existing = session.query(CompletedContactModel).filter(CompletedContactModel.official_website == web).first()

                data = self._convert_profile_to_dict(profile)
                data["npi"] = npi or (existing.npi if existing else None)
                data["updated_at"] = utcnow()

                if existing:
                    # Update fields, merge lists to prevent duplicates
                    existing.business_name = data["business_name"] or existing.business_name
                    
                    # Merge lists
                    existing.emails = list(set((existing.emails or []) + (data["emails"] or [])))
                    existing.phones = list(set((existing.phones or []) + (data["phones"] or [])))
                    existing.pages_visited = list(set((existing.pages_visited or []) + (data["pages_visited"] or [])))
                    existing.errors = list(set((existing.errors or []) + (data["errors"] or [])))
                    
                    # Merge dicts (copy to trigger SQLAlchemy mutation tracking)
                    existing_socials = dict(existing.social_links or {})
                    new_socials = data["social_links"] or {}
                    for k, v in new_socials.items():
                        if v:
                            existing_socials[k] = v
                    existing.social_links = existing_socials

                    existing_provenance = dict(existing.provenance or {})
                    new_provenance = data["provenance"] or {}
                    for k, v in new_provenance.items():
                        if v:
                            existing_provenance[k] = v
                    existing.provenance = existing_provenance

                    existing.address = data["address"] or existing.address
                    existing.extraction_method = "Merged"
                    existing.confidence = max(existing.confidence or 0.0, data["confidence"] or 0.0)
                    existing.updated_at = utcnow()
                    updates += 1
                else:
                    new_row = CompletedContactModel(**data)
                    new_row.created_at = utcnow()
                    session.add(new_row)
                    inserts += 1
        return inserts, updates

    def save_failed_batch(
        self,
        records: List[Dict[str, Any]],
        error_messages: List[str]
    ) -> int:
        """Saves a batch of failed records."""
        affected = 0
        with TransactionManager(self.conn_mgr) as session:
            for rec, err in zip(records, error_messages):
                failed_row = FailedRecordModel(
                    npi=rec.get("npi"),
                    company_name=rec.get("company_name") or rec.get("business_name", ""),
                    website=rec.get("website") or rec.get("official_website", ""),
                    error_message=err,
                    raw_data=rec,
                    failed_at=utcnow()
                )
                session.add(failed_row)
                affected += 1
        return affected

    def save_retry_batch(
        self,
        records: List[Dict[str, Any]],
        error_messages: List[str],
        max_retries: int = 3
    ) -> int:
        """Saves or updates records scheduled for retry."""
        affected = 0
        with TransactionManager(self.conn_mgr) as session:
            for rec, err in zip(records, error_messages):
                npi = rec.get("npi")
                web = rec.get("website") or rec.get("official_website", "")
                
                existing = None
                if npi:
                    existing = session.query(RetryRecordModel).filter(RetryRecordModel.npi == npi).first()
                if not existing and web:
                    existing = session.query(RetryRecordModel).filter(RetryRecordModel.website == web).first()

                if existing:
                    existing.retry_count += 1
                    existing.last_error = err
                    existing.raw_data = rec
                    existing.status = "pending"
                    existing.updated_at = utcnow()
                else:
                    retry_row = RetryRecordModel(
                        npi=npi,
                        company_name=rec.get("company_name") or rec.get("business_name", ""),
                        website=web,
                        retry_count=1,
                        max_retries=max_retries,
                        last_error=err,
                        raw_data=rec,
                        status="pending",
                        updated_at=utcnow()
                    )
                    session.add(retry_row)
                affected += 1
        return affected

    def get_pending_retries(self) -> List[Dict[str, Any]]:
        """Retrieves retry records that are pending execution."""
        session = self.conn_mgr.get_session()
        try:
            rows = session.query(RetryRecordModel).filter(
                RetryRecordModel.status == "pending",
                RetryRecordModel.retry_count < RetryRecordModel.max_retries
            ).all()
            
            results = []
            for r in rows:
                raw = r.raw_data or {}
                # Ensure db meta attributes are accessible
                raw["_retry_id"] = r.id
                raw["_retry_count"] = r.retry_count
                results.append(raw)
            return results
        finally:
            session.close()

    def update_retry_status(
        self,
        npi: str,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Updates the state of a retry record."""
        with TransactionManager(self.conn_mgr) as session:
            row = session.query(RetryRecordModel).filter(RetryRecordModel.npi == npi).first()
            if row:
                row.status = status
                if error_message:
                    row.last_error = error_message
                row.updated_at = utcnow()

    def get_checkpoint(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Gets checkpoint configuration details."""
        session = self.conn_mgr.get_session()
        try:
            row = session.query(CheckpointModel).filter(CheckpointModel.batch_id == batch_id).first()
            if row:
                return {
                    "batch_id": row.batch_id,
                    "last_processed_index": row.last_processed_index,
                    "total_records": row.total_records,
                    "status": row.status,
                    "updated_at": row.updated_at
                }
            return None
        finally:
            session.close()

    def save_checkpoint(
        self,
        batch_id: str,
        last_processed_index: int,
        total_records: int,
        status: str
    ) -> None:
        """Saves/updates a processing checkpoint."""
        with TransactionManager(self.conn_mgr) as session:
            row = session.query(CheckpointModel).filter(CheckpointModel.batch_id == batch_id).first()
            if row:
                row.last_processed_index = last_processed_index
                row.total_records = total_records
                row.status = status
                row.updated_at = utcnow()
            else:
                row = CheckpointModel(
                    batch_id=batch_id,
                    last_processed_index=last_processed_index,
                    total_records=total_records,
                    status=status,
                    updated_at=utcnow()
                )
                session.add(row)

    def get_all_completed(self) -> List[BusinessProfile]:
        """Gets all completed profiles from the DB."""
        session = self.conn_mgr.get_session()
        try:
            rows = session.query(CompletedContactModel).order_by(CompletedContactModel.id).all()
            return [BusinessProfile(**self._convert_row_to_dict(r)) for r in rows]
        finally:
            session.close()

    def get_all_failed(self) -> List[Dict[str, Any]]:
        """Gets all failed records from the DB."""
        session = self.conn_mgr.get_session()
        try:
            rows = session.query(FailedRecordModel).order_by(FailedRecordModel.id).all()
            return [
                {
                    "id": r.id,
                    "npi": r.npi,
                    "company_name": r.company_name,
                    "website": r.website,
                    "error_message": r.error_message,
                    "raw_data": r.raw_data,
                    "failed_at": r.failed_at.isoformat() if r.failed_at else None
                }
                for r in rows
            ]
        finally:
            session.close()

    def get_all_retries(self) -> List[Dict[str, Any]]:
        """Gets all retry records from the DB."""
        session = self.conn_mgr.get_session()
        try:
            rows = session.query(RetryRecordModel).order_by(RetryRecordModel.id).all()
            return [
                {
                    "id": r.id,
                    "npi": r.npi,
                    "company_name": r.company_name,
                    "website": r.website,
                    "retry_count": r.retry_count,
                    "max_retries": r.max_retries,
                    "last_error": r.last_error,
                    "status": r.status,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None
                }
                for r in rows
            ]
        finally:
            session.close()

    def save_audit_trails(self, audit_records: List[Dict[str, Any]]) -> None:
        """Saves a batch of audit trail records to the database."""
        session = self.conn_mgr.get_session()
        try:
            from .database_manager import AuditTrailModel
            db_records = [AuditTrailModel(**rec) for rec in audit_records]
            session.add_all(db_records)
            session.commit()
            logger.info(f"[SQLiteRepository] Saved {len(audit_records)} audit trails to DB.")
        except Exception as e:
            session.rollback()
            logger.error(f"[SQLiteRepository] Failed to save audit trails: {e}")
            raise e
        finally:
            session.close()
