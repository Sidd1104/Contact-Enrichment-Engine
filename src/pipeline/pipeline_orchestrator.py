"""
src/pipeline/pipeline_orchestrator.py
======================================
Coordinates the complete pipeline flow.
Integrates Import, Search, Scraping Worker Pool, Validation, AI Fallbacks, DB, and Exporters.
Manages resume points, health telemetry checks, signal signals, and event publishing.
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from src.importer.importer import ImportEngine
from src.search.search_engine import SearchEngine
from src.search.search_manager import SearchManager
from src.workers.task import Task
from src.workers.worker_pool import WorkerPool
from src.scraper.scraper_manager import ScraperManager
from src.validator.validation_manager import ValidationManager
from src.validator.business_profile_validator import BusinessProfile
from src.ai.enrichment_manager import AIEnrichmentManager
from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager
from src.database.bulk_writer import BulkWriter
from src.exporter.export_manager import ExportManager

from .pipeline_context import PipelineContext
from .pipeline_state import PipelineState
from .pipeline_events import PipelineEventBus, PipelineEventType
from .health_monitor import HealthMonitor
from .performance_profiler import PerformanceProfiler
from .pipeline_metrics import PipelineMetrics

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the lifecycle and execution of all pipeline sub-modules.
    """

    def __init__(
        self,
        context: PipelineContext,
        event_bus: PipelineEventBus,
        connection_manager: ConnectionManager,
        file_path: Optional[str] = None,
        export_dir: str = "data/export"
    ) -> None:
        self.context = context
        self.event_bus = event_bus
        self.conn_mgr = connection_manager
        self.file_path = file_path
        self.export_dir = export_dir

        self.db_mgr = DatabaseManager(self.conn_mgr)
        self.health_monitor = HealthMonitor()

        # Control hooks
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Start unpaused
        self._stop_requested = False

        # Submanagers
        self.scraper_mgr: Optional[ScraperManager] = None
        self.ai_mgr: Optional[AIEnrichmentManager] = None
        self.search_mgr: Optional[SearchManager] = None
        self.bulk_writer: Optional[BulkWriter] = None
        self.export_mgr: Optional[ExportManager] = None
        self.repo: Optional[Any] = None

    def pause(self) -> None:
        """Pauses pipeline execution after the current batch finishes."""
        self._pause_event.clear()
        self.context.state = PipelineState.PAUSED
        logger.warning("[Orchestrator] Pause requested. The pipeline will halt after the current batch finishes.")

    def resume(self) -> None:
        """Resumes a paused pipeline."""
        self._pause_event.set()
        self.context.state = PipelineState.RUNNING
        logger.info("[Orchestrator] Resuming pipeline execution.")

    def stop(self) -> None:
        """Stops the pipeline after the current batch."""
        self._stop_requested = True
        self.resume()  # Ensure it is not blocked on pause event
        self.context.state = PipelineState.STOPPED
        logger.warning("[Orchestrator] Stop requested. Finalizing current batch and aborting.")

    async def _init_components(self) -> None:
        """Bootstraps sub-module instances."""
        logger.info("[Orchestrator] Initializing module components...")
        self.db_mgr.create_tables()
        self.repo = self.db_mgr.get_repository()

        # Retrieve configurations from context profile parameters
        profile = self.context.profile
        self.bulk_writer = BulkWriter(self.repo, batch_size=profile.batch_size, max_retries=profile.retry_limit)
        self.export_mgr = ExportManager(self.repo)

        # Scraper/Browser
        self.scraper_mgr = ScraperManager(strict_robots=False)

        # AI fallback
        self.ai_mgr = AIEnrichmentManager()
        
        # Resolve AI order and Gemini config
        from src.search.search_provider import GeminiSearchProvider, BingSearchProvider
        from src.search.provider_router import ProviderRouter
        from src.search.cache_manager import FileSearchCache
        from src.search.metrics import SearchMetrics
        from src.search.search_engine import SearchEngine

        gemini_prov = GeminiSearchProvider()
        bing_prov = BingSearchProvider()
        search_router = ProviderRouter([gemini_prov, bing_prov], ["gemini_grounding", "bing"])
        
        search_cache = FileSearchCache()
        search_metrics = SearchMetrics()
        search_engine = SearchEngine(search_router, cache=search_cache, metrics=search_metrics)
        self.search_mgr = SearchManager(search_engine, max_concurrency=profile.max_concurrency)

    async def _cleanup_components(self) -> None:
        """Safely disposes Playwright browsers and database connections."""
        logger.info("[Orchestrator] Disposing components...")
        if self.scraper_mgr:
            if self.scraper_mgr.browser_scraper:
                self.context.set_value("browser_launches", self.scraper_mgr.browser_scraper.launches_count)
            await self.scraper_mgr.close()
        if self.ai_mgr:
            await self.ai_mgr.close()
        # Dispose connection manager
        self.conn_mgr.close()

    async def run(self) -> Dict[str, Any]:
        """
        Executes the main orchestration loop.
        """
        self.context.state = PipelineState.STARTING
        self.context.start_time = time.time()
        self.event_bus.publish(PipelineEventType.PIPELINE_STARTED)

        try:
            await self._init_components()
            
            # 1. Initialize Ingestion Engine
            importer = ImportEngine(batch_size=self.context.profile.batch_size)
            target_file = Path(self.file_path) if self.file_path else importer.reader.detect_primary_file()
            sheet_name = importer.reader.detect_primary_sheet(target_file)
            
            # Deriving Batch ID for DB checkpoints
            batch_id = f"{target_file.name}_{sheet_name}"
            
            # 2. Check DB checkpoints to see if we should resume
            db_checkpoint = self.repo.get_checkpoint(batch_id)
            start_batch_index = 0
            processed_records = 0
            
            if db_checkpoint and db_checkpoint.get("status") == "in_progress":
                start_batch_index = db_checkpoint.get("last_processed_index", 0)
                processed_records = start_batch_index
                logger.info(f"[Orchestrator] Found active database checkpoint for {batch_id}. Resuming at batch index: {start_batch_index}")
                self.context.update_metrics(retry_count=1)
            else:
                logger.info(f"[Orchestrator] Starting fresh run for {batch_id}.")
                # Clear checkpoint in case it was marked completed before
                self.repo.save_checkpoint(batch_id, 0, 0, "in_progress")

            # Load rows using importer
            target_file, sheet_name, mapping, raw_rows = importer.initialize_import(target_file)
            
            # Fetch completed NPIs from DB that actually contain email or phone data.
            # Rows with empty contact details (e.g. from failed search/mock runs) will be re-processed.
            processed_npis = set()
            try:
                from src.database.database_manager import CompletedContactModel, FailedRecordModel
                session = self.conn_mgr.get_session()
                comp_rows = session.query(CompletedContactModel.npi).filter(
                    CompletedContactModel.npi.isnot(None)
                ).filter(
                    (CompletedContactModel.emails.isnot(None) & (CompletedContactModel.emails != "") & (CompletedContactModel.emails != "[]")) |
                    (CompletedContactModel.phones.isnot(None) & (CompletedContactModel.phones != "") & (CompletedContactModel.phones != "[]"))
                ).all()
                fail_rows = session.query(FailedRecordModel.npi).filter(FailedRecordModel.npi.isnot(None)).all()
                processed_npis.update(str(r[0]).strip() for r in comp_rows if r[0])
                processed_npis.update(str(r[0]).strip() for r in fail_rows if r[0])
                session.close()
                logger.info(f"[Orchestrator] Pre-loaded {len(processed_npis)} processed NPIs from DB to skip.")
            except Exception as e:
                logger.warning(f"[Orchestrator] Failed to pre-load processed NPIs: {e}")

            eligible_records, completed_count, skipped_empty, duplicate_count = importer.process_records(raw_rows, mapping, processed_npis)
            
            # --- RECHECK / RE-VERIFICATION MODE ---
            # If the entire file has been completed (i.e., zero eligible new records are found),
            # we automatically trigger a recheck pass on any rows that have missing contact details.
            if len(eligible_records) == 0:
                logger.info("[Orchestrator] All records in the Excel file have been processed. Scanning for incomplete/skipped rows to recheck...")
                recheck_npis = set()
                for row in status_rows_for_metrics:
                    mapped_row = row_mapper.map_row(row)
                    npi = mapped_row.get("npi", "").strip()
                    if not npi:
                        continue
                    
                    email_val = mapped_row.get("email", "")
                    phone_val = mapped_row.get("phone", "")
                    emails_list = [e.strip() for e in str(email_val).split(",") if e.strip() and not is_empty_value(e.strip())]
                    phones_list = [p.strip() for p in str(phone_val).split(",") if p.strip() and not is_empty_value(p.strip())]
                    
                    # If either email or phone is missing, or status is "not found", we recheck it
                    row_status = ""
                    if status_col_name and status_col_name in row:
                        row_status = str(row[status_col_name]).strip().lower()
                    
                    is_complete = len(emails_list) > 0 and len(phones_list) > 0
                    if not is_complete or row_status in ("no contact found", "not found", "no contacts"):
                        recheck_npis.add(npi)
                
                if recheck_npis:
                    # Filter processed_npis to exclude the NPIs we want to recheck, making them eligible again
                    processed_npis = processed_npis - recheck_npis
                    # Re-run process_records with the adjusted processed_npis
                    eligible_records, completed_count, skipped_empty, duplicate_count = importer.process_records(raw_rows, mapping, processed_npis)
                    logger.info(f"[Orchestrator] Entering recheck mode: Found {len(eligible_records)} incomplete records to retry starting from the beginning.")
                else:
                    logger.info("[Orchestrator] All records in the Excel file are already fully complete (both email & phone found). Nothing to recheck.")

            # Enforce limits if specified in the context metrics
            limit = self.context.get_value("total_records")
            if limit:
                eligible_records = eligible_records[:limit]
            
            total_records = len(eligible_records)
            self.context.set_value("total_records", total_records)
            self.context.set_value("processed_records", processed_records)
            self.context.set_value("duplicate_count", duplicate_count)

            # Split eligible records into batches
            batch_size = self.context.profile.batch_size
            batches = [eligible_records[x:x+batch_size] for x in range(0, total_records, batch_size)]
            self.context.set_value("total_batches", len(batches))

            # Run loops starting from checkpoint batch index
            self.context.state = PipelineState.RUNNING
            
            for b_idx in range(start_batch_index, len(batches)):
                # Check Pause Event
                await self._pause_event.wait()
                if self._stop_requested:
                    break

                self.context.set_value("current_batch_index", b_idx + 1)
                batch_records = batches[b_idx]
                
                # Check Resource health
                self.health_monitor.perform_health_check(
                    context=self.context,
                    queue_size=len(batch_records),
                    db_alive=True,
                    browser_active=True
                )
                
                self.event_bus.publish(PipelineEventType.BATCH_STARTED, batch_index=b_idx+1, size=len(batch_records))

                # --- STAGE 1: SEARCH ---
                logger.info(f"[Orchestrator] Executing Search URL Resolution for Batch {b_idx+1}/{len(batches)}")
                with PerformanceProfiler.profile_stage(self.context, "search"):
                    searched_records = await self.search_mgr.resolve_batch(batch_records)
                self.event_bus.publish(PipelineEventType.SEARCH_COMPLETED, count=len(searched_records))

                # --- STAGE 2: WORKER POOL (SCRAPE & VALIDATE & AI) ---
                logger.info(f"[Orchestrator] Executing Worker Pool Crawl & Validate for Batch {b_idx+1}/{len(batches)}")
                
                validation_mgr = ValidationManager()
                completed_profiles_batch: List[BusinessProfile] = []
                failed_records_batch: List[Dict[str, Any]] = []
                failed_errors_batch: List[str] = []

                # Define the concurrent worker processing callback
                async def worker_callback(rec_data: Dict[str, Any]) -> Dict[str, Any]:
                    url = rec_data.get("website", "")
                    try:
                        # Scrape
                        with PerformanceProfiler.profile_stage(self.context, "scraping"):
                            scraper_out = await self.scraper_mgr.scrape_website(url)
                            
                        # Set default business name
                        if not scraper_out.business_name:
                            scraper_out.business_name = rec_data.get("company_name", "")

                        # Validate
                        with PerformanceProfiler.profile_stage(self.context, "validation"):
                            profile, needs_ai = validation_mgr.validate_contact(scraper_out, rec_data)

                        # AI enrichment
                        if needs_ai:
                            with PerformanceProfiler.profile_stage(self.context, "ai"):
                                # Extract content text body from crawler
                                text_body = scraper_out.raw_text if scraper_out.raw_text else "Clinic web text..."
                                profile = await self.ai_mgr.enrich_profile(profile, text_body)
                                self.context.update_metrics(ai_calls=1)
                        else:
                            self.context.update_metrics(ai_avoided=1)
                            self.ai_mgr.record_ai_avoided()

                        rec_data["profile"] = profile
                        rec_data["worker_status"] = "success"
                    except Exception as e:
                        rec_data["worker_status"] = "error"
                        rec_data["worker_error"] = str(e)
                    return rec_data

                # Dispatch tasks
                worker_count = self.context.profile.worker_count
                pool = WorkerPool(process_callback=worker_callback, worker_count=worker_count)
                
                self.context.set_value("active_workers", worker_count)
                for rec in searched_records:
                    await pool.queue_mgr.add_task(Task(record_data=rec))
                
                await pool.start()
                await pool.join()
                self.context.set_value("active_workers", 0)

                # Collate results
                all_tasks = list(pool.queue_mgr.completed_tasks.values())
                batch_profiles = []
                
                for t in all_tasks:
                    rec_out = t.record_data
                    row_num = rec_out.get("raw_data", {}).get("_row_number", "?")
                    name = rec_out.get("first_name", "") + " " + rec_out.get("last_name", "")
                    name = name.strip() or rec_out.get("company_name", "Unknown Row")

                    if rec_out.get("worker_status") == "success":
                        batch_profiles.append(rec_out["profile"])
                        # Accumulate emails and phones counts
                        self.context.update_metrics(
                            emails_found=len(rec_out["profile"].emails),
                            phones_found=len(rec_out["profile"].phones)
                        )
                        details = f"Emails: {len(rec_out['profile'].emails)}, Phones: {len(rec_out['profile'].phones)}"
                        self.context.log_processed_row(row_num, name, "SUCCESS", details)
                    else:
                        failed_records_batch.append(rec_out)
                        err_msg = rec_out.get("worker_error", "Unknown crawler error")
                        failed_errors_batch.append(err_msg)
                        self.context.log_processed_row(row_num, name, "FAILED", err_msg[:40])

                self.event_bus.publish(PipelineEventType.SCRAPING_COMPLETED, count=len(batch_profiles))

                # Deduplicate profiles inside this batch
                unique_batch_profiles = validation_mgr.deduplicate_profiles(batch_profiles)
                self.context.update_metrics(duplicate_count=(len(batch_profiles) - len(unique_batch_profiles)))
                self.event_bus.publish(PipelineEventType.VALIDATION_COMPLETED, count=len(unique_batch_profiles))

                # --- STAGE 3: PERSISTENCE (WRITE TO DB) ---
                logger.info(f"[Orchestrator] Saving Batch {b_idx+1} to database...")
                with PerformanceProfiler.profile_stage(self.context, "db"):
                    # Save completed
                    inserts, updates = self.bulk_writer.write_profiles(unique_batch_profiles, batch_records)
                    self.context.update_metrics(success_count=inserts + updates)
                    
                    # Save failed
                    if failed_records_batch:
                        self.repo.save_failed_batch(failed_records_batch, failed_errors_batch)
                        self.context.update_metrics(failed_count=len(failed_records_batch))

                # Update Checkpoint in database
                processed_records += len(batch_records)
                self.context.set_value("processed_records", processed_records)
                self.repo.save_checkpoint(batch_id, b_idx + 1, total_records, "in_progress")
                
                # In-place update original Excel file after each batch to show real-time progress
                excel_path = self.file_path or (str(target_file) if 'target_file' in locals() else None)
                if excel_path:
                    try:
                        self.export_mgr.update_original_excel(excel_path)
                    except Exception as e:
                        logger.warning(f"[Orchestrator] In-place Excel update failed for batch {b_idx+1}: {e}")
                
                self.event_bus.publish(PipelineEventType.DATABASE_SAVED, count=len(unique_batch_profiles))
                self.event_bus.publish(PipelineEventType.BATCH_COMPLETED, batch_index=b_idx+1)

            # Loop finished or stopped
            if not self._stop_requested:
                # --- STAGE 4: EXPORT ENGINE ---
                logger.info("[Orchestrator] Ingestion loop completed. Generating data exports...")
                with PerformanceProfiler.profile_stage(self.context, "export"):
                    self.export_mgr.export_all(self.export_dir, self.file_path or str(target_file))
                self.event_bus.publish(PipelineEventType.EXPORT_FINISHED)
                
                # Mark checkpoint as completed
                self.repo.save_checkpoint(batch_id, len(batches), total_records, "completed")
                self.context.state = PipelineState.COMPLETED
            
        except Exception as e:
            self.context.state = PipelineState.FAILED
            self.context.log_error(f"Pipeline crashed: {e}")
            logger.critical(f"[Orchestrator] Pipeline crashed: {e}", exc_info=True)
            self.event_bus.publish(PipelineEventType.PIPELINE_FAILED, error_message=str(e))
            raise e
        finally:
            self.context.end_time = time.time()
            
            # Finalize and update the original Excel sheet one last time to capture all scraped rows
            excel_path = self.file_path or (str(target_file) if 'target_file' in locals() else None)
            if excel_path and self.export_mgr:
                try:
                    self.export_mgr.update_original_excel(excel_path)
                except Exception as e:
                    logger.warning(f"[Orchestrator] Final Excel update in finally block failed: {e}")
                    
            await self._cleanup_components()
            
            # Generate final metrics report
            metrics_saver = PipelineMetrics(self.context)
            report = metrics_saver.generate_final_report()
            
            if self.context.state == PipelineState.COMPLETED:
                self.event_bus.publish(PipelineEventType.PIPELINE_FINISHED)
                
        return report
