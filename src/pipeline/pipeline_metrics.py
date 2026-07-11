"""
src/pipeline/pipeline_metrics.py
================================
Collects performance telemetry from PipelineContext and compiles the final run-level JSON diagnostic report.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any
from .pipeline_context import PipelineContext

logger = logging.getLogger(__name__)


class PipelineMetrics:
    """
    Compiles, computes, and serializes final execution report telemetry.
    """

    def __init__(self, context: PipelineContext, report_path: str = "logs/final_pipeline_report.json") -> None:
        self.context = context
        self.report_path = Path(report_path)

    def generate_final_report(self) -> Dict[str, Any]:
        """
        Gathers runtime data from context, calculates speed statistics,
        and saves the JSON report structure.
        """
        stats = self.context.get_all_stats()
        elapsed = stats.get("elapsed_time_seconds", 0.0)
        processed = stats.get("processed_records", 0)
        success = stats.get("success_count", 0)
        failed = stats.get("failed_count", 0)
        ai_calls = stats.get("ai_calls", 0)
        ai_avoided = stats.get("ai_avoided", 0)

        # Calculations
        throughput = (processed / elapsed) if elapsed > 0 else 0.0
        success_rate = (success / processed) if processed > 0 else 0.0
        
        total_ai_needs = ai_calls + ai_avoided
        cache_ratio = (ai_avoided / total_ai_needs) if total_ai_needs > 0 else 0.0

        # Load external validation/database/export metrics if available on disk for completeness
        def load_external_json(filename: str) -> Dict[str, Any]:
            p = Path(filename)
            if p.exists():
                try:
                    with open(p, "r") as f:
                        return json.load(f)
                except Exception:
                    pass
            return {}

        db_metrics = load_external_json("logs/database_metrics.json")
        export_metrics = load_external_json("logs/export_metrics.json")
        val_metrics = load_external_json("logs/validation_metrics.json")

        report = {
            "execution_summary": {
                "profile": stats.get("profile", {}).get("profile_name", "unknown"),
                "status": stats.get("state", "idle"),
                "total_execution_time_seconds": elapsed,
                "average_throughput_records_per_sec": round(throughput, 2),
                "success_rate": round(success_rate, 4),
            },
            "records_count": {
                "total_ingested": stats.get("total_records", 0),
                "processed": processed,
                "completed_success": success,
                "failed": failed,
                "retry_pending": stats.get("retry_count", 0),
                "duplicates_merged": stats.get("duplicate_count", 0)
            },
            "contact_intelligence": {
                "emails_found": stats.get("emails_found", 0),
                "phones_found": stats.get("phones_found", 0),
                "ai_provider_calls": ai_calls,
                "ai_calls_avoided": ai_avoided,
                "ai_cache_hit_ratio": round(cache_ratio, 4),
                "browser_launches": stats.get("browser_launches", 0)
            },
            "stage_durations_seconds": stats.get("durations", {}),
            "internal_metrics_file_references": {
                "validation_metrics": val_metrics,
                "database_metrics": db_metrics,
                "export_metrics": export_metrics
            },
            "system_diagnostics": {
                "warnings_count": stats.get("warnings_count", 0),
                "errors_count": stats.get("errors_count", 0),
                "warnings": stats.get("warnings", []),
                "errors": stats.get("errors", [])
            }
        }

        # Write to disk
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            logger.info(f"[PipelineMetrics] Saved final pipeline report to: {self.report_path}")
        except Exception as e:
            logger.error(f"[PipelineMetrics] Error saving final report file: {e}")

        return report
