"""
scripts/test_importer_run.py
==============================
Live Demonstration of the Import Engine.

Demonstrates:
  - Excel file auto-detection.
  - Sheet auto-selection (selecting 'Investor Contacts' and ignoring 'Status').
  - Schema mapping detection and reporting.
  - Smart filtering (calculating completed, duplicate, and eligible records).
  - Batch partitioning and processing loop.
  - Checkpoint saving and resumption simulation.
  - Final statistics writing and serialization.
"""

import asyncio
import sys
import os
import json
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.importer import ImportEngine
from src.importer.checkpoint import CheckpointSystem


def format_record(rec):
    """Format record subset for readable print."""
    return {
        "npi": rec.get("npi"),
        "first_name": rec.get("first_name"),
        "last_name": rec.get("last_name"),
        "email": rec.get("email"),
        "phone": rec.get("phone"),
        "city": rec.get("city"),
        "state": rec.get("state"),
        "source_website": rec.get("website")
    }


def main():
    print("=" * 70)
    print("IMPORT ENGINE PIPELINE LIVE DEMONSTRATION")
    print("=" * 70)

    # 1. Setup Engine Instance
    # We set a small batch size of 50 to demonstrate partition yielding clearly
    engine = ImportEngine(batch_size=50)

    # 2. Phase 1: Initialize Import Metadata
    print("\n[STEP 1] Scanning directories & analyzing workbook metadata...")
    try:
        target_file, sheet_name, mapping, raw_rows = engine.initialize_import()
    except Exception as e:
        print(f"  [ERROR] Failed to locate or load spreadsheet: {e}")
        print("  Make sure us_investors_enriched.xlsx is placed in data/input/")
        sys.exit(1)

    print(f"  Located target file:  {target_file.name}")
    print(f"  Selected worksheet:   '{sheet_name}'")
    print(f"  Total raw row cells:  {len(raw_rows)}")

    # 3. Phase 2: Schema Mapping
    print("\n[STEP 2] Auto-detecting Schema Column Map...")
    for sys_key, raw_col in mapping.items():
        print(f"  - Mapped '{sys_key}' -> Column: '{raw_col}'")

    # 4. Phase 3: Filtering & Quality Analysis
    print("\n[STEP 3] Filtering rows (Skipping completed and duplicate NPIs)...")
    eligible_records, completed_count, skipped_empty, duplicate_count = engine.process_records(raw_rows, mapping)
    print(f"  - Total Raw Rows:       {len(raw_rows)}")
    print(f"  - Empty Rows Skipped:   {skipped_empty}")
    print(f"  - Duplicate NPIs:       {duplicate_count}")
    print(f"  - Already Completed:    {completed_count} (had BOTH email & phone)")
    print(f"  - Eligible for Queue:   {len(eligible_records)} (missing email/phone)")

    # 5. Phase 4: Batch Generator Simulation with Checkpoints
    print("\n[STEP 4] Simulating Batch Generation & Ingestion Lifecycle...")
    print("  We will simulate importing batches. At the end of each batch, a checkpoint is saved.")
    print("  To simulate recovery, we will stop after 3 batches and resume.")

    # Reset any old checkpoint first
    checkpoint_sys = CheckpointSystem()
    checkpoint_sys.clear_checkpoint(target_file.name, sheet_name)

    # Generator instance
    generator = engine.import_generator(file_path=target_file, reset_checkpoint=True)

    # Run first 3 batches
    print("\n  --- Starting Ingestion Run 1 (Simulated Crash after Batch 3) ---")
    try:
        for idx in range(3):
            batch = next(generator)
            print(f"    - Yielded Batch {idx+1}: contains {len(batch)} records.")
            print(f"      Sample record 1: {format_record(batch[0])}")
            print(f"      Sample record 2: {format_record(batch[1])}")
    except StopIteration:
        print("    - Finished early!")

    # Check that a checkpoint exists
    print("\n  [CRASH DETECTED] Process stopped. Checking saved checkpoint state on disk...")
    chk = checkpoint_sys.load_checkpoint(target_file.name, sheet_name)
    if chk:
        print(f"    Checkpoint index:   {chk.get('last_batch_index')}")
        print(f"    Processed count:    {chk.get('processed_count')}")
        print(f"    Queued count:       {chk.get('queued_count')}")
        print(f"    Timestamp:          {chk.get('timestamp')}")
    else:
        print("    [ERROR] No checkpoint saved!")

    # 6. Phase 5: Resuming Ingestion from Checkpoint
    print("\n[STEP 5] Re-initializing Import Engine (Simulating Recovery)...")
    engine2 = ImportEngine(batch_size=50)
    
    # We run the import generator without resetting the checkpoint.
    # It will automatically detect and load the checkpoint file, resuming from batch 3.
    generator2 = engine2.import_generator(file_path=target_file, reset_checkpoint=False)

    print("\n  --- Starting Ingestion Run 2 (Resuming from Checkpoint) ---")
    print("    This generator will yield batches starting from Batch Index 3.")
    
    # We will consume the remaining batches or just run a couple of them to show it resumed
    try:
        # Batch 4 (which is index 3)
        batch = next(generator2)
        print(f"    - Yielded Resumed Batch 4: contains {len(batch)} records.")
        print(f"      Sample record 1: {format_record(batch[0])}")
        
        # Batch 5 (which is index 4)
        batch = next(generator2)
        print(f"    - Yielded Resumed Batch 5: contains {len(batch)} records.")
        print(f"      Sample record 2: {format_record(batch[0])}")
        
        # Let's consume the rest to trigger successful completion and statistics generation
        print("\n    - Ingesting remaining records in background...")
        rest_count = 5
        while True:
            batch = next(generator2)
            rest_count += 1
    except StopIteration:
        print(f"    - Full ingestion finished. Total batches processed: {rest_count}")

    # Check if checkpoint was deleted after completion
    print("\n[STEP 6] Ingestion finished. Checking checkpoint cleanups...")
    chk_after = checkpoint_sys.load_checkpoint(target_file.name, sheet_name)
    if chk_after is None:
        print("  - [PASS] Checkpoint successfully deleted upon completion.")

    # 7. Check Ingestion Statistics
    print("\n[STEP 7] Inspecting Import Statistics report on disk...")
    stats_path = Path("logs/import_statistics.json")
    if stats_path.exists():
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
        print(json.dumps(stats, indent=2))
        print("  - [PASS] statistics.json is formatted correctly.")
    else:
        print("  - [ERROR] Statistics file not found!")

    print("\n" + "=" * 70)
    print("IMPORT ENGINE PIPELINE DEMONSTRATION SUCCESSFUL")
    print("=" * 70)


if __name__ == "__main__":
    main()
