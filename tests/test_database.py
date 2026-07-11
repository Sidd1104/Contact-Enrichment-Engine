"""
tests/test_database.py
======================
Unit and integration tests for the Phase 2G Persistence Layer.
Tests transactions, repository methods, duplicate detection, bulk writes, and retries.
"""

from __future__ import annotations

import os
import json
import pytest
from pathlib import Path
from datetime import datetime

from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager, CompletedContactModel
from src.database.transaction_manager import TransactionManager
from src.database.bulk_writer import BulkWriter, DatabaseMetrics
from src.database.retry_repository import RetryRepository
from src.validator.business_profile_validator import BusinessProfile


@pytest.fixture
def temp_conn_mgr():
    """Initializes an in-memory SQLite connection manager for tests."""
    # Use in-memory DB to guarantee test isolation
    conn = ConnectionManager(custom_uri="sqlite:///:memory:")
    db_mgr = DatabaseManager(conn)
    db_mgr.create_tables()
    yield conn
    conn.close()


@pytest.fixture
def test_metrics_file(tmp_path):
    """Temporary file path for database metrics."""
    return str(tmp_path / "test_database_metrics.json")


def test_table_initialization(temp_conn_mgr):
    """Verifies that database schemas are initialized correctly."""
    session = temp_conn_mgr.get_session()
    # Query check
    try:
        # Table should be empty but exist
        res = session.query(CompletedContactModel).all()
        assert len(res) == 0
    finally:
        session.close()


def test_transaction_commit(temp_conn_mgr):
    """Verifies TransactionManager commits successfully on no exceptions."""
    with TransactionManager(temp_conn_mgr) as session:
        contact = CompletedContactModel(
            npi="12345",
            business_name="Test Clinic",
            official_website="http://test.com",
            emails=["contact@test.com"]
        )
        session.add(contact)

    # Check database
    session = temp_conn_mgr.get_session()
    try:
        res = session.query(CompletedContactModel).first()
        assert res is not None
        assert res.business_name == "Test Clinic"
        assert res.emails == ["contact@test.com"]
    finally:
        session.close()


def test_transaction_rollback(temp_conn_mgr):
    """Verifies TransactionManager rolls back modifications on exceptions."""
    with pytest.raises(ValueError):
        with TransactionManager(temp_conn_mgr) as session:
            contact = CompletedContactModel(
                npi="12345",
                business_name="Rollback Clinic",
                official_website="http://rollback.com"
            )
            session.add(contact)
            raise ValueError("Forced error to test rollback")

    # Check database
    session = temp_conn_mgr.get_session()
    try:
        res = session.query(CompletedContactModel).filter(
            CompletedContactModel.business_name == "Rollback Clinic"
        ).first()
        assert res is None
    finally:
        session.close()


def test_duplicate_merging_and_upsert(temp_conn_mgr):
    """Verifies that inserting a profile with an existing website merges data."""
    db_mgr = DatabaseManager(temp_conn_mgr)
    repo = db_mgr.get_repository()

    profile1 = BusinessProfile(
        business_name="Alpha Clinic",
        official_website="http://alpha.com",
        emails=["alpha1@clinic.com"],
        phones=["111-222-3333"],
        confidence=0.7
    )
    
    # Save first profile
    inserts, updates = repo.save_completed_batch([profile1])
    assert inserts == 1
    assert updates == 0

    # Create duplicate profile with new email, phone, and higher confidence
    profile2 = BusinessProfile(
        business_name="Alpha Clinic Refined",
        official_website="http://alpha.com",
        emails=["alpha2@clinic.com", "alpha1@clinic.com"],
        phones=["444-555-6666"],
        confidence=0.85,
        social_links={"linkedin": "http://linkedin.com/alpha"}
    )

    # Save second profile
    inserts2, updates2 = repo.save_completed_batch([profile2])
    assert inserts2 == 0
    assert updates2 == 1

    # Verify merged data
    completed = repo.get_all_completed()
    assert len(completed) == 1
    
    merged = completed[0]
    # Set assertion checks for lists (order insensitive)
    assert set(merged.emails) == {"alpha1@clinic.com", "alpha2@clinic.com"}
    assert set(merged.phones) == {"111-222-3333", "444-555-6666"}
    assert merged.confidence == 0.85
    assert merged.social_links["linkedin"] == "http://linkedin.com/alpha"
    assert merged.extraction_method == "Merged"


def test_bulk_writer_batching_and_metrics(temp_conn_mgr, test_metrics_file):
    """Verifies BulkWriter correctly batches operations and writes metrics to disk."""
    db_mgr = DatabaseManager(temp_conn_mgr)
    repo = db_mgr.get_repository()
    
    writer = BulkWriter(repo, batch_size=2, metrics_file=test_metrics_file)

    profiles = [
        BusinessProfile(business_name="C1", official_website="http://c1.com", emails=["c1@c.com"]),
        BusinessProfile(business_name="C2", official_website="http://c2.com"),
        BusinessProfile(business_name="C3", official_website="http://c3.com"),
    ]

    ins, upd = writer.write_profiles(profiles)
    assert ins == 3
    assert upd == 0

    # Verify metrics file on disk
    metrics_path = Path(test_metrics_file)
    assert metrics_path.exists()

    with open(metrics_path, "r") as f:
        data = json.load(f)

    assert data["counts"]["total_inserts"] == 3
    assert data["counts"]["total_updates"] == 0
    assert data["counts"]["failed_writes"] == 0
    assert data["performance"]["sessions_count"] == 2 # 3 items with batch size 2 yields 2 write calls


def test_retry_repository_workflow(temp_conn_mgr):
    """Tests the state transition machine of retry and failed records."""
    db_mgr = DatabaseManager(temp_conn_mgr)
    repo = db_mgr.get_repository()
    retry_repo = RetryRepository(repo)

    # 1. Add transient failure
    record = {"npi": "9999", "company_name": "Transient Clinic", "website": "http://transient.com"}
    retry_repo.persist_retry(record, "Connection timeout", max_retries=2)

    # Check pending
    pending = retry_repo.fetch_pending_retries()
    assert len(pending) == 1
    assert pending[0]["company_name"] == "Transient Clinic"
    assert pending[0]["_retry_count"] == 1

    # 2. Simulate second failure (exceeds max_retries of 2)
    retry_id = pending[0]["_retry_id"]
    retry_repo.process_retry_failure(retry_id, "Connection timeout again")

    # Pending count should be 0 because status transitions to 'failed' and clones to failed table
    pending_after = retry_repo.fetch_pending_retries()
    assert len(pending_after) == 0

    # Failed records should have 1 item
    failed = repo.get_all_failed()
    assert len(failed) == 1
    assert failed[0]["company_name"] == "Transient Clinic"
    assert "Max retries" in failed[0]["error_message"]


def test_checkpoints_restart(temp_conn_mgr):
    """Verifies that processing checkpoints can be saved and read."""
    db_mgr = DatabaseManager(temp_conn_mgr)
    repo = db_mgr.get_repository()

    # Save checkpoint
    repo.save_checkpoint("batch_abc", last_processed_index=15, total_records=100, status="in_progress")

    # Get checkpoint
    cp = repo.get_checkpoint("batch_abc")
    assert cp is not None
    assert cp["last_processed_index"] == 15
    assert cp["total_records"] == 100
    assert cp["status"] == "in_progress"
