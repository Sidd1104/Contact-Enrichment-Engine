"""
src/config/importer_config.py
==============================
Importer Engine Configurations.

Reads configurations from environment variables with safe defaults.
"""

from __future__ import annotations

import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class ImporterConfig(BaseModel):
    """
    Importer settings managed via environment variables.
    """
    import_batch_size: int = Field(
        default=100,
        description="Number of records to yield per batch partition."
    )
    input_directory: str = Field(
        default="data/input",
        description="Path where raw Excel source files reside."
    )
    checkpoint_directory: str = Field(
        default="data/temp",
        description="Path where JSON checkpoint files are saved."
    )
    max_memory_rows: int = Field(
        default=100000,
        description="Maximum number of rows allowed to load into memory."
    )

    @classmethod
    def from_env(cls) -> "ImporterConfig":
        return cls(
            import_batch_size=int(os.getenv("IMPORT_BATCH_SIZE", "100")),
            input_directory=os.getenv("INPUT_DIRECTORY", "data/input"),
            checkpoint_directory=os.getenv("CHECKPOINT_DIRECTORY", "data/temp"),
            max_memory_rows=int(os.getenv("MAX_MEMORY_ROWS", "100000")),
        )


importer_config = ImporterConfig.from_env()
