"""
tests/test_exporter.py
======================
Unit and integration tests for the Phase 2G Export Engine.
Tests CSV writing, Excel sheets formatting, ReportGenerator, and ExportManager orchestration.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
import pandas as pd

from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager
from src.exporter.export_metrics import ExportMetrics
from src.exporter.csv_exporter import CSVExporter
from src.exporter.excel_exporter import ExcelExporter
from src.exporter.report_generator import ReportGenerator
from src.exporter.export_manager import ExportManager
from src.validator.business_profile_validator import BusinessProfile


@pytest.fixture
def temp_export_dir(tmp_path):
    """Returns a temporary path for export destinations."""
    return tmp_path / "export"


@pytest.fixture
def test_export_metrics_file(tmp_path):
    """Temporary file path for export metrics."""
    return str(tmp_path / "test_export_metrics.json")


@pytest.fixture
def sample_profiles():
    """Returns a list of mock business profiles for exporting."""
    return [
        BusinessProfile(
            business_name="Beta Medical Center",
            official_website="http://beta.com",
            emails=["info@beta.com"],
            phones=["(212) 555-0199"],
            social_links={"linkedin": "http://linkedin.com/beta"},
            address="123 Broad St, NY",
            extraction_method="HTTP",
            confidence=0.88
        ),
        BusinessProfile(
            business_name="Gamma Care",
            official_website="http://gamma.org",
            emails=["support@gamma.org", "billing@gamma.org"],
            phones=[],
            social_links={},
            address="456 Wall St, NY",
            extraction_method="Merged",
            confidence=0.75
        )
    ]


def test_csv_exporter(sample_profiles, temp_export_dir, test_export_metrics_file):
    """Verifies that CSVExporter writes RFC-4180 tabular data correctly."""
    metrics = ExportMetrics(test_export_metrics_file)
    exporter = CSVExporter(metrics)
    csv_file = str(temp_export_dir / "contacts.csv")

    exporter.export(sample_profiles, csv_file)

    assert Path(csv_file).exists()

    # Read and inspect
    df = pd.read_csv(csv_file).fillna("")
    assert len(df) == 2
    assert list(df["business_name"]) == ["Beta Medical Center", "Gamma Care"]
    assert list(df["emails"]) == ["info@beta.com", "support@gamma.org; billing@gamma.org"]
    assert list(df["social_linkedin"]) == ["http://linkedin.com/beta", ""]


def test_excel_exporter(sample_profiles, temp_export_dir, test_export_metrics_file):
    """Verifies that ExcelExporter writes multi-column Excel spreadsheet structures."""
    metrics = ExportMetrics(test_export_metrics_file)
    exporter = ExcelExporter(metrics)
    xlsx_file = str(temp_export_dir / "contacts.xlsx")

    exporter.export(sample_profiles, xlsx_file)

    assert Path(xlsx_file).exists()

    # Read Excel with pandas
    df = pd.read_excel(xlsx_file, sheet_name="Enriched Contacts")
    assert len(df) == 2
    assert list(df["Business Name"]) == ["Beta Medical Center", "Gamma Care"]
    assert list(df["Emails"]) == ["info@beta.com", "support@gamma.org, billing@gamma.org"]


def test_report_generators(temp_export_dir):
    """Tests the generation of summary, duplicate, and failed markdown reports."""
    summary_path = str(temp_export_dir / "summary.md")
    failed_path = str(temp_export_dir / "failed.md")
    dup_path = str(temp_export_dir / "dup.md")

    # Generate
    ReportGenerator.generate_summary_report(
        completed_count=5, failed_count=2, retry_count=1, duplicate_count=3, filepath=summary_path
    )
    ReportGenerator.generate_failed_report(
        [{"npi": "1", "company_name": "FC", "website": "http://f.com", "error_message": "Timeout"}], failed_path
    )
    ReportGenerator.generate_duplicate_report(
        [{"npi": "2", "company_name": "DC", "website": "http://d.com", "resolution": "Merged"}], dup_path
    )

    assert Path(summary_path).exists()
    assert Path(failed_path).exists()
    assert Path(dup_path).exists()

    # Basic contents inspection
    with open(summary_path, "r") as f:
        summary_content = f.read()
    assert "Completed / Enriched Records | 5" in summary_content
    assert "Duplicates Merged | 3" in summary_content

    with open(failed_path, "r") as f:
        failed_content = f.read()
    assert "FC" in failed_content
    assert "Timeout" in failed_content


def test_export_manager_integration(sample_profiles, temp_export_dir, test_export_metrics_file):
    """Verifies that ExportManager queries repository and runs all exporters and reports."""
    conn = ConnectionManager(custom_uri="sqlite:///:memory:")
    db_mgr = DatabaseManager(conn)
    db_mgr.create_tables()
    repo = db_mgr.get_repository()

    # Prepopulate repository
    repo.save_completed_batch(sample_profiles)
    repo.save_failed_batch(
        [{"npi": "88", "company_name": "Failed Inc", "website": "http://failed.org"}],
        ["HTTP 404 Error"]
    )
    repo.save_retry_batch(
        [{"npi": "99", "company_name": "Retry Corp", "website": "http://retry.org"}],
        ["Rate limit exceeded"]
    )

    # Initialize manager
    manager = ExportManager(repo, metrics_file=test_export_metrics_file)
    results = manager.export_all(str(temp_export_dir))

    # Assert paths
    assert "completed_csv" in results
    assert "completed_excel" in results
    assert "failed_csv" in results
    assert "summary_report" in results
    assert "failed_report" in results
    assert "duplicate_report" in results
    assert "statistics_report" in results

    for key, path in results.items():
        assert Path(path).exists()

    # Check stats report
    with open(results["statistics_report"], "r") as f:
        stats_content = f.read()
    assert "Database Ingestion Diagnostics" in stats_content

    conn.close()
