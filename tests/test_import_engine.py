"""
tests/test_import_engine.py
============================
Unit tests for the Import Engine (Phase 2B).

Covers:
  - Excel header dynamic schema mapping.
  - Rejecting duplicate headers.
  - Mapping row values and cell cleaning (e.g. NaN -> empty string).
  - Smart filtering (skipping rows where both email and phone are present).
  - In-memory duplicate NPI check.
  - Checkpoint serialization, loading, and clear operations.
  - Batching division, offsets, and generators.
  - Statistics reports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.schema_detector import SchemaDetector
from src.importer.row_mapper import RowMapper
from src.importer.filters import ImportFilter, is_empty_value
from src.importer.checkpoint import CheckpointSystem
from src.importer.batch_manager import BatchManager
from src.importer.statistics import ImportStatistics


# =============================================================================
# Test: is_empty_value Heuristics
# =============================================================================

def test_is_empty_value():
    assert is_empty_value(None) is True
    assert is_empty_value(float("nan")) is True
    assert is_empty_value("") is True
    assert is_empty_value("   ") is True
    assert is_empty_value("nan") is True
    assert is_empty_value("n/a") is True
    assert is_empty_value("-") is True
    assert is_empty_value("valid_string") is False
    assert is_empty_value(12345) is False


# =============================================================================
# Test: SchemaDetector
# =============================================================================

class TestSchemaDetector:
    """Test dynamic header mapping rules."""

    def test_detector_valid_columns(self):
        headers = [
            "NPI", "First Name", "Last name", "Address line 1",
            "City", "State", "Postal code", "Country", "Phone", "Email"
        ]
        detector = SchemaDetector(headers)
        mapping = detector.detect_mapping()

        assert mapping["npi"] == "NPI"
        assert mapping["first_name"] == "First Name"
        assert mapping["last_name"] == "Last name"
        assert mapping["address_line_1"] == "Address line 1"
        assert mapping["email"] == "Email"
        assert mapping["phone"] == "Phone"

    def test_detector_duplicate_headers_raises(self):
        headers = ["NPI", "First Name", "first_name"]
        with pytest.raises(ValueError, match="Duplicate column headers detected"):
            SchemaDetector(headers)

    def test_detector_partial_columns(self):
        headers = ["npi", "email", "street address", "zip_code"]
        detector = SchemaDetector(headers)
        mapping = detector.detect_mapping()

        assert mapping["npi"] == "npi"
        assert mapping["email"] == "email"
        assert mapping["address_line_1"] == "street address"
        assert mapping["postal_code"] == "zip_code"

    def test_report_generation(self):
        headers = ["NPI", "email", "unrelated_column_xyz"]
        detector = SchemaDetector(headers)
        report = detector.generate_report()

        assert report["total_columns"] == 3
        assert report["mapped_count"] == 2
        assert report["unmapped_count"] == 1
        assert "unrelated_column_xyz" in report["unmapped_columns"]


# =============================================================================
# Test: RowMapper
# =============================================================================

class TestRowMapper:
    """Test mapping raw rows into standardized keys."""

    def test_row_mapping(self):
        mapping = {
            "npi": "NPI",
            "first_name": "First Name",
            "email": "Email",
            "phone": "Phone",
        }
        raw_row = {
            "NPI": "1000000001",
            "First Name": "John",
            "Email": "john@test.com",
            "Phone": None,
            "extra_key": "ignored_in_standard"
        }
        mapper = RowMapper(mapping)
        mapped = mapper.map_row(raw_row)

        assert mapped["npi"] == "1000000001"
        assert mapped["first_name"] == "John"
        assert mapped["email"] == "john@test.com"
        assert mapped["phone"] == ""  # converted None to empty string
        assert mapped["city"] == ""   # unmapped fields initialized to empty string
        assert mapped["raw_data"] == raw_row


# =============================================================================
# Test: ImportFilter (Deduplication, Empty, Smart Filtering)
# =============================================================================

class TestImportFilter:
    """Test smart filtering and deduplication rules."""

    def test_is_row_empty(self):
        row_filter = ImportFilter()
        mapping = {"npi": "NPI", "email": "Email"}
        
        empty_row = {"NPI": None, "Email": "nan", "unmapped": "val"}
        assert row_filter.is_row_empty(empty_row, mapping) is True
        
        non_empty_row = {"NPI": "123", "Email": "nan"}
        assert row_filter.is_row_empty(non_empty_row, mapping) is False

    def test_is_fully_enriched_smart_filtering(self):
        row_filter = ImportFilter()

        # Both present -> fully enriched -> Skip queue
        row1 = {"email": "test@test.com", "phone": "123-456"}
        assert row_filter.is_fully_enriched(row1) is True

        # Missing phone -> not fully enriched -> Needs queue
        row2 = {"email": "test@test.com", "phone": ""}
        assert row_filter.is_fully_enriched(row2) is False

        # Missing email -> not fully enriched -> Needs queue
        row3 = {"email": "-", "phone": "123-456"}
        assert row_filter.is_fully_enriched(row3) is False

        # Both missing -> Needs queue
        row4 = {"email": "", "phone": ""}
        assert row_filter.is_fully_enriched(row4) is False

    def test_duplicate_primary_key_npi(self):
        row_filter = ImportFilter()
        
        row1 = {"npi": "1000000001"}
        row2 = {"npi": "1000000001"}
        row3 = {"npi": "1000000002"}

        assert row_filter.is_duplicate(row1) is False
        assert row_filter.is_duplicate(row2) is True  # Duplicate
        assert row_filter.is_duplicate(row3) is False


# =============================================================================
# Test: CheckpointSystem
# =============================================================================

class TestCheckpointSystem:
    """Test saving, loading, and recovery mechanics."""

    def test_checkpoint_lifecycle(self):
        with TemporaryDirectory() as temp_dir:
            sys_chk = CheckpointSystem(temp_dir)
            file_name = "test_file.xlsx"
            sheet_name = "Investor Contacts"

            # Check fresh start
            assert sys_chk.load_checkpoint(file_name, sheet_name) is None

            # Save state
            sys_chk.save_checkpoint(
                file_name=file_name,
                sheet_name=sheet_name,
                last_batch_index=4,
                processed_count=400,
                skipped_count=50,
                queued_count=350,
            )

            # Load state and verify
            chk = sys_chk.load_checkpoint(file_name, sheet_name)
            assert chk is not None
            assert chk["last_batch_index"] == 4
            assert chk["processed_count"] == 400
            assert chk["skipped_count"] == 50
            assert chk["queued_count"] == 350
            assert "timestamp" in chk

            # Clear state
            sys_chk.clear_checkpoint(file_name, sheet_name)
            assert sys_chk.load_checkpoint(file_name, sheet_name) is None


# =============================================================================
# Test: BatchManager
# =============================================================================

class TestBatchManager:
    """Test batch partitioning and generation offsets."""

    def test_batch_division(self):
        records = [{"npi": str(i)} for i in range(25)]
        
        # Batch size 10 -> Should produce 3 batches (10, 10, 5)
        bm = BatchManager(records, batch_size=10)
        assert bm.total_batches == 3

        batches = list(bm.generate_batches())
        assert len(batches) == 3
        
        # Verify first batch
        idx1, batch1 = batches[0]
        assert idx1 == 0
        assert len(batch1) == 10
        assert batch1[0]["npi"] == "0"
        assert batch1[9]["npi"] == "9"

        # Verify last batch
        idx3, batch3 = batches[2]
        assert idx3 == 2
        assert len(batch3) == 5
        assert batch3[0]["npi"] == "20"
        assert batch3[4]["npi"] == "24"

    def test_batch_skip_past_checkpoint(self):
        records = [{"npi": str(i)} for i in range(25)]
        bm = BatchManager(records, batch_size=10)

        # Resume from batch index 1 (skips batch 0)
        batches = list(bm.generate_batches(start_batch_index=1))
        assert len(batches) == 2
        idx, batch = batches[0]
        assert idx == 1
        assert len(batch) == 10
        assert batch[0]["npi"] == "10"


# =============================================================================
# Test: Statistics
# =============================================================================

def test_statistics_generation():
    with TemporaryDirectory() as temp_dir:
        stats_file = Path(temp_dir) / "stats.json"
        sys_stats = ImportStatistics(stats_file)

        report = sys_stats.generate_report(
            file_name="us_investors.xlsx",
            sheet_name="Contacts",
            total_records=1000,
            completed_records=400,
            queued_records=550,
            duplicates_count=50,
            batch_size=100,
            estimated_sec_per_record=2.0
        )

        assert report["counts"]["total_records"] == 1000
        assert report["counts"]["completed_records"] == 400
        assert report["counts"]["eligible_records"] == 550
        assert report["batching"]["batch_size"] == 100
        assert report["batching"]["batch_count"] == 6
        assert report["estimation"]["estimated_processing_seconds"] == 1100.0

        # Check file was written
        assert stats_file.exists()
        with open(stats_file, "r") as f:
            data = json.load(f)
        assert data["counts"]["total_records"] == 1000
