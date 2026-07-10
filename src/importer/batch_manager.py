"""
src/importer/batch_manager.py
==============================
Batch Manager and Generator.

Splits records into partition blocks based on IMPORT_BATCH_SIZE and yields them.
Allows skipping blocks when resuming from checkpoints.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Generator, List, Optional
from ..config.importer_config import importer_config

logger = logging.getLogger(__name__)


class BatchManager:
    """
    Slices lists of records into yieldable batches.
    """

    def __init__(self, records: List[Dict[str, Any]], batch_size: Optional[int] = None) -> None:
        self.records = records
        self.batch_size = batch_size or importer_config.import_batch_size
        self.total_records = len(records)
        
        # Calculate total batch count
        if self.total_records == 0:
            self.total_batches = 0
        else:
            self.total_batches = (self.total_records + self.batch_size - 1) // self.batch_size
            
        logger.info(
            f"[BatchManager] Initialized with {self.total_records} records, "
            f"batch_size={self.batch_size}, total_batches={self.total_batches}"
        )

    def generate_batches(self, start_batch_index: int = 0) -> Generator[Tuple[int, List[Dict[str, Any]]], None, None]:
        """
        Yield partition batches starting from a specific batch index.
        
        Args:
            start_batch_index: 0-indexed starting point. Batches before this index are skipped.
            
        Yields:
            Tuple of (batch_index, list of record dictionaries in that batch).
        """
        if start_batch_index > 0:
            logger.info(f"[BatchManager] Resuming/Skipping to start_batch_index={start_batch_index}")

        for i in range(start_batch_index, self.total_batches):
            start_idx = i * self.batch_size
            end_idx = min(start_idx + self.batch_size, self.total_records)
            batch = self.records[start_idx:end_idx]
            
            logger.debug(f"[BatchManager] Yielding batch {i+1}/{self.total_batches} (size={len(batch)})")
            yield i, batch
