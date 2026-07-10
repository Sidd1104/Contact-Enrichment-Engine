"""
src/scraper/scraper_metrics.py
===============================
Tracks scraping, browser fallbacks, error rates, and writes stats to JSON.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ScraperMetrics:
    """
    Manages and persists execution telemetry for HTTP and browser scrapers.
    """

    def __init__(self, filepath: str = "logs/scraper_metrics.json") -> None:
        self.filepath = Path(filepath)
        
        # State variables
        self.http_success = 0
        self.http_fail = 0
        self.browser_success = 0
        self.browser_fail = 0
        self.pages_crawled = 0
        self.emails_extracted = 0
        self.phones_extracted = 0
        self.total_extraction_time = 0.0
        self.sessions_count = 0
        self.browser_launches = 0
        self.failures = 0

        # Load existing metrics if file exists
        self.load()

    def load(self) -> None:
        """Load state from file if it exists."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                
                counts = data.get("counts", {})
                self.http_success = counts.get("http_success", 0)
                self.http_fail = counts.get("http_fail", 0)
                self.browser_success = counts.get("browser_success", 0)
                self.browser_fail = counts.get("browser_fail", 0)
                self.pages_crawled = counts.get("pages_crawled", 0)
                self.emails_extracted = counts.get("emails_extracted", 0)
                self.phones_extracted = counts.get("phones_extracted", 0)
                self.browser_launches = counts.get("browser_launches", 0)
                self.failures = counts.get("failures", 0)

                latency = data.get("performance", {})
                self.total_extraction_time = latency.get("total_extraction_time", 0.0)
                self.sessions_count = latency.get("sessions_count", 0)
            except Exception as e:
                logger.warning(f"Could not load metrics file: {e}. Starting fresh.")

    def increment_http_success(self) -> None:
        self.http_success += 1

    def increment_http_fail(self) -> None:
        self.http_fail += 1

    def increment_browser_success(self) -> None:
        self.browser_success += 1

    def increment_browser_fail(self) -> None:
        self.browser_fail += 1

    def increment_browser_launches(self) -> None:
        self.browser_launches += 1

    def increment_pages_crawled(self, val: int = 1) -> None:
        self.pages_crawled += val

    def add_extracted_counts(self, emails: int, phones: int) -> None:
        self.emails_extracted += emails
        self.phones_extracted += phones

    def record_session(self, latency: float) -> None:
        self.total_extraction_time += latency
        self.sessions_count += 1

    def increment_failures(self) -> None:
        self.failures += 1

    def generate_report(self) -> Dict[str, Any]:
        """Calculates derived metrics and returns a report dictionary."""
        total_http = self.http_success + self.http_fail
        http_success_rate = (self.http_success / total_http) if total_http > 0 else 0.0

        total_sessions = self.sessions_count
        browser_fallback_rate = (self.browser_launches / total_sessions) if total_sessions > 0 else 0.0
        avg_extraction_time = (self.total_extraction_time / total_sessions) if total_sessions > 0 else 0.0

        return {
            "counts": {
                "http_success": self.http_success,
                "http_fail": self.http_fail,
                "browser_success": self.browser_success,
                "browser_fail": self.browser_fail,
                "pages_crawled": self.pages_crawled,
                "emails_extracted": self.emails_extracted,
                "phones_extracted": self.phones_extracted,
                "browser_launches": self.browser_launches,
                "failures": self.failures
            },
            "performance": {
                "total_extraction_time": round(self.total_extraction_time, 2),
                "sessions_count": self.sessions_count,
                "average_extraction_time_seconds": round(avg_extraction_time, 2),
            },
            "rates": {
                "http_success_rate": round(http_success_rate, 4),
                "browser_fallback_rate": round(browser_fallback_rate, 4)
            }
        }

    def save(self) -> None:
        """Saves current report to json file."""
        report = self.generate_report()
        try:
            # Create logs/ directory if missing
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save scraper metrics to file: {e}")
