"""
src/database/bulk_writer.py
===========================
Executes database write operations in configurable batches.
Provides automatic retry capabilities on lock/transaction failures, logs metrics,
and channels failures to the retry/failed persistence layers.
"""

from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from src.validator.business_profile_validator import BusinessProfile
from .repository import BaseRepository
from .retry_repository import RetryRepository

logger = logging.getLogger(__name__)


class DatabaseMetrics:
    """
    Measures and persists performance counters and speeds for database writes.
    Tracks statistics in logs/database_metrics.json.
    """

    def __init__(self, filepath: str = "logs/database_metrics.json") -> None:
        self.filepath = Path(filepath)
        self.total_inserts = 0
        self.total_updates = 0
        self.failed_writes = 0
        self.retries = 0
        self.total_write_time = 0.0
        self.sessions_count = 0
        self.load()

    def load(self) -> None:
        """Loads metrics from disk if they exist, facilitating cumulative runs."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                
                counts = data.get("counts", {})
                self.total_inserts = counts.get("total_inserts", 0)
                self.total_updates = counts.get("total_updates", 0)
                self.failed_writes = counts.get("failed_writes", 0)
                self.retries = counts.get("retries", 0)

                perf = data.get("performance", {})
                self.total_write_time = perf.get("total_write_time_seconds", 0.0)
                self.sessions_count = perf.get("sessions_count", 0)
            except Exception as e:
                logger.warning(f"Could not load database metrics: {e}. Starting fresh.")

    def record_write(self, inserts: int, updates: int, latency: float) -> None:
        """Tracks successful writes and durations."""
        self.total_inserts += inserts
        self.total_updates += updates
        self.total_write_time += latency
        self.sessions_count += 1

    def record_failure(self, count: int = 1) -> None:
        """Tracks occurrences of write failures."""
        self.failed_writes += count

    def record_retry(self, count: int = 1) -> None:
        """Tracks transient lock/transaction retries."""
        self.retries += count

    def save(self) -> None:
        """Saves metrics report JSON to disk."""
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            
            avg_ins_speed = (self.total_inserts / self.total_write_time) if self.total_write_time > 0 else 0.0
            avg_upd_speed = (self.total_updates / self.total_write_time) if self.total_write_time > 0 else 0.0
            
            report = {
                "counts": {
                    "total_inserts": self.total_inserts,
                    "total_updates": self.total_updates,
                    "failed_writes": self.failed_writes,
                    "retries": self.retries
                },
                "performance": {
                    "total_write_time_seconds": round(self.total_write_time, 3),
                    "sessions_count": self.sessions_count,
                    "average_insert_speed_records_per_sec": round(avg_ins_speed, 2),
                    "average_update_speed_records_per_sec": round(avg_upd_speed, 2)
                }
            }
            with open(self.filepath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save database metrics: {e}")


class BulkWriter:
    """
    Buffers and writes contacts to the database with batch size management and retry safeguards.
    """

    def __init__(
        self,
        repo: BaseRepository,
        batch_size: int = 100,
        max_retries: int = 3,
        metrics_file: str = "logs/database_metrics.json"
    ) -> None:
        self.repo = repo
        self.retry_repo = RetryRepository(repo)
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.metrics = DatabaseMetrics(metrics_file)

    def write_profiles(
        self,
        profiles: List[BusinessProfile],
        raw_records: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[int, int]:
        """
        Saves a list of validated business profiles. Handles batch partition and handles
        database errors with retries. On absolute failure, writes to failed records database.
        
        Returns:
            Tuple of (total_inserts, total_updates).
        """
        if not profiles:
            return 0, 0

        total_ins = 0
        total_upd = 0

        # Break down into batches
        for i in range(0, len(profiles), self.batch_size):
            batch_profiles = profiles[i:i + self.batch_size]
            batch_raw = None
            if raw_records:
                batch_raw = raw_records[i:i + self.batch_size]

            ins, upd = self._write_batch_with_retry(batch_profiles, batch_raw)
            total_ins += ins
            total_upd += upd

        self.metrics.save()
        return total_ins, total_upd

    def _write_batch_with_retry(
        self,
        batch_profiles: List[BusinessProfile],
        batch_raw: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[int, int]:
        """Runs batch insertion within a transaction wrapper, retrying on connection/lock error."""
        attempts = 0
        while attempts < self.max_retries:
            start_time = time.perf_counter()
            try:
                # Attempt to save batch
                inserts, updates = self.repo.save_completed_batch(batch_profiles, batch_raw)
                latency = time.perf_counter() - start_time
                self.metrics.record_write(inserts, updates, latency)
                logger.info(
                    f"[BulkWriter] Successfully wrote batch: inserts={inserts}, "
                    f"updates={updates} in {latency:.3f}s"
                )
                return inserts, updates
            except Exception as e:
                attempts += 1
                self.metrics.record_retry()
                logger.warning(
                    f"[BulkWriter] Write batch failed (attempt {attempts}/{self.max_retries}): {e}. "
                    "Retrying..."
                )
                if attempts >= self.max_retries:
                    # Permanent failure for this batch
                    latency = time.perf_counter() - start_time
                    self.metrics.record_failure(len(batch_profiles))
                    
                    # Store failed records
                    failed_records = []
                    error_messages = []
                    for profile in batch_profiles:
                        rec = {
                            "npi": getattr(profile, "npi", None),
                            "business_name": profile.business_name,
                            "website": profile.official_website
                        }
                        failed_records.append(rec)
                        error_messages.append(f"Database bulk write failure: {e}")
                    
                    try:
                        self.repo.save_failed_batch(failed_records, error_messages)
                    except Exception as fe:
                        logger.critical(f"[BulkWriter] Could not even write failures to DB: {fe}")
                    
                    logger.error(f"[BulkWriter] Batch of {len(batch_profiles)} profiles failed permanently. Saved to failed_records.")
                    break
                time.sleep(0.5 * attempts)  # Back off
        return 0, 0
