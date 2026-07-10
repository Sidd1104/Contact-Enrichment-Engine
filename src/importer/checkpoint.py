"""
src/importer/checkpoint.py
===========================
Importer Checkpoint System.

Enables resuming long-running import tasks from the last completed batch
in the event of a crash or shutdown.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from ..config.importer_config import importer_config

logger = logging.getLogger(__name__)


class CheckpointSystem:
    """
    Saves and loads processing state checkpoints for individual datasets.
    """

    def __init__(self, checkpoint_dir: Optional[str] = None) -> None:
        self.checkpoint_dir = Path(checkpoint_dir or importer_config.checkpoint_directory)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, file_name: str, sheet_name: str) -> Path:
        """Generate a safe checkpoint filename for a file + sheet combination."""
        # Sanitize sheet name for path safety
        safe_sheet = "".join(c for c in sheet_name if c.isalnum() or c in ("-", "_")).rstrip()
        safe_filename = f"{Path(file_name).stem}_{safe_sheet}_checkpoint.json"
        return self.checkpoint_dir / safe_filename

    def save_checkpoint(
        self,
        file_name: str,
        sheet_name: str,
        last_batch_index: int,
        processed_count: int,
        skipped_count: int,
        queued_count: int,
    ) -> None:
        """
        Save the current processing state checkpoint to a JSON file.
        """
        checkpoint_path = self._get_checkpoint_path(file_name, sheet_name)
        data: Dict[str, Any] = {
            "file_name": file_name,
            "sheet_name": sheet_name,
            "last_batch_index": last_batch_index,
            "processed_count": processed_count,
            "skipped_count": skipped_count,
            "queued_count": queued_count,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            logger.info(
                f"[CheckpointSystem] Checkpoint saved successfully: index={last_batch_index}, "
                f"processed={processed_count}, queued={queued_count} to {checkpoint_path.name}"
            )
        except Exception as e:
            logger.error(f"[CheckpointSystem] Failed to save checkpoint to {checkpoint_path}: {e}")

    def load_checkpoint(self, file_name: str, sheet_name: str) -> Optional[Dict[str, Any]]:
        """
        Load the checkpoint for a file + sheet if it exists and is valid.
        """
        checkpoint_path = self._get_checkpoint_path(file_name, sheet_name)
        if not checkpoint_path.exists():
            logger.info(f"[CheckpointSystem] No checkpoint found for {file_name} [{sheet_name}]. Starting fresh.")
            return None

        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(
                f"[CheckpointSystem] Loaded checkpoint for {file_name} [{sheet_name}]: "
                f"resuming from batch index={data.get('last_batch_index')}, "
                f"previous processed={data.get('processed_count')}, queued={data.get('queued_count')}"
            )
            return data
        except Exception as e:
            logger.warning(f"[CheckpointSystem] Failed to read checkpoint {checkpoint_path}: {e}. Discarding.")
            return None

    def clear_checkpoint(self, file_name: str, sheet_name: str) -> None:
        """
        Delete checkpoint file when import completes successfully.
        """
        checkpoint_path = self._get_checkpoint_path(file_name, sheet_name)
        if checkpoint_path.exists():
            try:
                os.remove(checkpoint_path)
                logger.info(f"[CheckpointSystem] Cleared checkpoint: {checkpoint_path.name}")
            except Exception as e:
                logger.error(f"[CheckpointSystem] Failed to remove checkpoint file: {e}")
