"""
src/importer/importer.py
=========================
Importer Main Orchestrator.

Coordinates Excel reading, dynamic schema mapping, smart filtering, batching,
checkpoint tracking, and stats recording into a simple public yield generator.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .excel_reader import ExcelReader
from .schema_detector import SchemaDetector
from .row_mapper import RowMapper
from .filters import ImportFilter
from .checkpoint import CheckpointSystem
from .batch_manager import BatchManager
from .statistics import ImportStatistics
from ..config.importer_config import importer_config

logger = logging.getLogger(__name__)


class ImportEngine:
    """
    Main orchestrator for Excel ingestion pipelines.
    """

    def __init__(
        self,
        input_dir: Optional[str] = None,
        checkpoint_dir: Optional[str] = None,
        batch_size: Optional[int] = None,
    ) -> None:
        self.reader = ExcelReader(input_dir)
        self.checkpoint_sys = CheckpointSystem(checkpoint_dir)
        self.stats_sys = ImportStatistics()
        self.batch_size = batch_size or importer_config.import_batch_size

    def initialize_import(self, file_path: Optional[Path] = None) -> Tuple[Path, str, Dict[str, str], List[Dict[str, Any]]]:
        """
        Scan directory, select file/sheet, detect schema, and load raw records.
        """
        logger.info("[ImportEngine] Initializing import process...")
        start_time = time.monotonic()

        # 1. Locate file
        if file_path:
            target_file = Path(file_path)
        else:
            target_file = self.reader.detect_primary_file()
        logger.info(f"[ImportEngine] Target file selected: {target_file.name}")

        # 2. Select sheet
        sheet_name = self.reader.detect_primary_sheet(target_file)
        logger.info(f"[ImportEngine] Worksheet selected: '{sheet_name}'")

        # 3. Read sheet rows
        headers, raw_rows = self.reader.read_rows(target_file, sheet_name)

        # 4. Detect schema mapping
        detector = SchemaDetector(headers)
        mapping = detector.detect_mapping()
        logger.info(f"[ImportEngine] Detected schema mapping: {mapping}")

        duration = time.monotonic() - start_time
        logger.info(f"[ImportEngine] Ingested raw file in {duration:.2f}s")
        return target_file, sheet_name, mapping, raw_rows

    def process_records(
        self,
        raw_rows: List[Dict[str, Any]],
        mapping: Dict[str, str],
    ) -> Tuple[List[Dict[str, Any]], int, int, int]:
        """
        Process, normalize, filter and deduplicate raw records.
        
        Returns:
            Tuple of (list of mapped eligible records, completed count, skipped empty count, duplicate count).
        """
        row_filter = ImportFilter()
        row_mapper = RowMapper(mapping)

        eligible_records: List[Dict[str, Any]] = []
        completed_count = 0
        skipped_empty = 0
        duplicate_count = 0

        for row in raw_rows:
            # Skip entirely empty rows
            if row_filter.is_row_empty(row, mapping):
                skipped_empty += 1
                continue

            # Standardize raw row mapping
            mapped_row = row_mapper.map_row(row)

            # Skip duplicate primary keys (NPI)
            if row_filter.is_duplicate(mapped_row):
                duplicate_count += 1
                continue

            # Check if record is already complete (has both phone and email)
            if row_filter.is_fully_enriched(mapped_row):
                completed_count += 1
                continue

            # Record is eligible for enrichment queue
            eligible_records.append(mapped_row)

        logger.info(
            f"[ImportEngine] Filtering summary: total={len(raw_rows)}, "
            f"eligible={len(eligible_records)}, completed={completed_count}, "
            f"duplicates={duplicate_count}, empty={skipped_empty}"
        )
        return eligible_records, completed_count, skipped_empty, duplicate_count

    def import_generator(
        self,
        file_path: Optional[Path] = None,
        reset_checkpoint: bool = False,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Core yield generator that processes the Excel dataset in batches.
        Resumes from a checkpoint if available.
        
        Yields:
            List of standardized dictionary records representing a batch to process.
        """
        # 1. Initialize file, sheet, schema, rows
        target_file, sheet_name, mapping, raw_rows = self.initialize_import(file_path)
        file_name = target_file.name

        # 2. Filter, map, and deduplicate rows
        eligible_records, completed_count, skipped_empty, duplicate_count = self.process_records(raw_rows, mapping)

        # 3. Load or clear checkpoints
        checkpoint = None
        if not reset_checkpoint:
            checkpoint = self.checkpoint_sys.load_checkpoint(file_name, sheet_name)

        start_batch_index = 0
        processed_count = 0
        skipped_count = completed_count + duplicate_count + skipped_empty
        queued_count = 0

        if checkpoint:
            start_batch_index = checkpoint.get("last_batch_index", 0)
            processed_count = checkpoint.get("processed_count", 0)
            queued_count = checkpoint.get("queued_count", 0)
            # Re-adjust stats with resumed indices
            logger.info(f"[ImportEngine] Resuming from checkpoint at batch {start_batch_index}")
        else:
            logger.info("[ImportEngine] Starting fresh batch ingestion.")

        # 4. Divide into batches
        batch_manager = BatchManager(eligible_records, self.batch_size)
        start_time = time.monotonic()

        # If we have no records, complete immediately
        if batch_manager.total_batches == 0:
            logger.info("[ImportEngine] No eligible records to process.")
            # Clear checkpoints and save report
            self.checkpoint_sys.clear_checkpoint(file_name, sheet_name)
            self.stats_sys.generate_report(
                file_name=file_name,
                sheet_name=sheet_name,
                total_records=len(raw_rows),
                completed_records=len(raw_rows) - len(eligible_records) - duplicate_count - skipped_empty,
                queued_records=0,
                duplicates_count=duplicate_count,
                batch_size=self.batch_size,
            )
            return

        # Iterate and yield batches
        for batch_index, batch_records in batch_manager.generate_batches(start_batch_index):
            yield batch_records
            
            # Post-batch bookkeeping
            processed_count += len(batch_records)
            queued_count += len(batch_records)
            
            # Save checkpoint state after successful batch yield
            self.checkpoint_sys.save_checkpoint(
                file_name=file_name,
                sheet_name=sheet_name,
                last_batch_index=batch_index + 1,  # save next start batch
                processed_count=processed_count,
                skipped_count=skipped_count,
                queued_count=queued_count,
            )

        # 5. Execution finalized
        duration = time.monotonic() - start_time
        logger.info(f"[ImportEngine] Batched import completed in {duration:.2f}s")

        # Clear checkpoint file
        self.checkpoint_sys.clear_checkpoint(file_name, sheet_name)

        # Generate and save final report statistics
        self.stats_sys.generate_report(
            file_name=file_name,
            sheet_name=sheet_name,
            total_records=len(raw_rows),
            completed_records=completed_count,
            queued_records=len(eligible_records),
            duplicates_count=duplicate_count,
            batch_size=self.batch_size,
        )
