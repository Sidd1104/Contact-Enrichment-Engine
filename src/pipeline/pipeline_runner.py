"""
src/pipeline/pipeline_runner.py
==============================
Main runner script wrapping startup validation, signal handlers,
live dashboard rendering, and orchestrator execution.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any, Optional

from src.database.connection_manager import ConnectionManager
from .pipeline_context import PipelineContext
from .pipeline_events import PipelineEventBus, PipelineEventType
from .pipeline_orchestrator import PipelineOrchestrator
from .startup_validator import StartupValidator
from .shutdown_manager import ShutdownManager
from .dashboard import Dashboard
from .health_monitor import HealthMonitor

logger = logging.getLogger(__name__)


class PipelineRunner:
    """
    Coordinates pre-flight checks, signal traps, and orchestrator loop running.
    """

    def __init__(
        self,
        profile_name: str = "production",
        file_path: Optional[str] = None,
        export_dir: str = "data/export",
        db_uri: Optional[str] = None,
        reset_checkpoint: bool = False,
        show_dashboard: bool = True
    ) -> None:
        self.profile_name = profile_name
        self.file_path = file_path
        self.export_dir = export_dir
        self.db_uri = db_uri
        self.reset_checkpoint = reset_checkpoint
        self.show_dashboard = show_dashboard

        # Core context/bus
        self.context = PipelineContext(profile_name=self.profile_name)
        self.event_bus = PipelineEventBus()
        self.conn_mgr = ConnectionManager(custom_uri=self.db_uri)

        self.dashboard = Dashboard(disabled=not self.show_dashboard)
        self.shutdown_mgr = ShutdownManager()
        self.orchestrator: Optional[PipelineOrchestrator] = None

    def _bind_dashboard(self) -> None:
        """Hooks dashboard rendering to state-change events."""
        health_checker = HealthMonitor()

        def update_ui(*args: Any, **kwargs: Any) -> None:
            # Sample health stats
            health_report = health_checker.perform_health_check(
                context=self.context,
                queue_size=self.context.queue_depth,
                db_alive=True,
                browser_active=self.context.browser_launches > 0
            )
            # Render stats
            self.dashboard.render(self.context.get_all_stats(), health_report)

        # Register update callbacks
        self.event_bus.subscribe(PipelineEventType.PIPELINE_STARTED, update_ui)
        self.event_bus.subscribe(PipelineEventType.BATCH_STARTED, update_ui)
        self.event_bus.subscribe(PipelineEventType.BATCH_COMPLETED, update_ui)
        self.event_bus.subscribe(PipelineEventType.SEARCH_COMPLETED, update_ui)
        self.event_bus.subscribe(PipelineEventType.SCRAPING_COMPLETED, update_ui)
        self.event_bus.subscribe(PipelineEventType.VALIDATION_COMPLETED, update_ui)
        self.event_bus.subscribe(PipelineEventType.DATABASE_SAVED, update_ui)
        self.event_bus.subscribe(PipelineEventType.EXPORT_FINISHED, update_ui)
        self.event_bus.subscribe(PipelineEventType.PIPELINE_FINISHED, update_ui)
        self.event_bus.subscribe(PipelineEventType.PIPELINE_FAILED, update_ui)

    async def run(self) -> Dict[str, Any]:
        """
        Runs pre-flight validation and boots the main orchestrator task.
        """
        if self.reset_checkpoint:
            logger.warning("[PipelineRunner] Resetting database and checkpoints as requested...")
            from src.database.database_manager import DatabaseManager
            db_mgr = DatabaseManager(self.conn_mgr)
            db_mgr.drop_all_tables()
            db_mgr.create_tables()

            # Purge local JSON cache files to clear mock/fake URLs
            import os
            from pathlib import Path
            for filename in ["search_cache.json", "crawl_cache.json", "contact_cache.json", "worker_queue_state.json"]:
                cache_path = Path("data/temp") / filename
                if cache_path.exists():
                    try:
                        os.remove(cache_path)
                        logger.warning(f"[PipelineRunner] Deleted cache file: {filename}")
                    except Exception as e:
                        logger.error(f"[PipelineRunner] Failed to delete cache file {filename}: {e}")

        # 1. Startup pre-flight validation
        validator = StartupValidator(self.conn_mgr)
        valid, logs = validator.validate_all()
        if not valid:
            logger.critical("[PipelineRunner] Pre-flight startup diagnostics failed. Aborting run.")
            print("\n==========================================")
            print("  STARTUP DIAGNOSTICS FAILURE")
            print("==========================================")
            for log in logs:
                print(log)
            print("==========================================\n")
            raise RuntimeError("Pipeline pre-flight validation failed.")

        # 2. Register Signal handlers for graceful exits
        def sync_shutdown_hook() -> None:
            logger.warning("\n[PipelineRunner] Interruption detected. Initiating graceful database-to-Excel backup...")
            if self.orchestrator:
                self.orchestrator.stop()
                if self.orchestrator.export_mgr:
                    excel_path = self.orchestrator.file_path
                    if not excel_path:
                        excel_path = "us_investors_enriched.xlsx"
                    try:
                        self.orchestrator.export_mgr.update_original_excel(excel_path)
                        logger.info("[PipelineRunner] In-place Excel backup completed successfully.")
                    except Exception as e:
                        logger.error(f"[PipelineRunner] Failed to update Excel backup during shutdown: {e}")

        self.shutdown_mgr.register_signal_handlers(sync_shutdown_hook)

        # 3. Bind events dashboard
        if self.show_dashboard:
            self._bind_dashboard()

        # 4. Instantiate and run orchestrator
        self.orchestrator = PipelineOrchestrator(
            context=self.context,
            event_bus=self.event_bus,
            connection_manager=self.conn_mgr,
            file_path=self.file_path,
            export_dir=self.export_dir
        )

        # Run E2E pipeline
        report = await self.orchestrator.run()
        return report
