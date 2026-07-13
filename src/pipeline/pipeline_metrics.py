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

        # Enrichment quality metrics from context
        total_search_attempts = stats.get("total_search_attempts", 0)
        website_found_count = stats.get("website_found_count", 0)
        contact_page_found_count = stats.get("contact_page_found_count", 0)
        emails_extracted_count = stats.get("emails_extracted_count", 0)
        phones_extracted_count = stats.get("phones_extracted_count", 0)
        ai_fallback_attempts = stats.get("ai_fallback_attempts", 0)
        ai_fallback_successes = stats.get("ai_fallback_successes", 0)
        validation_attempts = stats.get("validation_attempts", 0)
        validation_rejections = stats.get("validation_rejections", 0)

        # KPI Rates
        website_discovery_rate = (website_found_count / total_search_attempts) if total_search_attempts > 0 else 0.0
        contact_page_discovery_rate = (contact_page_found_count / website_found_count) if website_found_count > 0 else 0.0
        email_extraction_success_rate = (emails_extracted_count / website_found_count) if website_found_count > 0 else 0.0
        phone_extraction_success_rate = (phones_extracted_count / website_found_count) if website_found_count > 0 else 0.0
        ai_fallback_success_rate = (ai_fallback_successes / ai_fallback_attempts) if ai_fallback_attempts > 0 else 0.0
        validation_rejection_rate = (validation_rejections / validation_attempts) if validation_attempts > 0 else 0.0

        # Console output for RUN SUMMARY
        total_rows = stats.get("total_rows", 0)
        session_processed = stats.get("session_processed", 0)
        success_full = stats.get("success_full_count", 0)
        success_email = stats.get("success_email_count", 0)
        success_phone = stats.get("success_phone_count", 0)
        not_found = stats.get("not_found_count", 0)
        
        # Calculate rates
        total_outcomes = success_full + success_email + success_phone + not_found + failed
        email_cov = ((success_full + success_email) / total_outcomes * 100) if total_outcomes > 0 else 0.0
        phone_cov = ((success_full + success_phone) / total_outcomes * 100) if total_outcomes > 0 else 0.0
        both_cov = (success_full / total_outcomes * 100) if total_outcomes > 0 else 0.0
        
        avg_time_ms = ((elapsed * 1000) / session_processed) if session_processed > 0 else 0.0
        web_success_rate = website_discovery_rate * 100
        
        summary = f"""
==============================
RUN SUMMARY
==============================
Total Rows              {total_rows:,}
Processed               {total_outcomes:,}
SUCCESS_FULL             {success_full:,}
SUCCESS_EMAIL            {success_email:,}
SUCCESS_PHONE            {success_phone:,}
NOT_FOUND               {not_found:,}
FAILED                     {failed:,}
------------------------------
Email Coverage         {email_cov:.1f}%
Phone Coverage         {phone_cov:.1f}%
Both Contacts          {both_cov:.1f}%
Average Time/Record    {avg_time_ms:.0f} ms
AI Calls               {ai_calls:,}
Cache Hit Rate          {cache_ratio * 100:.1f}%
Website Success Rate   {web_success_rate:.1f}%
==============================
"""
        # Compute Funnel Report
        total_searched = total_search_attempts
        web_located = website_found_count
        contact_page_discovered = contact_page_found_count
        pages_crawled = stats.get("pages_crawled_count", 0)
        contacts_extracted_raw = stats.get("raw_contacts_found_count", 0)
        validated_contacts = stats.get("validated_contacts_count", 0)
        
        hist_s_full = stats.get("historical_success_full", 0)
        fully_enriched = max(0, success_full - hist_s_full)

        def get_funnel_stats(current: int, previous: int, initial: int) -> tuple[float, float]:
            overall_conv = (current / initial * 100.0) if initial > 0 else 0.0
            step_drop = ((previous - current) / previous * 100.0) if previous > 0 else 0.0
            return overall_conv, step_drop

        c_web, d_web = get_funnel_stats(web_located, total_searched, total_searched)
        c_contact, d_contact = get_funnel_stats(contact_page_discovered, web_located, total_searched)
        c_crawl, d_crawl = get_funnel_stats(pages_crawled, max(1, web_located), total_searched)
        c_ext, d_ext = get_funnel_stats(contacts_extracted_raw, max(1, web_located), total_searched)
        c_val, d_val = get_funnel_stats(validated_contacts, max(1, contacts_extracted_raw), total_searched)
        c_full, d_full = get_funnel_stats(fully_enriched, max(1, validated_contacts), total_searched)

        drops = [
            ("Official Website Resolution", d_web),
            ("Contact Page Discovery", d_contact),
            ("Pages Visited/Crawled", d_crawl),
            ("Raw Contacts Extraction", d_ext),
            ("Validation Stage", d_val),
            ("Final Enrichment Stage", d_full)
        ]
        max_drop_stage, max_drop_val = max(drops, key=lambda x: x[1]) if total_searched > 0 else ("N/A", 0.0)

        funnel_str = f"""
========================================================================
  ENRICHMENT QUALITY FUNNEL REPORT (SESSION PROCESS FLOW)
========================================================================
  Stage                              | Count    | Conversion | Drop-off
------------------------------------------------------------------------
  1. Total Searched                  | {total_searched:8,} |   100.0%   |    0.0%
  2. Official Website Located        | {web_located:8,} |   {c_web:6.1f}% | {d_web:6.1f}%
  3. Contact Page Discovered         | {contact_page_discovered:8,} |   {c_contact:6.1f}% | {d_contact:6.1f}%
  4. Pages Visited/Crawled           | {pages_crawled:8,} |   {c_crawl:6.1f}% | {d_crawl:6.1f}%
  5. Raw Contacts Extracted          | {contacts_extracted_raw:8,} |   {c_ext:6.1f}% | {d_ext:6.1f}%
  6. Validated Contacts              | {validated_contacts:8,} |   {c_val:6.1f}% | {d_val:6.1f}%
  7. Final Fully Enriched (Full)     | {fully_enriched:8,} |   {c_full:6.1f}% | {d_full:6.1f}%
------------------------------------------------------------------------
  >> Critical Bottleneck Identified: {max_drop_stage} (Loss: {max_drop_val:.1f}%)
========================================================================
"""
        import sys
        sys.stdout.write(summary)
        sys.stdout.write(funnel_str)
        sys.stdout.flush()

        # Write funnel report markdown
        try:
            funnel_md_path = Path("logs/funnel_report.md")
            funnel_md_path.parent.mkdir(parents=True, exist_ok=True)
            with open(funnel_md_path, "w", encoding="utf-8") as f:
                f.write(f"""# Enrichment Quality Funnel Report

| Stage | Count | Cumulative Conversion | Step Drop-off |
| :--- | :---: | :---: | :---: |
| **1. Total Searched** | {total_searched:,} | 100.0% | 0.0% |
| **2. Official Website Located** | {web_located:,} | {c_web:.1f}% | {d_web:.1f}% |
| **3. Contact Page Discovered** | {contact_page_discovered:,} | {c_contact:.1f}% | {d_contact:.1f}% |
| **4. Pages Visited/Crawled** | {pages_crawled:,} | {c_crawl:.1f}% | {d_crawl:.1f}% |
| **5. Raw Contacts Extracted** | {contacts_extracted_raw:,} | {c_ext:.1f}% | {d_ext:.1f}% |
| **6. Validated Contacts** | {validated_contacts:,} | {c_val:.1f}% | {d_val:.1f}% |
| **7. Final Fully Enriched (Full)** | {fully_enriched:,} | {c_full:.1f}% | {d_full:.1f}% |

## Funnel Bottleneck Identification
* **Primary Bottleneck**: **{max_drop_stage}** with a step drop-off of **{max_drop_val:.1f}%**.
* *Recommendation*: Focus on improving this specific pipeline stage to boost overall conversion and email/phone coverage.
""")
        except Exception as e:
            logger.warning(f"Failed to write funnel_report.md: {e}")

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
            "enrichment_quality_kpis": {
                "website_discovery_rate": round(website_discovery_rate, 4),
                "contact_page_discovery_rate": round(contact_page_discovery_rate, 4),
                "email_extraction_success_rate": round(email_extraction_success_rate, 4),
                "phone_extraction_success_rate": round(phone_extraction_success_rate, 4),
                "ai_fallback_success_rate": round(ai_fallback_success_rate, 4),
                "validation_rejection_rate": round(validation_rejection_rate, 4)
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
