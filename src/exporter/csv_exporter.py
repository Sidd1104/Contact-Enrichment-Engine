"""
src/exporter/csv_exporter.py
============================
Serializes validated business profiles into standard tabular CSV files.
Updates exporter telemetry metrics.
"""

from __future__ import annotations

import csv
import json
import time
import logging
from pathlib import Path
from typing import List, Optional

from src.validator.business_profile_validator import BusinessProfile
from .export_metrics import ExportMetrics

logger = logging.getLogger(__name__)


class CSVExporter:
    """
    Exports business profiles to RFC-4180 compliant CSV format.
    """

    def __init__(self, metrics: Optional[ExportMetrics] = None) -> None:
        self.metrics = metrics or ExportMetrics()

    def export(self, profiles: List[BusinessProfile], filepath: str) -> None:
        """
        Exports the provided profiles list to the specified destination path.
        """
        start_time = time.perf_counter()
        path = Path(filepath)
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            
            headers = [
                "business_name", "official_website", "emails", "phones", 
                "address", "extraction_method", "confidence", "pages_visited",
                "social_linkedin", "social_facebook", "social_instagram", 
                "social_twitter", "social_youtube", "social_github",
                "errors", "provenance"
            ]
            
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                
                for prof in profiles:
                    row = {
                        "business_name": prof.business_name,
                        "official_website": prof.official_website,
                        "emails": "; ".join(prof.emails) if prof.emails else "",
                        "phones": "; ".join(prof.phones) if prof.phones else "",
                        "address": prof.address or "",
                        "extraction_method": prof.extraction_method or "",
                        "confidence": round(prof.confidence, 3),
                        "pages_visited": "; ".join(prof.pages_visited) if prof.pages_visited else "",
                        "social_linkedin": prof.social_links.get("linkedin", "") if prof.social_links else "",
                        "social_facebook": prof.social_links.get("facebook", "") if prof.social_links else "",
                        "social_instagram": prof.social_links.get("instagram", "") if prof.social_links else "",
                        "social_twitter": prof.social_links.get("twitter", "") if prof.social_links else "",
                        "social_youtube": prof.social_links.get("youtube", "") if prof.social_links else "",
                        "social_github": prof.social_links.get("github", "") if prof.social_links else "",
                        "errors": "; ".join(prof.errors) if prof.errors else "",
                        "provenance": json.dumps(prof.provenance) if prof.provenance else "{}"
                    }
                    writer.writerow(row)
                    
            duration = time.perf_counter() - start_time
            self.metrics.record_export("csv", len(profiles), duration)
            self.metrics.save()
            logger.info(f"[CSVExporter] Successfully exported {len(profiles)} profiles to {filepath} in {duration:.3f}s")
        except Exception as e:
            self.metrics.record_failure()
            self.metrics.save()
            logger.error(f"[CSVExporter] Error writing CSV file {filepath}: {e}")
            raise e
