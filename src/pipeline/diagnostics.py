"""
src/pipeline/diagnostics.py
===========================
Diagnostic Sampler Utility.

Automatically pulls a random sample of NOT_FOUND and successful records from the database
or audit trails every 500 records and generates comparative diagnostics reports.
"""

from __future__ import annotations

import os
import json
import random
import logging
from pathlib import Path
from typing import Dict, Any, List
from sqlalchemy import text

logger = logging.getLogger(__name__)


class DiagnosticSampler:
    """
    Randomly inspects NOT_FOUND and successful outcomes to provide quality insights.
    """

    def __init__(self, conn_mgr: Any) -> None:
        self.conn_mgr = conn_mgr

    def run_diagnostics(self, processed_count: int) -> str | None:
        """
        Samples random NOT_FOUND and SUCCESS records, compiles aggregation metrics,
        and writes a comparative quality report to logs/diagnostics_sample_{count}.md.
        """
        session = self.conn_mgr.get_session()
        try:
            # 1. Query random NOT_FOUND records from audit_trails
            query_nf = text(
                "SELECT row_number, entity_name, search_query, selected_website, reason_code, validation_results, crawl_telemetry, processing_duration_ms "
                "FROM audit_trails WHERE outcome = 'NOT_FOUND' ORDER BY "
                f"{'RANDOM()' if self.conn_mgr.engine_type == 'sqlite' else 'random()'} LIMIT 5"
            )
            result_nf = session.execute(query_nf).fetchall()

            # 2. Query random successful records (SUCCESS_FULL, SUCCESS_EMAIL, SUCCESS_PHONE)
            query_succ = text(
                "SELECT row_number, entity_name, search_query, selected_website, outcome, validation_results, crawl_telemetry, processing_duration_ms "
                "FROM audit_trails WHERE outcome IN ('SUCCESS_FULL', 'SUCCESS_EMAIL', 'SUCCESS_PHONE') ORDER BY "
                f"{'RANDOM()' if self.conn_mgr.engine_type == 'sqlite' else 'random()'} LIMIT 5"
            )
            result_succ = session.execute(query_succ).fetchall()

            if not result_nf and not result_succ:
                logger.info("[DiagnosticSampler] No records found to run diagnostics.")
                return None

            report_path = Path("logs") / f"diagnostics_sample_{processed_count}.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)

            # 3. Compute granular validation rejections and page skip reasons across all audit trails
            all_records_query = text("SELECT outcome, validation_results, crawl_telemetry FROM audit_trails")
            all_rows = session.execute(all_records_query).fetchall()
            
            email_rejections: Dict[str, int] = {}
            phone_rejections: Dict[str, int] = {}
            page_skips: Dict[str, int] = {}
            total_playwright_renders = 0
            playwright_successes = 0

            for out, val_res_str, crawl_tel_str in all_rows:
                # Safe JSON load
                try:
                    val_res = json.loads(val_res_str) if isinstance(val_res_str, str) else (val_res_str or {})
                except Exception:
                    val_res = {}
                try:
                    crawl_tel = json.loads(crawl_tel_str) if isinstance(crawl_tel_str, str) else (crawl_tel_str or {})
                except Exception:
                    crawl_tel = {}

                # Track page skips
                for skip in crawl_tel.get("pages_skipped", []):
                    reason = skip.get("reason", "Unknown skip")
                    page_skips[reason] = page_skips.get(reason, 0) + 1

                # Track email rejections
                for rej in val_res.get("rejected_emails", []):
                    reason = rej.get("reason", "Unknown rejection")
                    email_rejections[reason] = email_rejections.get(reason, 0) + 1

                # Track phone rejections
                for rej in val_res.get("rejected_phones", []):
                    reason = rej.get("reason", "Unknown rejection")
                    phone_rejections[reason] = phone_rejections.get(reason, 0) + 1

                # Playwright fallback stats
                if crawl_tel.get("playwright_rendered"):
                    total_playwright_renders += 1
                    if out in ("SUCCESS_FULL", "SUCCESS_EMAIL", "SUCCESS_PHONE"):
                        playwright_successes += 1

            # 4. Generate report body
            report_content = f"""# Enrichment Quality & Diagnostics Report
Checkpoint: {processed_count} Processed Records

This report analyzes search, crawling, and validation bottlenecks to improve contact coverage.

---

## 1. Pipeline Flow Funnel Stats (Overall Audit Summary)

* **Playwright Fallback Execution Rate**: {total_playwright_renders} runs triggered Playwright fallback.
* **Playwright Fallback Conversion Rate**: {(playwright_successes / total_playwright_renders * 100.0) if total_playwright_renders > 0 else 0.0:.1f}% ({playwright_successes} successful enrichments out of {total_playwright_renders} renders).

### Page discovery & Link Crawl Skip Reasons:
{f"| Skip Reason | Count |\\n| :--- | :---: |\\n" + "\\n".join(f"| {r} | {c} |" for r, c in page_skips.items()) if page_skips else "*No pages skipped.*"}

### Validation Rejections:
#### Email Validator:
{f"| Email Rejection Reason | Count |\\n| :--- | :---: |\\n" + "\\n".join(f"| {r} | {c} |" for r, c in email_rejections.items()) if email_rejections else "*No emails rejected.*"}

#### Phone Validator:
{f"| Phone Rejection Reason | Count |\\n| :--- | :---: |\\n" + "\\n".join(f"| {r} | {c} |" for r, c in phone_rejections.items()) if phone_rejections else "*No phones rejected.*"}

---

## 2. Sample Comparison: Successful vs. NOT_FOUND Records

### A. Sample Successful Records
| Row Number | Company / Entity Name | Selected Website | Method Used | Duration (ms) |
| :--- | :--- | :--- | :---: | :---: |
"""
            for row in result_succ:
                row_num, name, _, website, outcome, _, crawl_tel_str, dur = row
                try:
                    crawl_tel = json.loads(crawl_tel_str) if isinstance(crawl_tel_str, str) else (crawl_tel_str or {})
                except Exception:
                    crawl_tel = {}
                method = "Browser" if crawl_tel.get("playwright_rendered") else "HTTP"
                report_content += f"| {row_num or 'N/A'} | {name or 'N/A'} | {website or 'None'} | {method} | {int(dur or 0):,} ms |\n"

            report_content += """
### B. Sample NOT_FOUND Records
| Row Number | Company / Entity Name | Search Query Used | Selected Website | NOT_FOUND Reason |
| :--- | :--- | :--- | :--- | :--- |
"""
            for row in result_nf:
                row_num, name, query_str, website, reason, _, _, _ = row
                report_content += f"| {row_num or 'N/A'} | {name or 'N/A'} | `{query_str or 'N/A'}` | {website or 'None'} | **{reason or 'N/A'}** |\n"

            report_content += "\n## 3. Systematic Diagnostics & Recommendations\n\n"

            # 5. Output specific recommendations based on reasons found in samples
            all_sampled_reasons = [row[4] for row in result_nf]
            
            # Recommendation 1: Query Tuning
            report_content += "### 🔍 Search Query & Website Discovery Recommendations\n"
            if "Official website not found" in all_sampled_reasons:
                report_content += (
                    "- **Query Tuning needed**: Multiple entities failed at the website discovery stage. "
                    "Ensure queries include structured address details (city/state) or identifiers (NPI, medical domain). "
                    "Consider appending 'official clinic website' or 'doctor profile' to google search queries.\n"
                )
            else:
                report_content += (
                    "- **Search is stable**: Search query parameters appear to resolve correct official websites successfully. "
                    "The bottleneck is further down in crawling/parsing.\n"
                )

            # Recommendation 2: Link crawling
            report_content += "\n### 🕸️ Link Discovery & Crawling Recommendations\n"
            if "Contact page missing" in all_sampled_reasons:
                report_content += (
                    "- **Expand Contact Page Keywords**: The crawler resolves homepages but misses contact subpages. "
                    "Ensure keywords in `ContactPageDetector` detect non-standard paths like `/meet-us`, `/our-location`, `/reach-us`, `/info`.\n"
                )
            if page_skips.get("Restricted by robots.txt", 0) > (processed_count * 0.1):
                report_content += (
                    "- **Robots.txt bottleneck**: A significant percentage of pages are skipped because of Robots.txt rules. "
                    "Consider loosening strictness (`strict_robots=False` in configs) or utilizing search cache fallbacks.\n"
                )
            report_content += "- **Improve crawling depth**: Verify link parser handles dynamically created relative links, checking standard domains.\n"

            # Recommendation 3: Dynamic vs Static Page extraction
            report_content += "\n### ⚡ Dynamic Rendering & Scraper Recommendations\n"
            if total_playwright_renders > 0 and (playwright_successes / total_playwright_renders) < 0.2:
                report_content += (
                    "- **Optimize Playwright Scraper**: Playwright falls back frequently but has a low success/conversion rate. "
                    "This suggests sites are either blocking headless browsers (Cloudflare checks) or contact details aren't present. "
                    "Implement human-like scrolling, randomized window sizes, and anti-detection settings in `browser_scraper.py`.\n"
                )
            else:
                report_content += (
                    "- **Dynamic rendering is effective**: When browser fallback is triggered, it successfully resolves additional contact details. "
                    "Continue to selectively trigger Playwright to avoid latency bloat.\n"
                )

            # Recommendation 4: Regex and Validators
            report_content += "\n### ⚙️ Regex Patterns & Validation Recommendations\n"
            if "Validation rejected extracted data" in all_sampled_reasons or email_rejections or phone_rejections:
                report_content += (
                    "- **Tune Regex Filters**: Check if legitimate emails/phones are being discarded by strict validators. "
                    "Ensure disposable domain lists are up-to-date and regex matches correct spacing/punctuation in phone numbers.\n"
                )
            report_content += "- **De-duplicate cleanly**: Ensure validator merges similar numbers (e.g. sharing suffix extension) to avoid duplicate counts.\n"

            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)

            # Write static overall copy
            try:
                with open("logs/enrichment_quality_report.md", "w", encoding="utf-8") as f:
                    f.write(report_content)
            except Exception:
                pass

            logger.info(f"[DiagnosticSampler] Saved diagnostic report to: {report_path}")
            return str(report_path)

        except Exception as e:
            logger.error(f"[DiagnosticSampler] Error running diagnostics: {e}")
            return None
        finally:
            session.close()
