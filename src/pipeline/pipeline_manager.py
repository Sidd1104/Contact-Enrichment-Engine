"""
src/pipeline/pipeline_manager.py
================================
Sub-module controller interfacing CLI arguments with the PipelineRunner and Benchmark tools.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Dict, Any

from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager
from .pipeline_runner import PipelineRunner
from .benchmark import PipelineBenchmark
from .health_monitor import HealthMonitor
from .startup_validator import StartupValidator

logger = logging.getLogger(__name__)


class PipelineManager:
    """
    Acts as the entrypoint dispatcher for CLI run controls.
    """

    @staticmethod
    def run_pipeline(
        profile: str = "production",
        file_path: Optional[str] = None,
        export_dir: str = "data/export",
        limit: Optional[int] = None,
        show_dashboard: bool = True
    ) -> None:
        """Starts a standard ingestion pipeline run."""
        logger.info(f"[PipelineManager] Launching pipeline with profile={profile}, file={file_path}")
        
        # Override settings if limit is present
        custom_settings = {}
        if limit:
            # We can override batch size or enforce limits in context
            custom_settings["batch_size"] = min(limit, 20)

        runner = PipelineRunner(
            profile_name=profile,
            file_path=file_path,
            export_dir=export_dir,
            show_dashboard=show_dashboard
        )
        if limit:
            runner.context.set_value("total_records", limit)

        # Run asyncio loop
        try:
            report = asyncio.run(runner.run())
            print("\nIngestion completed successfully.")
            print(f"Total Processed: {report.get('records_count', {}).get('processed')}")
            print(f"Success Rate: {report.get('execution_summary', {}).get('success_rate') * 100:.2f}%")
        except Exception as e:
            logger.critical(f"[PipelineManager] Pipeline execution failed: {e}")
            sys.exit(1)

    @staticmethod
    def run_benchmark(file_path: str) -> None:
        """Starts the configuration benchmarking checks."""
        if not file_path:
            print("[ERROR] A valid Excel file path is required to run benchmarks.")
            return

        benchmark = PipelineBenchmark(file_path=file_path)
        try:
            report_file = asyncio.run(benchmark.execute_benchmarks())
            print(f"\nBenchmarking finalized successfully. Comparison report written to: {report_file}")
        except Exception as e:
            logger.error(f"[PipelineManager] Benchmarking crashed: {e}")

    @staticmethod
    def check_health() -> None:
        """Runs pre-flight validations and current resource health checks."""
        conn = ConnectionManager()
        validator = StartupValidator(conn)
        logger.info("[PipelineManager] Running pre-flight diagnostic validation...")
        valid, logs = validator.validate_all()
        
        print("\n=== STARTUP PRE-FLIGHT VALIDATION ===")
        for log in logs:
            print(log)
        print("=====================================")

        # Run system health diagnostics
        from .pipeline_context import PipelineContext
        ctx = PipelineContext()
        monitor = HealthMonitor()
        report = monitor.perform_health_check(ctx)
        
        print("\n=== SYSTEM RESOURCE HEALTH STATUS ===")
        print(f"CPU Usage:         {report['cpu_usage_percent']}%")
        print(f"RAM Usage:         {report['ram_usage_percent']}%")
        print(f"API Connectivity:  {'OK' if report['api_availability'] else 'OFFLINE'}")
        print(f"Database Status:   {'OK' if report['database_ok'] else 'OFFLINE'}")
        print("=====================================\n")
        conn.close()

    @staticmethod
    def show_status() -> None:
        """Queries and displays database statistics and last checkpoint parameters."""
        conn = ConnectionManager()
        db_mgr = DatabaseManager(conn)
        db_mgr.create_tables()
        repo = db_mgr.get_repository()
        
        try:
            completed = repo.get_all_completed()
            failed = repo.get_all_failed()
            retries = repo.get_all_retries()
            
            print("\n=== DATABASE ENRICHMENT STATUS ===")
            print(f"Completed Profiles:  {len(completed)}")
            print(f"Failed Records:      {len(failed)}")
            print(f"Pending Retries:     {len([r for r in retries if r.get('status') == 'pending'])}")
            print(f"Total Retries Saved: {len(retries)}")
            print("==================================\n")
        except Exception as e:
            logger.error(f"Could not read status from database: {e}")
        finally:
            conn.close()
import sys
from typing import Optional
