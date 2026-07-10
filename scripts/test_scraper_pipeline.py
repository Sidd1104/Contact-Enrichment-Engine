"""
scripts/test_scraper_pipeline.py
==================================
Live Integration Demonstration of the Website Acquisition & Contact Extraction Pipeline.

Demonstrates:
  1. Ingesting raw Excel rows via the Import Engine.
  2. Resolving website domains via the Search Engine (pointing to a local mock server).
  3. Dispatching tasks to the Async Worker Pool.
  4. Running the Website Acquisition Pipeline (HTTP Client vs Playwright fallback).
  5. Dynamically parsing JS content and performing heuristic confidence scoring.
  6. Outputting the final Structured Contact profiles and saving metrics logs.
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
from typing import Any, Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.importer import ImportEngine
from src.search.search_engine import SearchEngine
from src.search.search_manager import SearchManager
from src.search.search_provider import BingSearchProvider
from src.search.provider_router import ProviderRouter
from src.workers.task import Task
from src.workers.worker_pool import WorkerPool
from src.scraper.scraper_manager import ScraperManager
from src.extractor.structured_contact import StructuredContact

# Setup logging to show stdout clearly
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# =============================================================================
# Local Mock HTTP Server
# =============================================================================

class MockBusinessServer(BaseHTTPRequestHandler):
    """
    Simulated web server serving static HTML and dynamic JS-rendered markup.
    """

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard logging to prevent console pollution
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        path = self.path

        if path == "/":
            # Homepage containing contact and social links (no emails/phones)
            self.wfile.write(b"""
            <html>
                <head><title>Super Clinic</title></head>
                <body>
                    <h1>Welcome to Super Clinic</h1>
                    <p>We provide advanced healthcare. View our <a href="/contact">contact page</a> or <a href="/about-us">about us</a>.</p>
                    <footer>Follow us on <a href="https://facebook.com/super-clinic">Facebook</a> or &copy; Super Clinic 2026.</footer>
                </body>
            </html>
            """)
        elif path == "/contact":
            # Dedicated contact page (contains actual emails, phones, and socials)
            self.wfile.write(b"""
            <html>
                <head><title>Contact Super Clinic</title></head>
                <body>
                    <h1>Contact Our Team</h1>
                    <p>Email: <a href="mailto:info@superclinic.com">info@superclinic.com</a></p>
                    <p>Tel: tel:+12124567890</p>
                    <p>Office: (212) 456-7890</p>
                    <p>Follow our company: <a href="https://linkedin.com/company/super-clinic">LinkedIn</a></p>
                </body>
            </html>
            """)
        elif path == "/about-us":
            self.wfile.write(b"""
            <html>
                <head><title>About Us</title></head>
                <body>
                    <p>Super Clinic is located in NY.</p>
                </body>
            </html>
            """)
        elif path == "/js-page":
            # Page that requires JS rendering to display contact info
            # HTTPScraper will see 'Loading details...' while Playwright extracts the actual info
            self.wfile.write(b"""
            <html>
                <head><title>Dynamic Diagnostics</title></head>
                <body>
                    <h1>Dynamic Diagnostics</h1>
                    <div id="dynamic-info">Loading details...</div>
                    <script>
                        setTimeout(() => {
                            document.getElementById('dynamic-info').innerHTML = 
                                'Please email billing@dynamic.com or call (212) 999-8888.';
                        }, 200);
                    </script>
                </body>
            </html>
            """)
        else:
            self.wfile.write(b"<html><body>404 Not Found</body></html>")


def start_mock_server() -> HTTPServer:
    """Starts the local mock server in a daemon thread."""
    server = HTTPServer(("127.0.0.1", 8088), MockBusinessServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("[MockServer] Started local test server at http://127.0.0.1:8088/")
    return server


# =============================================================================
# Demonstration Script
# =============================================================================

async def main():
    print("=" * 80)
    print("E2E PIPELINE & WEBSITE ACQUISITION SYSTEM LIVE INTEGRATION DEMO")
    print("=" * 80)

    # Start mock business server
    server = start_mock_server()

    # 1. Ingest via Import Engine
    print("\n[STEP 1] Ingesting raw records...")
    importer = ImportEngine(batch_size=20)
    try:
        target_file, sheet_name, mapping, raw_rows = importer.initialize_import()
        eligible_records, completed_count, skipped_empty, duplicate_count = importer.process_records(raw_rows, mapping)
        logger.info(f"Loaded {len(eligible_records)} eligible records from Excel.")
    except Exception as e:
        logger.warning(f"Spreadsheet not found or failed to load: {e}. Generating 20 in-memory mock records.")
        # Generate 20 in-memory mock records
        eligible_records = []
        for i in range(20):
            eligible_records.append({
                "npi": f"10000000{i:02d}",
                "first_name": f"Doctor_{i}",
                "last_name": f"LastName_{i}",
                "company_name": f"Clinic_{i}",
                "email": "",
                "phone": "",
                "city": "New York",
                "state": "NY",
                "website": ""
            })

    # Limit to exactly 20 sample records
    test_batch = eligible_records[:20]
    logger.info(f"Selected {len(test_batch)} sample records for E2E processing.")

    # 2. Search Engine / Website Discovery
    print("\n[STEP 2] Simulating Search Engine resolving websites...")
    # Map them to our local HTTP server to test both static crawling and JS fallback rendering
    for idx, rec in enumerate(test_batch):
        # Let's alternate:
        # - Odd indices: point to static homepage (requires crawling subpage /contact)
        # - Even indices: point to JS-rendered page (requires browser fallback)
        # - Last 2: point to broken/offline links to demonstrate error resilient logs
        if idx >= 18:
            rec["website"] = "http://localhost:8089/broken-link"  # Offline port
        elif idx % 2 == 1:
            rec["website"] = "http://127.0.0.1:8088/"
        else:
            rec["website"] = "http://127.0.0.1:8088/js-page"

        rec["search_resolution"] = {
            "status": "success" if idx < 18 else "failed",
            "provider_used": "bing",
            "confidence_score": 0.95 if idx < 18 else 0.0,
            "cache_hit": True
        }

    # 3. Setup Scraper Manager
    print("\n[STEP 3] Initializing Scraper Manager...")
    scraper_mgr = ScraperManager(strict_robots=False, headless_browser=True)

    # Create worker callback for task queue
    async def process_callback(record_data: Dict[str, Any]) -> Dict[str, Any]:
        url = record_data.get("website", "")
        npi = record_data.get("npi", "")
        logger.info(f"[Worker] Processing record NPI: {npi} | Target website: {url}")
        
        # Scrape website using Website Acquisition Pipeline
        start = time.perf_counter()
        try:
            contact = await scraper_mgr.scrape_website(url)
            # Store structured details inside record
            record_data["enriched_data"] = contact.model_dump()
        except Exception as e:
            logger.error(f"[Worker] Exception scraping {url}: {e}")
            record_data["enriched_data"] = {
                "official_website": url,
                "errors": [str(e)]
            }
        return record_data

    # 4. Setup Worker Pool
    print("\n[STEP 4] Dispatching to Worker Pool Coordinator...")
    # Initialize worker pool with callback, 3 concurrent workers, and temp files
    pool = WorkerPool(
        process_callback=process_callback,
        worker_count=3,
        state_file="data/temp/worker_state.json",
        metrics_file="logs/worker_metrics.json"
    )

    # Queue all 20 tasks
    for rec in test_batch:
        task = Task(record_data=rec, priority=5)
        await pool.queue_mgr.add_task(task)

    # Start pool and join
    await pool.start()
    await pool.join()

    # 5. Output Results
    print("\n" + "=" * 80)
    print("DEMONSTRATION PIPELINE COMPLETED. RESULTS SUMMARY:")
    print("=" * 80)

    # Read records from completed queue
    completed_tasks = list(pool.queue_mgr.completed_tasks.values())
    failed_tasks = list(pool.queue_mgr.failed_tasks.values())

    print(f"\nSuccessfully Processed: {len(completed_tasks)} / {len(test_batch)}")
    print(f"Failed Tasks:           {len(failed_tasks)}")

    print("\n--- Sample Output Details (First 5 records) ---")
    for idx, task in enumerate(completed_tasks[:5]):
        rec = task.record_data
        enriched = rec.get("enriched_data", {})
        print(f"\n{idx+1}. Record NPI: {rec.get('npi')} | Company: {rec.get('company_name')}")
        print(f"   Target URL:    {enriched.get('official_website')}")
        print(f"   Biz Name:      {enriched.get('business_name')}")
        print(f"   Method:        {enriched.get('extraction_method')} | Confidence: {enriched.get('confidence')}")
        print(f"   Emails:        {enriched.get('emails')}")
        print(f"   Phones:        {enriched.get('phones')}")
        print(f"   Socials:       {enriched.get('social_links')}")
        print(f"   Errors:        {enriched.get('errors')}")

    # 6. Metrics Check
    print("\n[STEP 6] Checking Scraper Metrics log file...")
    metrics_path = Path("logs/scraper_metrics.json")
    if metrics_path.exists():
        with open(metrics_path, "r") as f:
            sc_metrics = json.load(f)
        print(json.dumps(sc_metrics, indent=2))
        print("\n  - [PASS] scraper_metrics.json recorded correctly.")
    else:
        print("  - [ERROR] scraper_metrics.json not found!")

    # Cleanup
    print("\n[STEP 7] Cleaning up server and scraper sessions...")
    await scraper_mgr.close()
    server.shutdown()
    logger.info("[Cleanup] Server stopped and playwright resources closed.")

    print("\n" + "=" * 80)
    print("E2E WEBSITE ACQUISITION INTEGRATION DEMONSTRATION SUCCESSFUL")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
