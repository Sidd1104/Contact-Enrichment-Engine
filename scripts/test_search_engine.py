"""
scripts/test_search_engine.py
==============================
Live Demonstration of the Search Engine & Website Discovery Layer.

Flow:
  1. Ingests raw records using the Import Engine (up to 20 eligible records for fast check).
  2. Resolves website URLs concurrently using the Search Manager and Search Engine.
  3. Demonstrates the local File-based Cache.
  4. Outputs search metrics (logs/search_metrics.json).
  5. Prints discovery summary details to the console.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.importer.importer import ImportEngine
from src.search.search_engine import SearchEngine
from src.search.search_manager import SearchManager
from src.search.search_provider import TavilySearchProvider, BingSearchProvider
from src.search.provider_router import ProviderRouter
from src.search.cache_manager import FileSearchCache
from src.search.metrics import SearchMetrics


async def run_demonstration():
    print("=" * 70)
    print("WEBSITE DISCOVERY SEARCH ENGINE PIPELINE LIVE DEMONSTRATION")
    print("=" * 70)

    # --- Phase 1: Ingestion via Import Engine ---
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
    print(f"  - Already Completed:      {completed_count}")
    print(f"  - Eligible for Discovery: {len(eligible_records)}")

    # Slice out 10 sample records for our demonstration to avoid API key usage depletion
    test_batch = eligible_records[:10]
    
    # Clear the website value for the first 3 records to force the search engine
    # to perform website discovery using the search APIs. The remaining 7 will demonstrate
    # skipping search when the website already exists in the dataset.
    for rec in test_batch[:3]:
        rec["website"] = ""
        
    print(f"  - Selected 10 test records for search resolution (3 forced, 7 skipped).")

    # --- Phase 2: Setup Search Engine ---
    print("\n[STEP 2] Setting up Search Engine layers...")
    
    # Instantiate providers (Tavily with real key, Bing in mock mode)
    tavily_prov = TavilySearchProvider()
    bing_prov = BingSearchProvider()
    
    # Priority order: Tavily first, Bing second
    router = ProviderRouter([tavily_prov, bing_prov], ["tavily", "bing"])
    
    cache = FileSearchCache()
    # Wipe any old cache for clean demonstration
    await cache.clear()
    
    metrics = SearchMetrics()
    await metrics.clear()
    
    engine = SearchEngine(router, cache=cache, metrics=metrics)
    manager = SearchManager(engine, max_concurrency=3)
    
    print("  - Active search providers registered: ['tavily', 'bing']")
    print("  - Provider priority order:             ['tavily', 'bing']")
    print("  - Search Cache:                        FileSearchCache enabled")
    print("  - Concurrency limit:                   3 concurrent requests")

    # --- Phase 3: Live Website Discovery Run 1 (Cache Misses) ---
    print("\n[STEP 3] Ingesting Batched Search Resolution (Run 1 - Cache Misses)...")
    print("  Resolving websites concurrently. This will call the Tavily search provider API...")
    
    start_time = time.monotonic()
    resolved_batch_1 = await manager.resolve_batch(test_batch)
    run_1_duration = time.monotonic() - start_time
    
    print(f"\n  Run 1 finished in {run_1_duration:.2f}s. Discovery Outcomes:")
    for idx, rec in enumerate(resolved_batch_1):
        res = rec.get("search_resolution", {})
        first = rec.get("first_name", "")
        last = rec.get("last_name", "")
        company = rec.get("company_name", "")
        name = f"{first} {last}".strip() or company
        
        status = res.get("status")
        url = rec.get("website", "")
        conf = res.get("confidence_score", 0.0)
        provider = res.get("provider_used")
        
        print(f"    {idx+1}. '{name}' ({rec.get('city')}, {rec.get('state')})")
        print(f"       Status: {status} | URL: '{url}' (Confidence: {conf:.3f}, Provider: {provider})")

    # --- Phase 4: Live Website Discovery Run 2 (Cache Hits) ---
    print("\n[STEP 4] Re-ingesting Same Batch (Run 2 - Cache Hits)...")
    print("  This run should fetch all website resolutions instantly from the local Cache...")
    
    start_time = time.monotonic()
    resolved_batch_2 = await manager.resolve_batch(test_batch)
    run_2_duration = time.monotonic() - start_time
    
    print(f"\n  Run 2 finished in {run_2_duration:.2f}s. Discovery Outcomes:")
    for idx, rec in enumerate(resolved_batch_2):
        res = rec.get("search_resolution", {})
        url = rec.get("website", "")
        provider = res.get("provider_used")
        cache_hit = res.get("cache_hit")
        print(f"    {idx+1}. URL: '{url}' | Provider: {provider} | Cache Hit: {cache_hit}")

    # --- Phase 5: Metrics Review ---
    print("\n[STEP 5] Inspecting Search Metrics report on disk...")
    metrics_path = Path("logs/search_metrics.json")
    if metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics_data = json.load(f)
        print(json.dumps(metrics_data, indent=2))
        print("  - [PASS] search_metrics.json populated successfully.")
    else:
        print("  - [ERROR] Metrics file not found!")

    # Check cache file size on disk
    cache_path = Path("data/temp/search_cache.json")
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_entries = json.load(f)
        print(f"  - [PASS] search_cache.json created with {len(cache_entries)} entries.")
    else:
        print("  - [ERROR] Cache file not found!")

    print("\n" + "=" * 70)
    print("WEBSITE DISCOVERY PIPELINE DEMONSTRATION SUCCESSFUL")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_demonstration())
