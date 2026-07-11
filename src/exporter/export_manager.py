"""
src/exporter/export_manager.py
==============================
Main exporter orchestrator. Gathers completed/failed datasets from the database,
triggers CSV/Excel writers, and initiates report compilation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.database.repository import BaseRepository
from .csv_exporter import CSVExporter
from .excel_exporter import ExcelExporter
from .report_generator import ReportGenerator
from .export_metrics import ExportMetrics

logger = logging.getLogger(__name__)


class ExportManager:
    """
    Orchestrates the complete dataset export process.
    """

    def __init__(
        self,
        repository: BaseRepository,
        metrics_file: str = "logs/export_metrics.json"
    ) -> None:
        self.repo = repository
        self.metrics = ExportMetrics(metrics_file)
        self.csv_exporter = CSVExporter(self.metrics)
        self.excel_exporter = ExcelExporter(self.metrics)

    def export_all(self, export_dir: str = "data/export") -> Dict[str, str]:
        """
        Loads dataset records from the repository and runs the exports/reports.
        
        Returns:
            Dict containing the file paths generated.
        """
        logger.info(f"[ExportManager] Initiating complete export to directory: {export_dir}")
        export_path = Path(export_dir)
        export_path.mkdir(parents=True, exist_ok=True)

        generated_files = {}

        try:
            # 1. Fetch completed, failed, and retry records from database
            completed_profiles = self.repo.get_all_completed()
            failed_records = self.repo.get_all_failed()
            retry_records = self.repo.get_all_retries()
            
            # 2. Export completed contacts to CSV and Excel
            completed_csv_path = export_path / "completed_contacts.csv"
            self.csv_exporter.export(completed_profiles, str(completed_csv_path))
            generated_files["completed_csv"] = str(completed_csv_path)

            completed_xlsx_path = export_path / "completed_contacts.xlsx"
            self.excel_exporter.export(completed_profiles, str(completed_xlsx_path))
            generated_files["completed_excel"] = str(completed_xlsx_path)

            # 3. Export failed records list to CSV for raw tracking
            if failed_records:
                import csv
                failed_csv_path = export_path / "failed_records.csv"
                with open(failed_csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["id", "npi", "company_name", "website", "error_message", "failed_at"])
                    for fr in failed_records:
                        writer.writerow([
                            fr.get("id"),
                            fr.get("npi") or "",
                            fr.get("company_name") or "",
                            fr.get("website") or "",
                            fr.get("error_message") or "",
                            fr.get("failed_at") or ""
                        ])
                generated_files["failed_csv"] = str(failed_csv_path)
                logger.info(f"[ExportManager] Exported {len(failed_records)} raw failed records to CSV.")

            # 4. Filter resolved duplicates from database (records marked Merged or having duplicate resolution)
            # Find Completed profiles where extraction_method == 'Merged' as database-level duplicates
            db_duplicates = []
            for p in completed_profiles:
                if p.extraction_method == "Merged":
                    db_duplicates.append({
                        "npi": getattr(p, "npi", "N/A"),
                        "company_name": p.business_name,
                        "website": p.official_website,
                        "resolution": f"Identified as duplicate (website/NPI match). Merged details. Confidence: {p.confidence}"
                    })

            # 5. Generate Markdown reports
            summary_path = export_path / "summary_report.md"
            # Get pending retries count
            pending_retries_count = len([r for r in retry_records if r.get("status") == "pending"])
            
            ReportGenerator.generate_summary_report(
                completed_count=len(completed_profiles),
                failed_count=len(failed_records),
                retry_count=pending_retries_count,
                duplicate_count=len(db_duplicates),
                filepath=str(summary_path)
            )
            generated_files["summary_report"] = str(summary_path)

            failed_report_path = export_path / "failed_records_report.md"
            ReportGenerator.generate_failed_report(failed_records, str(failed_report_path))
            generated_files["failed_report"] = str(failed_report_path)

            duplicate_report_path = export_path / "duplicate_report.md"
            ReportGenerator.generate_duplicate_report(db_duplicates, str(duplicate_report_path))
            generated_files["duplicate_report"] = str(duplicate_report_path)

            stats_report_path = export_path / "statistics_report.md"
            # Trigger stats report gathering JSON files
            ReportGenerator.generate_statistics_report(
                filepath=str(stats_report_path)
            )
            generated_files["statistics_report"] = str(stats_report_path)

            logger.info(f"[ExportManager] Export process finalized successfully. Generated {len(generated_files)} files.")
        except Exception as e:
            logger.error(f"[ExportManager] Export execution failed: {e}")
            raise e

        return generated_files
