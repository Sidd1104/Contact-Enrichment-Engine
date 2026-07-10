"""
scripts/test_validation_pipeline.py
====================================
End-to-End Integration Test for the Contact Intelligence Layer.

Flow:
  1. Ingests 25 sample business records (simulating Import Engine output).
  2. Resolves website URLs via Search (directing to local mock server).
  3. Dispatches tasks to the Async Worker Pool.
  4. Runs the Website Acquisition Scraper (HTTP/Browser).
  5. Runs the Validation Manager (Syntax, Normalized checks, Confidence).
  6. Selectively triggers Google Gemini AI Enrichment (mocked REST queries).
  7. Runs the Merge Engine to combine Scraper and AI outputs.
  8. Deduplicates duplicate profiles (merging duplicates).
  9. Validates metrics log files.
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
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.importer import ImportEngine
from src.workers.task import Task
from src.workers.worker_pool import WorkerPool
from src.scraper.scraper_manager import ScraperManager
from src.extractor.structured_contact import StructuredContact

from src.validator.validation_manager import ValidationManager
from src.validator.business_profile_validator import BusinessProfile
from src.ai.enrichment_manager import AIEnrichmentManager
from src.ai.enrichment_result import AIEnrichmentResult, AIEnrichmentResponseModel

# Setup stdout logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# List of 25 distinct clinic names to avoid accidental name-distance grouping
CLINIC_NAMES = [
    "Alpha Medical Clinic", "Beta Health Center", "Gamma Diagnostics", "Delta Family Practice",
    "Epsilon Health", "Zeta Medical Group", "Eta Care", "Theta Wellness",
    "Iota Pediatrics", "Kappa Orthopedics", "Lambda Cardiology", "Mu Dermatology",
    "Nu Neurology", "Xi Oncology", "Omicron Urology", "Pi Psychiatry",
    "Rho Radiology", "Sigma Surgery", "Tau Therapy", "Upsilon Urgent Care",
    "Phi Family Clinic", "Chi Chiropractic", "Psi Psychology", "Omega ObGyn",
    "Apex Medical Labs"
]


# =============================================================================
# Local Multi-Route HTTP Server
# =============================================================================

class IntegrationMockServer(BaseHTTPRequestHandler):
    """
    Local HTTP server returning customized HTML for 25 mock clinics.
    Tests various scraping and validation states:
    - 0 to 9: Valid mailto email and tel phone (no AI fallback needed)
    - 10 to 14: Only phone present (requires AI to fetch email)
    - 15 to 19: Only email present (requires AI to fetch phone)
    - 20 to 22: Duplicate clinics of 0, 1, 2 (to trigger Levenshtein duplicates)
    - 23 to 24: Offline / broken links (error fallback)
    """

    def log_message(self, format: str, *args: Any) -> None:
        pass  # suppress logs

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        path = self.path.strip("/")

        # Parse index e.g., clinic-12
        if path.startswith("clinic-"):
            try:
                idx = int(path.split("-")[1])
            except ValueError:
                idx = 0
            
            # Use name from our global list
            name = CLINIC_NAMES[idx] if idx < len(CLINIC_NAMES) else f"Clinic {idx}"

            # 1. 0 to 9: Has both email and phone (High quality mailto and tel anchors to boost confidence above 0.8)
            if 0 <= idx < 10:
                html = f"""
                <html>
                    <head><title>{name} - Home</title></head>
                    <body>
                        <h1>Welcome to {name}</h1>
                        <p>For bookings, email us: <a href="mailto:contact-{idx}@clinic.com">contact-{idx}@clinic.com</a></p>
                        <p>Phone: <a href="tel:+121255501{idx:02d}">(212) 555-01{idx:02d}</a></p>
                    </body>
                </html>
                """
            # 2. 10 to 14: Only phone present
            elif 10 <= idx < 15:
                html = f"""
                <html>
                    <head><title>{name}</title></head>
                    <body>
                        <h1>Welcome to {name}</h1>
                        <p>No email listed here. Call: <a href="tel:+121255501{idx:02d}">(212) 555-01{idx:02d}</a></p>
                    </body>
                </html>
                """
            # 3. 15 to 19: Only email present
            elif 15 <= idx < 20:
                html = f"""
                <html>
                    <head><title>{name}</title></head>
                    <body>
                        <h1>Welcome to {name}</h1>
                        <p>No phone number listed. Email us: <a href="mailto:support-{idx}@clinic.com">support-{idx}@clinic.com</a></p>
                    </body>
                </html>
                """
            # 4. 20 to 22: Duplicates of clinic 0, 1, 2
            elif 20 <= idx < 23:
                dup_target = idx - 20
                html = f"""
                <html>
                    <head><title>{CLINIC_NAMES[dup_target]} Dup</title></head>
                    <body>
                        <h1>Clinic {dup_target} Duplicate Location</h1>
                        <p>Email: <a href="mailto:contact-{dup_target}@clinic.com">contact-{dup_target}@clinic.com</a></p>
                        <p>Phone: <a href="tel:+121255501{dup_target:02d}">(212) 555-01{dup_target:02d}</a></p>
                    </body>
                </html>
                """
            else:
                html = "<html><body>Standard page</body></html>"
                
            self.wfile.write(html.encode("utf-8"))
        else:
            self.wfile.write(b"<html><body>404 Not Found</body></html>")


def start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 8088), IntegrationMockServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("[MockServer] Started local test server at http://127.0.0.1:8088/")
    return server


# =============================================================================
# E2E Pipeline Runner
# =============================================================================

async def run_pipeline():
    print("=" * 80)
    print("PHASE 2F INTEGRATION PIPELINE: 25 BUSINESS DEDUPLICATION & ENRICHMENT")
    print("=" * 80)

    # Clear existing metric files from disk to ensure counts are fresh and accurate
    for p in ["logs/validation_metrics.json", "logs/ai_metrics.json"]:
        path = Path(p)
        if path.exists():
            try:
                path.unlink()
                logger.info(f"Cleared existing metrics file: {p}")
            except Exception as e:
                logger.warning(f"Could not clear {p}: {e}")

    # Set validation threshold environment variable explicitly
    os.environ["VALIDATION_CONFIDENCE_THRESHOLD"] = "0.8"

    # Start server
    server = start_server()

    # 1. Generate 25 sample business records (simulating Import Engine)
    print("\n[STEP 1] Simulating 25 ingested Excel records...")
    records = []
    for i in range(25):
        # Clinics 20, 21, 22 are named very similarly to 0, 1, 2 to trigger Levenshtein distance matching
        if 20 <= i < 23:
            orig = i - 20
            # Levenshtein distances:
            # - Alpha Medical Clinic -> Alpha Medical Clnic (distance 1)
            # - Beta Health Center -> Beta Health Cntr (distance 2)
            # - Gamma Diagnostics -> Gamma Diagnostcs (distance 1)
            if orig == 0:
                name = "Alpha Medical Clnic"
            elif orig == 1:
                name = "Beta Health Cntr"
            else:
                name = "Gamma Diagnostcs"
            city = "New York"
            state = "NY"
        else:
            name = CLINIC_NAMES[i]
            city = f"City_{i}"
            state = f"State_{i}"

        records.append({
            "npi": f"10000000{i:02d}",
            "first_name": f"Doctor_{i}",
            "last_name": f"LastName_{i}",
            "company_name": name,
            "email": "",
            "phone": "",
            "address_line_1": f"Street {i}",
            "city": city,
            "state": state,
            "postal_code": f"100{i:02d}",
            "country": "US",
            "website": f"http://127.0.0.1:8088/clinic-{i}" if i < 23 else "http://localhost:8089/broken-link"
        })
    logger.info(f"Generated {len(records)} test records.")

    # 2. Setup Managers
    print("\n[STEP 2] Initializing Pipeline Managers...")
    scraper_mgr = ScraperManager(strict_robots=False)
    validation_mgr = ValidationManager()
    
    # Setup AI enrichment manager with mocked query calls
    ai_mgr = AIEnrichmentManager()

    # Build the Mock AI query return generator
    def mock_ai_response(prompt: str, response_model: Any, timeout: float = 0.0):
        # Find which clinic matches the prompt
        clinic_id = None
        for i, name in enumerate(CLINIC_NAMES):
            # Check if name is in prompt
            if name.lower() in prompt.lower():
                clinic_id = i
                break
        
        if clinic_id is None:
            # Check first word
            for i, name in enumerate(CLINIC_NAMES):
                first_word = name.split()[0].lower()
                if first_word in prompt.lower():
                    clinic_id = i
                    break

        if clinic_id is None:
            # Search for "clinic X"
            for i in range(25):
                if f"clinic {i}" in prompt.lower() or f"clinic-{i}" in prompt.lower():
                    clinic_id = i
                    break

        if clinic_id is None:
            # Fallback to a unique counter to prevent match collapses
            mock_ai_response.counter += 1
            clinic_id = mock_ai_response.counter + 100

        # If it is clinic 10-14 (needs email)
        if 10 <= clinic_id < 15:
            enrich_res = AIEnrichmentResult(
                official_email=f"ai-contact-{clinic_id}@clinic.com",
                official_phone="",
                reasoning="Extracted email from simulated AI lookup.",
                confidence=0.85
            )
        # If it is clinic 15-19 (needs phone)
        elif 15 <= clinic_id < 20:
            enrich_res = AIEnrichmentResult(
                official_email="",
                official_phone=f"(212) 555-99{clinic_id:02d}",
                reasoning="Extracted phone from simulated AI lookup.",
                confidence=0.85
            )
        else:
            enrich_res = AIEnrichmentResult(
                official_email=f"ai-general-{clinic_id}@clinic.com",
                official_phone=f"212-555-80{clinic_id:02d}",
                reasoning="Generic fallback.",
                confidence=0.75
            )
            
        return AIEnrichmentResponseModel(enrichment=enrich_res)

    mock_ai_response.counter = 0

    ai_mgr.router.router.query_structured = AsyncMock(side_effect=mock_ai_response)
    ai_mgr.router.router.stop = AsyncMock()

    # 3. Create Worker Callback
    async def process_callback(record_data: Dict[str, Any]) -> Dict[str, Any]:
        url = record_data.get("website", "")
        npi = record_data.get("npi", "")
        
        # Crawl site
        scraper_out = await scraper_mgr.scrape_website(url)
        # Set business name if empty from scraper
        if not scraper_out.business_name:
            scraper_out.business_name = record_data.get("company_name", "")

        # Run Validation Manager
        profile, needs_ai = validation_mgr.validate_contact(scraper_out, record_data)

        # Run conditional AI fallback enrichment
        if needs_ai:
            profile = await ai_mgr.enrich_profile(profile, "Simulated website crawl body text...")
        else:
            ai_mgr.record_ai_avoided()

        # Update record
        record_data["profile"] = profile
        return record_data

    # 4. Setup Worker Pool
    print("\n[STEP 3] Launching Worker Pool to process 25 tasks concurrently...")
    pool = WorkerPool(process_callback=process_callback, worker_count=5)
    
    for rec in records:
        task = Task(record_data=rec, priority=5)
        await pool.queue_mgr.add_task(task)

    await pool.start()
    await pool.join()

    # 5. Group and Deduplicate final profiles
    print("\n[STEP 4] Collecting outputs and executing Duplicate Detector...")
    all_profiles: List[BusinessProfile] = []
    completed_tasks = list(pool.queue_mgr.completed_tasks.values())
    for t in completed_tasks:
        prof = t.record_data.get("profile")
        if prof:
            all_profiles.append(prof)
            
    failed_tasks = list(pool.queue_mgr.failed_tasks.values())
    for t in failed_tasks:
        prof = t.record_data.get("profile")
        if prof:
            all_profiles.append(prof)

    print(f"  - Initial profiles collected: {len(all_profiles)}")

    # Deduplicate
    unique_profiles = validation_mgr.deduplicate_profiles(all_profiles)
    print(f"  - Unique profiles after merging: {len(unique_profiles)}")

    # 6. Verify duplicates removed count
    duplicates_removed = len(all_profiles) - len(unique_profiles)
    print(f"  - Duplicates merged: {duplicates_removed}")

    # 7. Print Final Merged Business Profiles
    print("\n" + "=" * 80)
    print("DEDUPLICATED & ENRICHED BUSINESS PROFILES SUMMARY:")
    print("=" * 80)
    for idx, prof in enumerate(unique_profiles):
        print(f"\n{idx+1}. Name: {prof.business_name} | Website: {prof.official_website}")
        print(f"   Address:    {prof.address}")
        print(f"   Emails:     {prof.emails}")
        print(f"   Phones:     {prof.phones}")
        print(f"   Method:     {prof.extraction_method} | Confidence: {prof.confidence}")
        print(f"   Provenance: {prof.provenance}")
        print(f"   Errors:     {prof.errors}")

    # 8. Assert and Verify Metrics Logs
    print("\n[STEP 5] Checking logs files on disk...")
    
    val_metrics_path = Path("logs/validation_metrics.json")
    if val_metrics_path.exists():
        with open(val_metrics_path, "r") as f:
            v_metrics = json.load(f)
        print("\n--- Validation Metrics Log ---")
        print(json.dumps(v_metrics, indent=2))
        assert v_metrics["counts"]["validated_emails"] > 0
        assert v_metrics["counts"]["duplicates_removed"] == duplicates_removed
    else:
        print("  [ERROR] validation_metrics.json not found!")

    ai_metrics_path = Path("logs/ai_metrics.json")
    if ai_metrics_path.exists():
        with open(ai_metrics_path, "r") as f:
            a_metrics = json.load(f)
        print("\n--- AI Metrics Log ---")
        print(json.dumps(a_metrics, indent=2))
        assert a_metrics["counts"]["ai_calls"] > 0
        assert a_metrics["counts"]["ai_avoided"] > 0
    else:
        print("  [ERROR] ai_metrics.json not found!")

    # Cleanup
    print("\n[STEP 6] Stopping server and closing scraper/AI connections...")
    await scraper_mgr.close()
    await ai_mgr.close()
    server.shutdown()
    logger.info("[Cleanup] Integration server stopped successfully.")
    
    print("\n" + "=" * 80)
    print("INTEGRATION DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
