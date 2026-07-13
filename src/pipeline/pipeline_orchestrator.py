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

from sqlalchemy import text
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


def determine_not_found_reason(rec_out: Dict[str, Any]) -> str:
    website = rec_out.get("website", "")
    if not website or website.strip() == "":
        return "Official website not found"
        
    scraper_out = rec_out.get("scraper_out")
    if not scraper_out:
        return "Website unreachable"
        
    # Check if we failed to connect/scrape homepage
    if scraper_out.errors and any("failed" in err.lower() or "unreachable" in err.lower() or "error" in err.lower() for err in scraper_out.errors) and not scraper_out.pages_visited:
        return "Website unreachable"
        
    profile = rec_out.get("profile")
    if not profile:
        return "No contacts on website"
        
    # Check if validation rejected all extracted contacts
    had_emails = len(scraper_out.emails) > 0 if scraper_out.emails else False
    had_phones = len(scraper_out.phones) > 0 if scraper_out.phones else False
    if had_emails and not profile.emails:
        return "Validation rejected extracted data"
    if had_phones and not profile.phones:
        return "Validation rejected extracted data"
        
    # Check if contact subpages were missing
    if len(scraper_out.pages_visited) <= 1 and not scraper_out.emails and not scraper_out.phones:
        return "Contact page missing"
        
    # Check AI fallback outcomes
    if rec_out.get("needs_ai") and not profile.emails and not profile.phones:
        return "AI returned no contacts"
        
    if not profile.emails and not profile.phones:
        return "No contacts on website"
    elif not profile.emails:
        return "No email on website"
    elif not profile.phones:
        return "No phone on website"
        
    return "Unknown"


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

        # Historical stats (to reconcile pipeline monitor correctly)
        self.historical_s_full = 0
        self.historical_s_email = 0
        self.historical_s_phone = 0
        self.historical_n_found = 0

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
            if not self.file_path:
                self.file_path = str(target_file)

            # Determine output Excel file: save back to a new Excel file next to target_file to keep them in sequence
            export_excel_path = str(target_file.parent / f"{target_file.stem}_enriched.xlsx")
            
            # Check if the output file exists and is valid
            is_valid_excel = False
            if Path(export_excel_path).exists():
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(export_excel_path, read_only=True)
                    wb.close()
                    is_valid_excel = True
                except Exception:
                    logger.warning(f"[Orchestrator] Existing output Excel {export_excel_path} is corrupted. Re-initializing from base.")
                    try:
                        os.remove(export_excel_path)
                    except Exception:
                        pass
            
            # If the new output file does not exist or was corrupted, initialize it by copying target_file
            if not is_valid_excel:
                import shutil
                source_base = target_file
                try:
                    shutil.copy(str(source_base), export_excel_path)
                    logger.info(f"[Orchestrator] Initialized new output Excel file {export_excel_path} from {source_base}")
                except Exception as e:
                    logger.warning(f"[Orchestrator] Failed to initialize output Excel file: {e}")
            else:
                logger.info(f"[Orchestrator] Reusing existing output Excel file: {export_excel_path}")

            logger.info(f"[Orchestrator] Input source Excel: {target_file} | Output target Excel: {export_excel_path}")

            # Sync database completed records to Excel at startup to align state
            try:
                self.export_mgr.update_original_excel(export_excel_path)
            except Exception as e:
                logger.warning(f"[Orchestrator] Failed startup Excel sync: {e}")
            
            sheet_name = importer.reader.detect_primary_sheet(target_file)
            
            # Deriving Batch ID for DB checkpoints
            batch_id = f"{target_file.name}_{sheet_name}"
            
            # 2. Check DB checkpoints to see if we should resume
            db_checkpoint = self.repo.get_checkpoint(batch_id)
            start_batch_index = 0
            processed_records = 0
            
            if db_checkpoint and db_checkpoint.get("status") == "in_progress":
                logger.info(f"[Orchestrator] Found active database checkpoint for {batch_id}. Resuming at batch index 0 of remaining records.")
                self.context.update_metrics(retry_count=1)
            else:
                logger.info(f"[Orchestrator] Starting fresh run for {batch_id}.")
                # Clear checkpoint in case it was marked completed before
                self.repo.save_checkpoint(batch_id, 0, 0, "in_progress")

            # Load rows using importer
            target_file, sheet_name, mapping, raw_rows = importer.initialize_import(target_file)
            
            # If export_excel_path is different from target_file, read it to get the progress status
            status_rows_for_metrics = raw_rows
            if export_excel_path != str(target_file):
                try:
                    _, _, _, export_raw_rows = importer.initialize_import(Path(export_excel_path))
                    status_rows_for_metrics = export_raw_rows
                    logger.info(f"[Orchestrator] Loaded status rows for metrics from: {export_excel_path}")
                except Exception as e:
                    logger.warning(f"[Orchestrator] Failed to read export excel for metrics: {e}")

            # Analyze raw Excel rows for pre-existing metrics and completed NPIs.
            # This makes progress metrics fully dynamic based on the actual Excel sheet state.
            s_full = 0
            s_email = 0
            s_phone = 0
            n_found = 0
            total_emails = 0
            total_phones = 0
            processed_npis = set()

            from src.importer.filters import is_empty_value
            from src.importer.row_mapper import RowMapper
            row_mapper = RowMapper(mapping)
            
            # Find status column header name
            status_col_name = None
            for sys_key, raw_h in mapping.items():
                if sys_key == "status" or str(raw_h).strip().lower() == "status":
                    status_col_name = raw_h
                    break
            if not status_col_name:
                if status_rows_for_metrics:
                    for k in status_rows_for_metrics[0].keys():
                        if str(k).strip().lower() == "status":
                            status_col_name = k
                            break

            for row in status_rows_for_metrics:
                mapped_row = row_mapper.map_row(row)
                npi = mapped_row.get("npi", "").strip()
                
                # Check email and phone fields
                email_val = mapped_row.get("email", "")
                phone_val = mapped_row.get("phone", "")
                
                emails_list = [e.strip() for e in str(email_val).split(",") if e.strip() and not is_empty_value(e.strip())]
                phones_list = [p.strip() for p in str(phone_val).split(",") if p.strip() and not is_empty_value(p.strip())]
                
                has_emails = len(emails_list) > 0
                has_phones = len(phones_list) > 0
                
                row_status = ""
                if status_col_name and status_col_name in row:
                    row_status = str(row[status_col_name]).strip().lower()
                
                is_row_processed = False
                if has_emails and has_phones:
                    s_full += 1
                    is_row_processed = True
                elif has_emails:
                    s_email += 1
                    is_row_processed = True
                elif has_phones:
                    s_phone += 1
                    is_row_processed = True
                elif row_status in ("no contact found", "not found", "no contacts"):
                    n_found += 1
                    is_row_processed = True
                elif row_status == "completed":
                    s_full += 1
                    is_row_processed = True
                elif row_status == "failed":
                    is_row_processed = True
                
                if is_row_processed and npi:
                    processed_npis.add(npi)
                    
                total_emails += len(emails_list)
                total_phones += len(phones_list)

            # Also load completed NPIs from database CompletedContactModel to prevent re-processing database-only runs
            try:
                from src.database.database_manager import CompletedContactModel
                session = self.conn_mgr.get_session()
                comp_rows = session.query(CompletedContactModel.npi).filter(
                    CompletedContactModel.npi.isnot(None)
                ).all()
                for r in comp_rows:
                    if r[0]:
                        processed_npis.add(str(r[0]).strip())
                session.close()
                logger.info(f"[Orchestrator] Dynamic Excel analysis found {len(processed_npis)} processed records.")
            except Exception as e:
                logger.warning(f"[Orchestrator] Failed startup database NPI pre-load: {e}")

            eligible_records, completed_count, skipped_empty, duplicate_count = importer.process_records(raw_rows, mapping, processed_npis)
            
            # Enforce limits if specified in the context metrics
            limit = self.context.get_value("total_records")
            if limit:
                eligible_records = eligible_records[:limit]
            
            total_records = len(eligible_records)
            self.context.set_value("total_records", total_records)
            self.context.set_value("duplicate_count", duplicate_count)

            # Split eligible records into batches
            batch_size = self.context.profile.batch_size
            batches = [eligible_records[x:x+batch_size] for x in range(0, total_records, batch_size)]
            self.context.set_value("total_batches", len(batches))

            # Redefined Ingestion metrics & Excel resume stats
            total_rows_count = len(raw_rows)
            completed_rows_count = total_rows_count - len(eligible_records)
            remaining_rows_count = len(eligible_records)

            # Initialize context with reconciled historical metrics
            self.context.set_value("success_full_count", s_full)
            self.context.set_value("success_email_count", s_email)
            self.context.set_value("success_phone_count", s_phone)
            self.context.set_value("not_found_count", n_found)
            self.context.set_value("emails_found", total_emails)
            self.context.set_value("phones_found", total_phones)

            # Store the initial database counts so we only audit session updates
            self.historical_s_full = s_full
            self.historical_s_email = s_email
            self.historical_s_phone = s_phone
            self.historical_n_found = n_found
            self.context.historical_success_full = s_full
            self.context.historical_success_email = s_email
            self.context.historical_success_phone = s_phone
            self.context.historical_not_found = n_found

            processed_records = completed_rows_count
            self.context.set_value("processed_records", processed_records)
            
            resume_row_num = batches[start_batch_index][0]["raw_data"]["_row_number"] if batches and start_batch_index < len(batches) else (eligible_records[0]["raw_data"]["_row_number"] if eligible_records else 0)
            
            self.context.set_value("total_rows", total_rows_count)
            self.context.set_value("completed_rows", completed_rows_count)
            self.context.set_value("remaining_rows", remaining_rows_count)
            self.context.set_value("resume_row", resume_row_num)
            self.context.set_value("current_row", resume_row_num)
            self.context.set_value("session_processed", 0)

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
                
                # --- SELF-AUDITING: BEFORE BATCH ---
                logger.info(f"[Audit] Performing pre-batch consistency checks for Batch {b_idx+1}...")
                excel_path = self.file_path or (str(target_file) if 'target_file' in locals() else None)
                if excel_path and not os.path.exists(excel_path):
                    self.context.log_warning(f"Excel file not found at: {excel_path}")
                try:
                    session = self.conn_mgr.get_session()
                    session.execute(text("SELECT 1"))
                    session.close()
                except Exception as e:
                    self.context.log_error(f"Database health check failed: {e}")

                self.event_bus.publish(PipelineEventType.BATCH_STARTED, batch_index=b_idx+1, size=len(batch_records))

                # --- STAGE 1: SEARCH ---
                logger.info(f"[Orchestrator] Executing Search URL Resolution for Batch {b_idx+1}/{len(batches)}")
                self.context.update_metrics(total_search_attempts=len(batch_records))
                with PerformanceProfiler.profile_stage(self.context, "search"):
                    searched_records = await self.search_mgr.resolve_batch(batch_records)
                for r in searched_records:
                    if r.get("website"):
                        self.context.update_metrics(website_found_count=1)
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
                    start_time = time.perf_counter()
                    try:
                        # Scrape
                        with PerformanceProfiler.profile_stage(self.context, "scraping"):
                            scraper_out = await self.scraper_mgr.scrape_website(url)
                            
                        # Set default business name
                        if not scraper_out.business_name:
                            scraper_out.business_name = rec_data.get("company_name", "")

                        # Record page discovery telemetry
                        if scraper_out.pages_visited:
                            self.context.update_metrics(pages_crawled_count=len(scraper_out.pages_visited))
                        if scraper_out.pages_visited and len(scraper_out.pages_visited) > 1:
                            self.context.update_metrics(contact_page_found_count=1)
                        if scraper_out.emails:
                            self.context.update_metrics(emails_extracted_count=1)
                        if scraper_out.phones:
                            self.context.update_metrics(phones_extracted_count=1)
                        if scraper_out.emails or scraper_out.phones:
                            self.context.update_metrics(raw_contacts_found_count=1)

                        # Validate
                        with PerformanceProfiler.profile_stage(self.context, "validation"):
                            profile, needs_ai = validation_mgr.validate_contact(scraper_out, rec_data)

                        self.context.update_metrics(validation_attempts=1)
                        if (scraper_out.emails or scraper_out.phones) and not (profile.emails or profile.phones):
                            self.context.update_metrics(validation_rejections=1)

                        # AI enrichment
                        if needs_ai:
                            self.context.update_metrics(ai_fallback_attempts=1)
                            with PerformanceProfiler.profile_stage(self.context, "ai"):
                                # Extract content text body from crawler
                                text_body = scraper_out.raw_text if scraper_out.raw_text else "Clinic web text..."
                                profile = await self.ai_mgr.enrich_profile(profile, text_body)
                                self.context.update_metrics(ai_calls=1)
                            if profile.emails or profile.phones:
                                self.context.update_metrics(ai_fallback_successes=1)
                        else:
                            self.context.update_metrics(ai_avoided=1)
                            self.ai_mgr.record_ai_avoided()

                        if profile.emails or profile.phones:
                            self.context.update_metrics(validated_contacts_count=1)

                        rec_data["profile"] = profile
                        rec_data["scraper_out"] = scraper_out
                        rec_data["needs_ai"] = needs_ai
                        rec_data["worker_status"] = "success"
                    except Exception as e:
                        rec_data["worker_status"] = "error"
                        rec_data["worker_error"] = str(e)
                    finally:
                        duration_ms = (time.perf_counter() - start_time) * 1000
                        rec_data["processing_duration_ms"] = duration_ms
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
                audit_records_batch = []
                
                for t in all_tasks:
                    rec_out = t.record_data
                    row_num = rec_out.get("raw_data", {}).get("_row_number")
                    npi = rec_out.get("npi") or rec_out.get("raw_data", {}).get("npi")
                    name = rec_out.get("first_name", "") + " " + rec_out.get("last_name", "")
                    name = name.strip() or rec_out.get("company_name", "Unknown Row")
                    
                    search_res = rec_out.get("search_resolution", {})
                    search_query = search_res.get("query", "")
                    
                    scraper_out = rec_out.get("scraper_out")
                    urls_visited = scraper_out.pages_visited if scraper_out else []
                    selected_website = rec_out.get("website", "")
                    
                    contact_pages = [url for url in urls_visited if url != selected_website]
                    emails_extracted = scraper_out.emails if scraper_out else []
                    phones_extracted = scraper_out.phones if scraper_out else []
                    
                    profile = rec_out.get("profile")
                    validation_results = {
                        "confidence": profile.confidence if profile else 0.0,
                        "errors": profile.errors if profile else [],
                        "raw_emails": emails_extracted,
                        "validated_emails": profile.emails if profile else [],
                        "rejected_emails": rec_out.get("rejected_emails", []),
                        "raw_phones": phones_extracted,
                        "validated_phones": profile.phones if profile else [],
                        "rejected_phones": rec_out.get("rejected_phones", [])
                    }
                    
                    duration_ms = rec_out.get("processing_duration_ms", 0.0)
                    
                    # Track current row in context
                    if isinstance(row_num, int):
                        self.context.set_value("current_row", row_num)

                    reason_code = "N/A"
                    if rec_out.get("worker_status") == "success" and profile:
                        batch_profiles.append(profile)
                        
                        has_emails = len(profile.emails) > 0
                        has_phones = len(profile.phones) > 0
                        
                        if has_emails and has_phones:
                            outcome = "SUCCESS_FULL"
                            self.context.update_metrics(success_full_count=1)
                        elif has_emails:
                            outcome = "SUCCESS_EMAIL"
                            self.context.update_metrics(success_email_count=1)
                        elif has_phones:
                            outcome = "SUCCESS_PHONE"
                            self.context.update_metrics(success_phone_count=1)
                        else:
                            outcome = "NOT_FOUND"
                            reason_code = determine_not_found_reason(rec_out)
                            self.context.update_metrics(not_found_count=1)

                        # Accumulate emails and phones counts
                        self.context.update_metrics(
                            emails_found=len(profile.emails),
                            phones_found=len(profile.phones),
                            session_processed=1
                        )
                        details = f"Emails: {len(profile.emails)}, Phones: {len(profile.phones)}"
                        self.context.log_processed_row(row_num, name, outcome, details)
                    else:
                        failed_records_batch.append(rec_out)
                        err_msg = rec_out.get("worker_error", "Unknown crawler error")
                        failed_errors_batch.append(err_msg)
                        
                        outcome = "FAILED"
                        reason_code = err_msg
                        self.context.update_metrics(failed_count=1, session_processed=1)
                        self.context.log_processed_row(row_num, name, "FAILED", err_msg[:40])

                    # Build audit trail entry
                    crawl_telemetry = scraper_out.crawl_telemetry if scraper_out and hasattr(scraper_out, "crawl_telemetry") else {}
                    audit_entry = {
                        "row_number": row_num,
                        "npi": str(npi) if npi else None,
                        "entity_name": name,
                        "search_query": search_query,
                        "urls_visited": urls_visited,
                        "selected_website": selected_website,
                        "contact_pages_crawled": contact_pages,
                        "emails_extracted": emails_extracted,
                        "phones_extracted": phones_extracted,
                        "validation_results": validation_results,
                        "crawl_telemetry": crawl_telemetry,
                        "outcome": outcome,
                        "reason_code": reason_code,
                        "processing_duration_ms": duration_ms
                    }
                    audit_records_batch.append(audit_entry)

                # Save audit trails to DB
                try:
                    self.repo.save_audit_trails(audit_records_batch)
                except Exception as ae:
                    logger.warning(f"[Orchestrator] Failed to save audit trails to DB: {ae}")

                # Append to local JSONL log
                try:
                    log_dir = Path("logs")
                    log_dir.mkdir(parents=True, exist_ok=True)
                    audit_log_path = log_dir / "audit_trail.jsonl"
                    import json
                    with open(audit_log_path, "a", encoding="utf-8") as af:
                        for record in audit_records_batch:
                            af.write(json.dumps(record) + "\n")
                except Exception as le:
                    logger.warning(f"[Orchestrator] Failed to write audit trail to JSONL file: {le}")

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

                # Update Checkpoint in database
                processed_records += len(batch_records)
                self.context.set_value("processed_records", processed_records)
                self.repo.save_checkpoint(batch_id, b_idx + 1, total_records, "in_progress")
                
                # --- SELF-AUDITING: AFTER BATCH ---
                logger.info(f"[Audit] Performing post-batch metric reconciliation for Batch {b_idx+1}...")
                s_proc = self.context.get_value("session_processed")
                s_full = self.context.get_value("success_full_count")
                s_email = self.context.get_value("success_email_count")
                s_phone = self.context.get_value("success_phone_count")
                n_found = self.context.get_value("not_found_count")
                f_count = self.context.get_value("failed_count")
                
                # Reconcile outcomes against the delta from initial database stats
                historical_sum = (
                    self.historical_s_full +
                    self.historical_s_email +
                    self.historical_s_phone +
                    self.historical_n_found
                )
                sum_categories = s_full + s_email + s_phone + n_found + f_count
                sum_session_categories = sum_categories - historical_sum
                
                if sum_session_categories != s_proc:
                    warn_msg = f"Auditing discrepancy: Session Processed ({s_proc}) does not match session outcomes sum ({sum_session_categories})!"
                    logger.warning(warn_msg)
                    self.context.log_warning(warn_msg)
                    self.context.set_value("session_processed", sum_session_categories)
                    s_proc = sum_session_categories
                
                # Continuously update completed and remaining counts based on Excel/session data
                current_completed = completed_rows_count + s_proc
                self.context.set_value("completed_rows", current_completed)
                self.context.set_value("remaining_rows", max(0, remaining_rows_count - s_proc))

                # Trigger diagnostic sampling every 500 records
                try:
                    prev_proc = processed_records - len(batch_records)
                    if (processed_records // 500) > (prev_proc // 500):
                        from src.pipeline.diagnostics import DiagnosticSampler
                        sampler = DiagnosticSampler(self.conn_mgr)
                        sampler.run_diagnostics(processed_records)
                except Exception as de:
                    logger.warning(f"[Orchestrator] Diagnostic sampling failed for batch {b_idx+1}: {de}")

                # In-place update original Excel file after each batch to show real-time progress
                excel_path = export_excel_path
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
                    self.export_mgr.export_all(self.export_dir, export_excel_path)
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
            excel_path = export_excel_path
            if excel_path and self.export_mgr:
                try:
                    self.export_mgr.update_original_excel(excel_path)
                except Exception as e:
                    logger.warning(f"[Orchestrator] Final Excel update in finally block failed: {e}")
                    
            await self._cleanup_components()
            
            # Run one final diagnostic sampler report on completion/interruption
            try:
                from src.pipeline.diagnostics import DiagnosticSampler
                sampler = DiagnosticSampler(self.conn_mgr)
                sampler.run_diagnostics(processed_records)
            except Exception as de:
                logger.warning(f"[Orchestrator] Final diagnostic sampling failed: {de}")
            
            # Generate final metrics report
            metrics_saver = PipelineMetrics(self.context)
            report = metrics_saver.generate_final_report()
            
            if self.context.state == PipelineState.COMPLETED:
                self.event_bus.publish(PipelineEventType.PIPELINE_FINISHED)
                
        return report
