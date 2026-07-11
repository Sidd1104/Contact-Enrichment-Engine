"""
scripts/test_database_pipeline.py
===================================
End-to-End Demonstration Pipeline for the Persistence Layer & Export Engine.

Ingestion Flow:
  1. Ingests 15 sample business records (simulating Import Engine output).
  2. Runs concurrent tasks through the Async Worker Pool.
  3. Scrapes mock clinic pages on a local server.
  4. Runs the Validation Manager (Syntax, Normalized, Confidence checks).
  5. Decides AI fallback enrichment (simulated REST calls).
  6. Deduplicates profiles (merging duplicated inputs).
  7. Persists records to SQLite (Completed, Failed, and Retry records) via BulkWriter.
  8. Exports datasets to CSV, Excel, and compiles Markdown reports via ExportManager.
  9. Validates telemetry metrics (database_metrics.json, export_metrics.json).
"""

import asyncio
import json
import logging
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workers.task import Task
from src.workers.worker_pool import WorkerPool
from src.scraper.scraper_manager import ScraperManager
from src.extractor.structured_contact import StructuredContact
from src.validator.validation_manager import ValidationManager
from src.validator.business_profile_validator import BusinessProfile
from src.ai.enrichment_manager import AIEnrichmentManager
from src.ai.enrichment_result import AIEnrichmentResult, AIEnrichmentResponseModel

from src.database.connection_manager import ConnectionManager
from src.database.database_manager import DatabaseManager
from src.database.bulk_writer import BulkWriter
from src.exporter.export_manager import ExportManager

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CLINIC_NAMES = [
    "Alpha Medical Clinic", "Beta Health Center", "Gamma Diagnostics", "Delta Family Practice",
    "Epsilon Health", "Zeta Medical Group", "Eta Care", "Theta Wellness",
    "Iota Pediatrics", "Kappa Orthopedics", "Lambda Cardiology", "Mu Dermatology",
    "Nu Neurology", "Xi Oncology", "Omicron Urology"
]


# =============================================================================
# Local Mock Server
# =============================================================================

class PipelineMockServer(BaseHTTPRequestHandler):
    """
    Simulates a web server hosting 15 pages for clinics:
    - 0 to 7: Has both email and phone (High quality, no AI fallback)
    - 8 to 9: Has only phone (requires AI fallback)
    - 10 to 11: Duplicates of 0 and 1
    - 12 to 14: Simulates unreachable pages (causes scraping errors)
    """

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress console log spam

    def do_GET(self) -> None:
        path = self.path.strip("/")
        
        if not path.startswith("clinic-"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        try:
            idx = int(path.split("-")[1])
        except ValueError:
            idx = 0

        # Simulate failures for clinics 12 to 14
        if idx >= 12:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"Service Unavailable")
            return

        name = CLINIC_NAMES[idx] if idx < len(CLINIC_NAMES) else f"Clinic {idx}"
        
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        # HTML generation
        if 0 <= idx < 8:
            # Valid email and phone
            html = f"""
            <html>
                <head><title>{name} - Home</title></head>
                <body>
                    <h1>{name}</h1>
                    <p>Contact: <a href="mailto:info-{idx}@clinic.com">info-{idx}@clinic.com</a></p>
                    <p>Phone: <a href="tel:+121255502{idx:02d}">(212) 555-02{idx:02d}</a></p>
                </body>
            </html>
            """
        elif 8 <= idx < 10:
            # Phone only
            html = f"""
            <html>
                <head><title>{name}</title></head>
                <body>
                    <h1>{name}</h1>
                    <p>Call us today at: <a href="tel:+121255502{idx:02d}">(212) 555-02{idx:02d}</a></p>
                </body>
            </html>
            """
        else:
            # Duplicates of clinic 0 & 1
            dup_target = idx - 10
            html = f"""
            <html>
                <head><title>{CLINIC_NAMES[dup_target]} Duplicate Location</title></head>
                <body>
                    <h1>Clinic {dup_target} - Alternate Site</h1>
                    <p>Email: <a href="mailto:info-{dup_target}@clinic.com">info-{dup_target}@clinic.com</a></p>
                    <p>Phone: <a href="tel:+121255502{dup_target:02d}">(212) 555-02{dup_target:02d}</a></p>
                </body>
            </html>
            """
        self.wfile.write(html.encode("utf-8"))


def start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 8092), PipelineMockServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("[MockServer] Running local server at http://127.0.0.1:8092/")
    return server


# =============================================================================
# E2E Pipeline Demonstration Execution
# =============================================================================

async def main():
    print("=" * 80)
    print("E2E PIPELINE: IMPORTER -> SCRAPER -> VALIDATION -> DATABASE -> EXPORT")
    print("=" * 80)

    # 1. Clear database and export files from previous runs
    for fp in [
        "data/test_pipeline.db",
        "logs/database_metrics.json",
        "logs/export_metrics.json",
        "logs/validation_metrics.json",
        "logs/ai_metrics.json"
    ]:
        path = Path(fp)
        if path.exists():
            try:
                path.unlink()
                logger.info(f"Cleaned previous file: {fp}")
            except Exception as e:
                logger.warning(f"Could not delete {fp}: {e}")

    # Set validation environment variables
    os.environ["VALIDATION_CONFIDENCE_THRESHOLD"] = "0.8"

    # Start mock server
    server = start_server()

    # 2. Ingest raw records (simulating Import Engine output)
    print("\n[STEP 1] Generating 15 raw clinic records...")
    records = []
    for i in range(15):
        if 10 <= i < 12:
            # Duplicates of clinic 0 & 1 with slight Levenshtein differences
            orig = i - 10
            name = "Alpha Medical Clnic" if orig == 0 else "Beta Health Cntr"
        else:
            name = CLINIC_NAMES[i]

        records.append({
            "npi": f"20000000{i:02d}",
            "company_name": name,
            "website": f"http://127.0.0.1:8092/clinic-{i}",
            "address_line_1": f"Street {i}",
            "city": f"New York",
            "state": "NY",
            "postal_code": f"100{i:02d}",
            "country": "US"
        })
    logger.info(f"Generated {len(records)} test records.")

    # 3. Setup Pipeline Components
    print("\n[STEP 2] Setting up database engine, schemas, and writer...")
    conn = ConnectionManager(custom_uri="sqlite:///data/test_pipeline.db")
    db_mgr = DatabaseManager(conn)
    db_mgr.create_tables()
    repo = db_mgr.get_repository()
    
    # Initialize bulk writer and retry repo
    bulk_writer = BulkWriter(repo, batch_size=5)
    
    print("[STEP 2b] Initializing Crawler, Validator, and AI Fallback Managers...")
    scraper_mgr = ScraperManager(strict_robots=False)
    validation_mgr = ValidationManager()
    ai_mgr = AIEnrichmentManager()

    # Mock the AI Enrichment response mapping
    def mock_ai_response(prompt: str, response_model: Any, timeout: float = 0.0):
        # Look for clinic index in prompt
        clinic_idx = 0
        for i in range(15):
            if f"clinic-{i}" in prompt.lower() or CLINIC_NAMES[i].split()[0].lower() in prompt.lower():
                clinic_idx = i
                break
        
        # Return mocked AI response containing missing email
        return AIEnrichmentResponseModel(
            enrichment=AIEnrichmentResult(
                official_email=f"ai-email-{clinic_idx}@clinic.com",
                official_phone="",
                reasoning="Simulated AI lookup successfully discovered missing contact email.",
                confidence=0.85
            )
        )

    ai_mgr.router.router.query_structured = AsyncMock(side_effect=mock_ai_response)
    ai_mgr.router.router.stop = AsyncMock()

    # Lists to collect results
    completed_profiles: List[BusinessProfile] = []
    failed_ingests: List[Dict[str, Any]] = []
    failed_errors: List[str] = []
    retry_ingests: List[Dict[str, Any]] = []
    retry_errors: List[str] = []

    # 4. Define Worker processing callback
    async def process_callback(rec: Dict[str, Any]) -> Dict[str, Any]:
        url = rec.get("website", "")
        npi = rec.get("npi", "")
        
        try:
            # Scraping
            scraper_out = await scraper_mgr.scrape_website(url)
            
            # Check for scraping errors
            if scraper_out.errors and "unreachable" in "".join(scraper_out.errors).lower():
                raise ConnectionError("Scraper could not reach the server")

            if not scraper_out.business_name:
                scraper_out.business_name = rec.get("company_name", "")

            # Validation
            profile, needs_ai = validation_mgr.validate_contact(scraper_out, rec)

            # AI Fallback
            if needs_ai:
                profile = await ai_mgr.enrich_profile(profile, "Simulated body content text...")
            else:
                ai_mgr.record_ai_avoided()

            rec["profile"] = profile
            rec["status"] = "success"
        except Exception as e:
            rec["status"] = "error"
            rec["error_message"] = str(e)
        return rec

    # 5. Execute concurrent processing via WorkerPool
    print("\n[STEP 3] Running Worker Pool (5 workers) for concurrent scraping/validation...")
    pool = WorkerPool(process_callback=process_callback, worker_count=5)
    
    for rec in records:
        await pool.queue_mgr.add_task(Task(record_data=rec))

    await pool.start()
    await pool.join()

    # 6. Collate worker pool outputs
    print("\n[STEP 4] Categorizing tasks results into Completed, Failed, or Retry lists...")
    completed_tasks = list(pool.queue_mgr.completed_tasks.values())
    
    profiles_to_dedup = []
    for t in completed_tasks:
        data = t.record_data
        if data.get("status") == "success":
            profiles_to_dedup.append(data["profile"])
        else:
            # These are failures (e.g. clinics 12, 13, 14 which threw errors)
            # Decide if transient (retry) or permanent (failed)
            # Let's say clinic 12 is transient (retry), and 13-14 are permanent failures
            npi_idx = int(data.get("npi", "00")[-2:])
            err_msg = data.get("error_message", "Unknown error")
            if npi_idx == 12:
                retry_ingests.append(data)
                retry_errors.append(err_msg)
            else:
                failed_ingests.append(data)
                failed_errors.append(err_msg)

    # 7. Run validation-level deduplication
    print("\n[STEP 5] Running validation-level deduplication on completed contacts...")
    unique_profiles = validation_mgr.deduplicate_profiles(profiles_to_dedup)
    logger.info(f"Unique profiles to persist: {len(unique_profiles)} (merged: {len(profiles_to_dedup) - len(unique_profiles)})")

    # 8. Persist batches to database
    print("\n[STEP 6] Saving all records into the database via BulkWriter...")
    # Write completed contacts
    ins, upd = bulk_writer.write_profiles(unique_profiles, records)
    logger.info(f"Database persist results: inserts={ins}, updates={upd}")

    # Write failures
    if failed_ingests:
        f_count = repo.save_failed_batch(failed_ingests, failed_errors)
        logger.info(f"Saved {f_count} permanent failures to database.")

    # Write retries
    if retry_ingests:
        r_count = repo.save_retry_batch(retry_ingests, retry_errors)
        logger.info(f"Saved {r_count} transient retry tasks to database.")

    # Save a checkpoint
    repo.save_checkpoint("demo_batch_001", last_processed_index=15, total_records=15, status="completed")
    print("Ingestion checkpoint stored successfully.")

    # 9. Export datasets and compile reports
    print("\n[STEP 7] Initializing ExportManager to output CSVs, Excel, and Markdown reports...")
    export_mgr = ExportManager(repo)
    generated = export_mgr.export_all("data/test_export")
    
    print("\nGenerated export files:")
    for key, path in generated.items():
        print(f"  - {key}: {path}")

    # 10. Display database metrics and export metrics
    print("\n[STEP 8] Printing database and export metrics JSON logs...")
    
    db_metrics_path = Path("logs/database_metrics.json")
    if db_metrics_path.exists():
        with open(db_metrics_path, "r") as f:
            print("\n=== Database Ingestion Telemetry ===")
            print(json.dumps(json.load(f), indent=2))
            
    export_metrics_path = Path("logs/export_metrics.json")
    if export_metrics_path.exists():
        with open(export_metrics_path, "r") as f:
            print("\n=== Export Engine Telemetry ===")
            print(json.dumps(json.load(f), indent=2))

    # Cleanup
    print("\n[STEP 9] Disposing resources and stopping local mock server...")
    await scraper_mgr.close()
    await ai_mgr.close()
    conn.close()
    server.shutdown()
    
    print("\n" + "=" * 80)
    print("E2E PIPELINE DEMONSTRATION RUN FINISHED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
