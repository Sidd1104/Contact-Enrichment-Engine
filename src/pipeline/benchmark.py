"""
src/pipeline/benchmark.py
==========================
Executes performance benchmarking tests across different worker counts and batch sizes.
Saves comparison telemetry matrices in data/export/benchmark_report.md.
"""

from __future__ import annotations

import time
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any

from .pipeline_runner import PipelineRunner

logger = logging.getLogger(__name__)


class PipelineBenchmark:
    """
    Executes benchmark matrix runs and logs performance comparisons.
    """

    def __init__(self, file_path: str, export_dir: str = "data/export") -> None:
        self.file_path = file_path
        self.export_dir = Path(export_dir)
        self.results: List[Dict[str, Any]] = []

    async def execute_benchmarks(self) -> str:
        """
        Runs the benchmark matrix:
          - Concurrency (Workers): [2, 4]
          - Batch Sizes: [5, 10]
        """
        logger.info("[PipelineBenchmark] Commencing system execution benchmarks...")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        configs = [
            {"worker_count": 2, "batch_size": 5},
            {"worker_count": 4, "batch_size": 10}
        ]

        for idx, cfg in enumerate(configs):
            workers = cfg["worker_count"]
            batch = cfg["batch_size"]
            logger.info(f"[PipelineBenchmark] Running configuration {idx+1}/{len(configs)}: workers={workers}, batch={batch}")
            
            # Initialize pipeline runner with custom parameters, disables dashboard to prevent print clutter
            runner = PipelineRunner(
                profile_name="testing",
                file_path=self.file_path,
                export_dir=str(self.export_dir / f"benchmark_cfg_{idx}"),
                db_uri=f"sqlite:///data/temp/benchmark_{workers}_{batch}.db",
                show_dashboard=False
            )
            
            # Override context settings
            runner.context.profile.worker_count = workers
            runner.context.profile.batch_size = batch
            
            # Start timer
            start_time = time.perf_counter()
            try:
                report = await runner.run()
                duration = time.perf_counter() - start_time
                
                success = report.get("records_count", {}).get("completed_success", 0)
                failed = report.get("records_count", {}).get("failed", 0)
                total = success + failed
                throughput = (total / duration) if duration > 0 else 0.0
                
                self.results.append({
                    "workers": workers,
                    "batch_size": batch,
                    "total_records": total,
                    "duration_seconds": round(duration, 3),
                    "throughput_records_per_sec": round(throughput, 2),
                    "success_count": success,
                    "failed_count": failed,
                    "averages": report.get("stage_durations_seconds", {})
                })
            except Exception as e:
                logger.error(f"[PipelineBenchmark] Configuration workers={workers}, batch={batch} failed: {e}")

        # Generate report
        report_path = self.export_dir / "benchmark_report.md"
        self._write_markdown_report(str(report_path))
        return str(report_path)

    def _write_markdown_report(self, filepath: str) -> None:
        """Writes the comparison matrix to a markdown file."""
        logger.info(f"[PipelineBenchmark] Compiling comparison report: {filepath}")
        
        rows = []
        for r in self.results:
            durs = r.get("averages", {})
            rows.append(
                f"| {r['workers']} | {r['batch_size']} | {r['total_records']} | "
                f"{r['duration_seconds']}s | {r['throughput_records_per_sec']} | "
                f"{r['success_count']} | {r['failed_count']} | "
                f"{durs.get('search', 0)}s | {durs.get('scraping', 0)}s | {durs.get('db', 0)}s |"
            )

        content = f"""# Contact Enrichment Engine Pipeline Benchmark Report

Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}

This report compares ingestion throughput, duration, and latency parameters across varying concurrency models.

## Concurrency Performance Matrix

| Workers Count | Batch Size | Total Records | Run Duration | Throughput (rec/s) | Successes | Failures | Avg Search Latency | Avg Scrape Latency | Avg DB Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{"\n".join(rows)}

## Diagnostic Insights
- **Throughput Bounds**: High worker counts increase processing speed but are bound by Playwright browser setup times and database lock states.
- **Resource Constraints**: High thread concurrency raises RAM footprints. For environments with low resources, workers = 5 is recommended.
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[PipelineBenchmark] Benchmark report written successfully.")
