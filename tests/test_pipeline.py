"""
tests/test_pipeline.py
=======================
E2E integration and unit tests for the Master Pipeline Orchestrator.
Checks configuration profiles, startup diagnostics, E2E runs, checkpoints recovery, and benchmarks.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager
from src.pipeline.configuration_profiles import get_profile
from src.pipeline.startup_validator import StartupValidator
from src.pipeline.pipeline_context import PipelineContext
from src.pipeline.pipeline_orchestrator import PipelineOrchestrator
from src.pipeline.pipeline_runner import PipelineRunner
from src.pipeline.benchmark import PipelineBenchmark


@pytest.fixture
def temp_db_uri(tmp_path):
    """Temporary SQLite database path."""
    return f"sqlite:///{tmp_path}/pipeline_test.db"


@pytest.fixture
def dummy_excel_file(tmp_path):
    """Generates a dummy Excel file for testing."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    headers = ["npi", "company_name", "website", "address_line_1", "city", "state", "postal_code", "country"]
    ws.append(headers)
    ws.append(["1111", "Clinic One", "http://127.0.0.1:8099/c1", "1 St", "NY", "NY", "10001", "US"])
    ws.append(["2222", "Clinic Two", "http://127.0.0.1:8099/c2", "2 St", "NY", "NY", "10002", "US"])
    ws.append(["3333", "Clinic Three", "http://127.0.0.1:8099/c3", "3 St", "NY", "NY", "10003", "US"])
    file_path = tmp_path / "test_import.xlsx"
    wb.save(file_path)
    return str(file_path)


def test_profile_resolution():
    """Verifies profile configuration parameters."""
    dev = get_profile("development")
    assert dev.worker_count == 2
    assert dev.batch_size == 5

    prod = get_profile("production")
    assert prod.worker_count == 5
    assert prod.batch_size == 20

    # Fallback
    fallback = get_profile("non_existent_profile")
    assert fallback.profile_name == "production"


def test_startup_validation(temp_db_uri):
    """Verifies pre-flight startup diagnostics validations."""
    conn = ConnectionManager(custom_uri=temp_db_uri)
    validator = StartupValidator(conn)
    success, logs = validator.validate_all()
    
    # Startup validation should return true if basic environment and DB connections are okay
    assert success is True
    assert any("[OK] Python version" in log for log in logs)
    assert any("[OK] Database connection established" in log for log in logs)
    conn.close()


@pytest.mark.asyncio
async def test_pipeline_e2e_run(dummy_excel_file, temp_db_uri, tmp_path):
    """Runs a complete miniature E2E pipeline run with mocked search and AI fallbacks."""
    runner = PipelineRunner(
        profile_name="testing",
        file_path=dummy_excel_file,
        export_dir=str(tmp_path / "export"),
        db_uri=temp_db_uri,
        show_dashboard=False
    )

    # Mock search resolution
    from src.search.search_manager import SearchResolution
    mock_resolution = SearchResolution(
        query="Clinic One",
        resolved_url="http://127.0.0.1:8099/c1",
        confidence_score=0.9,
        provider_used="mock",
        status="success"
    )

    # Patch ScraperManager.scrape_website, SearchEngine.resolve_website and AIEnrichmentManager.enrich_profile
    mock_enrich = AsyncMock(side_effect=lambda profile, text="": profile)
    with patch("src.search.search_engine.SearchEngine.resolve_website", AsyncMock(return_value=mock_resolution)), \
         patch("src.scraper.scraper_manager.ScraperManager.scrape_website") as mock_scrape, \
         patch("src.ai.enrichment_manager.AIEnrichmentManager.enrich_profile", mock_enrich):
        
        # Scraper mock output structured contact
        from src.extractor.structured_contact import StructuredContact
        mock_contact = StructuredContact(
            business_name="Clinic Mock",
            official_website="http://mock.com",
            emails=["mock@mock.com"],
            phones=["111-222-3333"]
        )
        mock_scrape.return_value = mock_contact

        report = await runner.run()
        
        assert report is not None
        assert report["records_count"]["processed"] == 3
        assert report["records_count"]["completed_success"] == 1
        assert report["records_count"]["duplicates_merged"] == 2
        assert report["execution_summary"]["status"] == "completed"

        # Verify exported files exist
        export_dir = Path(tmp_path / "export")
        assert (export_dir / "completed_contacts.csv").exists()
        assert (export_dir / "completed_contacts.xlsx").exists()
        assert (export_dir / "summary_report.md").exists()


@pytest.mark.asyncio
async def test_checkpoint_recovery(dummy_excel_file, temp_db_uri, tmp_path):
    """Verifies that the orchestrator resumes from database checkpoints on recovery."""
    conn = ConnectionManager(custom_uri=temp_db_uri)
    db_mgr = DatabaseManager(conn)
    db_mgr.create_tables()
    repo = db_mgr.get_repository()

    # Prepopulate a database checkpoint: batch index = 1, meaning batch 1 was completed, start at batch 2 (index 1)
    batch_id = f"{Path(dummy_excel_file).name}_Sheet1"
    repo.save_checkpoint(batch_id, last_processed_index=1, total_records=3, status="in_progress")
    conn.close()

    runner = PipelineRunner(
        profile_name="testing",
        file_path=dummy_excel_file,
        export_dir=str(tmp_path / "export"),
        db_uri=temp_db_uri,
        show_dashboard=False
    )
    
    # Override context profile batch size to 1, yielding 3 batches of 1 record
    runner.context.profile.batch_size = 1

    from src.search.search_manager import SearchResolution
    mock_resolution = SearchResolution(
        query="Clinic Mock",
        resolved_url="http://mock.com",
        confidence_score=0.9,
        provider_used="mock",
        status="success"
    )

    mock_enrich = AsyncMock(side_effect=lambda profile, text="": profile)
    with patch("src.search.search_engine.SearchEngine.resolve_website", AsyncMock(return_value=mock_resolution)), \
         patch("src.scraper.scraper_manager.ScraperManager.scrape_website") as mock_scrape, \
         patch("src.ai.enrichment_manager.AIEnrichmentManager.enrich_profile", mock_enrich):
        
        from src.extractor.structured_contact import StructuredContact
        mock_scrape.return_value = StructuredContact(
            business_name="Clinic Mock",
            official_website="http://mock.com",
            emails=["mock@mock.com"]
        )

        report = await runner.run()
        
        # Check that we skipped batch 1. The database checkpoint=1, so we resume at batch 2.
        # Cumulative progress is 3, retry_pending count is 1
        assert report["records_count"]["processed"] == 3
        assert report["records_count"]["retry_pending"] == 1
        assert report["execution_summary"]["status"] == "completed"


@pytest.mark.asyncio
async def test_benchmark_runner(dummy_excel_file, tmp_path):
    """Verifies that the benchmarking tool executes runs and outputs the Markdown comparison report."""
    benchmark = PipelineBenchmark(file_path=dummy_excel_file, export_dir=str(tmp_path / "benchmarks"))
    
    # Run mock benchmarks
    from src.search.search_manager import SearchResolution
    mock_resolution = SearchResolution(query="Mock", resolved_url="http://mock.com", confidence_score=0.9)

    mock_enrich = AsyncMock(side_effect=lambda profile, text="": profile)
    with patch("src.search.search_engine.SearchEngine.resolve_website", AsyncMock(return_value=mock_resolution)), \
         patch("src.scraper.scraper_manager.ScraperManager.scrape_website") as mock_scrape, \
         patch("src.ai.enrichment_manager.AIEnrichmentManager.enrich_profile", mock_enrich):
        
        from src.extractor.structured_contact import StructuredContact
        mock_scrape.return_value = StructuredContact(business_name="Mock", official_website="http://mock.com")

        report_file = await benchmark.execute_benchmarks()
        
        assert Path(report_file).exists()
        with open(report_file, "r") as f:
            content = f.read()
        assert "Benchmark Report" in content
        assert "Concurrency Performance Matrix" in content
