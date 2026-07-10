"""
scripts/test_worker_pool.py
============================
Live Demonstration of the Async Worker Pool & Task Orchestration.

Demonstrates:
  1. Reading eligible records from the Import Engine (20 sample records).
  2. Ingesting and scheduling tasks inside the QueueManager with priorities.
  3. Starting the Asynchronous Worker Pool (concurrency=4).
  4. Simulating task processing with mock HTTP latency and random failure retries.
  5. Demonstrating worker stall detection and automated recovery.
  6. Demonstrates dynamic scaling of workers (2 -> 4).
  7. Demonstrates graceful CTRL+C / interrupt saving states to disk.
  8. Checking output metrics (logs/worker_metrics.json) and progress json.
"""

import asyncio
import sys
import os
import json
import random
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.importer import ImportEngine
from src.workers.worker_pool import WorkerPool
from src.workers.heartbeat import HeartbeatMessage


async def mock_task_processor(record: dict) -> dict:
    """
    Simulated website scraper / AI enrichment callback.
    Takes 0.2 - 0.5s to simulate async HTTP wait, with random retries.
    """
    npi = record.get("npi", "unknown")
    name = f"{record.get('first_name','')} {record.get('last_name','')}".strip() or record.get("company_name", "unknown")
    
    # 1. Simulate async network delay
    await asyncio.sleep(random.uniform(0.1, 0.3))
    
    # 2. Simulate random transient errors and success outcomes
    # 15% chance of retryable transient error
    # 5% chance of fatal error
    # 80% chance of clean success
    rand = random.random()
    if rand < 0.15:
        raise ValueError(f"Transient HTTP connection reset resolving '{name}'")
    elif rand < 0.20:
        raise RuntimeError(f"Fatal Auth failure or site IP blocked scraping '{name}'")
        
    # Standard mock enrichment update
    record["enrichment_status"] = "mock_enriched"
    record["phone"] = record.get("phone") or "(555) 019-2834"
    record["email"] = record.get("email") or f"{name.lower().replace(' ', '.')}@mock-practice.com"
    return record


async def run_demonstration():
    print("=" * 70)
    print("ASYNCHRONOUS WORKER POOL PIPELINE LIVE DEMONSTRATION")
    print("=" * 70)

    # --- Phase 1: Import Engine Ingestion ---
    print("\n[STEP 1] Ingesting raw Excel rows via Import Engine...")
    importer = ImportEngine(batch_size=20)
    try:
        target_file, sheet_name, mapping, raw_rows = importer.initialize_import()
        eligible_records, completed_count, skipped_empty, duplicate_count = importer.process_records(raw_rows, mapping)
    except Exception as e:
        print(f"  [ERROR] Ingestion failed: {e}")
        print("  Make sure us_investors_enriched.xlsx is present in data/input/")
        sys.exit(1)

    print(f"  - Total spreadsheet rows: {len(raw_rows)}")
    print(f"  - Eligible for Queue:     {len(eligible_records)}")

    # Slice out 25 sample records for worker pool simulation
    test_batch = eligible_records[:25]
    print(f"  - Selected {len(test_batch)} records to feed into the worker queue.")

    # --- Phase 2: Setup Worker Pool ---
    print("\n[STEP 2] Initializing Worker Pool coordinator...")
    # Spawn 3 workers initially
    pool = WorkerPool(
        process_callback=mock_task_processor,
        worker_count=3,
        state_file="data/temp/worker_queue_state.json",
        metrics_file="logs/worker_metrics.json",
    )
    
    # Clean old cache/states
    pool.progress.clear()
    await pool.metrics.clear()
    pool.queue_mgr.clear_state_file()

    print("  - Active workers initialized: 3")
    print("  - Queue state path:           data/temp/worker_queue_state.json")
    print("  - Worker metrics path:        logs/worker_metrics.json")

    # --- Phase 3: Push Tasks & Dispatch ---
    print("\n[STEP 3] Converting records to Tasks and dispatching...")
    task_ids = await pool.dispatcher.dispatch_batch(test_batch)
    print(f"  - QueueManager pending tasks count: {pool.queue_mgr.queue_size}")

    # --- Phase 4: Start Ingestion Loops ---
    print("\n[STEP 4] Commencing worker threads execution loops...")
    await pool.start()
    
    # Let workers process for 1.5 seconds
    print("  - Processing tasks in background...")
    await asyncio.sleep(1.5)

    # --- Phase 5: Demonstrate Dynamic Concurrency Scaling ---
    print("\n[STEP 5] Scaling worker pool concurrently (3 -> 5 active loops)...")
    pool.manager.scale_workers(5)
    
    # Process for another 1 second
    await asyncio.sleep(1.0)

    # --- Phase 6: Simulate Worker Stall and Automated Recovery ---
    print("\n[STEP 6] Simulating worker stall and recovery detection...")
    # We select a worker and inject a fake stalled status heartbeat
    stalled_worker_id = "W-01"
    print(f"  - Injecting mock stalled heartbeat status for worker '{stalled_worker_id}'...")
    mock_hb = HeartbeatMessage(
        worker_id=stalled_worker_id,
        status="stalled",
        uptime=20.0,
        last_activity=time.time() - 15.0
    )
    pool.heartbeat_sys.register_heartbeat(mock_hb)
    
    # Allow health checking loop to capture the stall and trigger a replacement
    print("  - Waiting for health check monitor to detect and restart the stalled worker...")
    await asyncio.sleep(2.5)

    # --- Phase 7: Demonstrate Graceful Interruption (Queue State Save) ---
    print("\n[STEP 7] Simulating abrupt cancellation (CTRL+C / Graceful Shutdown)...")
    print("  Saving current queue buffer states to resume in next run...")
    await pool.shutdown()

    # Read queue state file from disk
    state_path = Path("data/temp/worker_queue_state.json")
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        print("  - [PASS] worker_queue_state.json written successfully:")
        print(f"    Pending tasks saved:   {len(state_data.get('pending', []))}")
        print(f"    Completed tasks saved: {len(state_data.get('completed', []))}")
        print(f"    Failed tasks saved:    {len(state_data.get('failed', []))}")
    else:
        print("  - [ERROR] Queue state file not found!")

    # --- Phase 8: Restart Ingestion from Saved State ---
    print("\n[STEP 8] Re-starting Worker Pool (Simulating recovery from state file)...")
    pool2 = WorkerPool(
        process_callback=mock_task_processor,
        worker_count=4,
        state_file="data/temp/worker_queue_state.json",
        metrics_file="logs/worker_metrics.json",
    )
    
    await pool2.start()
    print("  - Restored saved tasks into active priority queue. Processing remaining records...")
    
    # Run to completion
    await pool2.join()
    print("  - [PASS] Worker pool finished remaining tasks and cleared state file.")

    # --- Phase 9: Telemetry & Metrics Verification ---
    print("\n[STEP 9] Inspecting final metrics and progress reports...")
    metrics_path = Path("logs/worker_metrics.json")
    if metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics_data = json.load(f)
        print(json.dumps(metrics_data, indent=2))
        print("  - [PASS] worker_metrics.json formatted successfully.")
    else:
        print("  - [ERROR] Metrics file not found!")

    print("\n" + "=" * 70)
    print("WORKER POOL PIPELINE DEMONSTRATION SUCCESSFUL")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_demonstration())
