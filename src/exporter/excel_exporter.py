"""
src/exporter/excel_exporter.py
==============================
Serializes validated business profiles into formatted Excel spreadsheets.
Uses pandas and openpyxl, dynamically sizing columns for readability.
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
from src.validator.business_profile_validator import BusinessProfile
from .export_metrics import ExportMetrics

logger = logging.getLogger(__name__)


class ExcelExporter:
    """
    Exports business profiles to Excel with auto-sized columns.
    """

    def __init__(self, metrics: Optional[ExportMetrics] = None) -> None:
        self.metrics = metrics or ExportMetrics()

    def export(self, profiles: List[BusinessProfile], filepath: str) -> None:
        """
        Exports business profiles to the specified Excel filepath.
        """
        start_time = time.perf_counter()
        path = Path(filepath)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            rows = []
            for prof in profiles:
                rows.append({
                    "Business Name": prof.business_name,
                    "Official Website": prof.official_website,
                    "Emails": ", ".join(prof.emails) if prof.emails else "",
                    "Phones": ", ".join(prof.phones) if prof.phones else "",
                    "Address": prof.address or "",
                    "Extraction Method": prof.extraction_method or "",
                    "Confidence": round(prof.confidence, 3),
                    "Pages Visited": ", ".join(prof.pages_visited) if prof.pages_visited else "",
                    "LinkedIn": prof.social_links.get("linkedin", "") if prof.social_links else "",
                    "Facebook": prof.social_links.get("facebook", "") if prof.social_links else "",
                    "Instagram": prof.social_links.get("instagram", "") if prof.social_links else "",
                    "Twitter": prof.social_links.get("twitter", "") if prof.social_links else "",
                    "YouTube": prof.social_links.get("youtube", "") if prof.social_links else "",
                    "GitHub": prof.social_links.get("github", "") if prof.social_links else "",
                    "Errors": "; ".join(prof.errors) if prof.errors else "",
                    "Provenance": json.dumps(prof.provenance) if prof.provenance else "{}"
                })

            df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
                "Business Name", "Official Website", "Emails", "Phones", 
                "Address", "Extraction Method", "Confidence", "Pages Visited",
                "LinkedIn", "Facebook", "Instagram", "Twitter", "YouTube", "GitHub",
                "Errors", "Provenance"
            ])

            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Enriched Contacts", index=False)
                
                # Style column widths based on contents
                workbook = writer.book
                worksheet = writer.sheets["Enriched Contacts"]
                
                for col in worksheet.columns:
                    max_len = 0
                    col_letter = col[0].column_letter
                    for cell in col:
                        if cell.value is not None:
                            max_len = max(max_len, len(str(cell.value)))
                    # Apply width with buffer, cap at 50 for very long cells (like JSON)
                    worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 11), 50)

            duration = time.perf_counter() - start_time
            self.metrics.record_export("excel", len(profiles), duration)
            self.metrics.save()
            logger.info(f"[ExcelExporter] Successfully exported {len(profiles)} profiles to {filepath} in {duration:.3f}s")
        except Exception as e:
            self.metrics.record_failure()
            self.metrics.save()
            logger.error(f"[ExcelExporter] Error writing Excel file {filepath}: {e}")
            raise e
