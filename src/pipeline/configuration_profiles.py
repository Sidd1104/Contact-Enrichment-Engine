"""
src/pipeline/configuration_profiles.py
======================================
Defines execution profiles (Development, Testing, Production, High Throughput).
Configures concurrency limits, batch sizes, timeouts, and logging levels.
"""

from __future__ import annotations

from typing import Dict, Any
from pydantic import BaseModel, Field


class PipelineProfile(BaseModel):
    """
    Schema for execution configuration profiles.
    """
    profile_name: str
    worker_count: int = Field(default=2, description="Number of workers in async pool.")
    batch_size: int = Field(default=10, description="Size of record partitions for processing/DB writes.")
    timeout: float = Field(default=30.0, description="General network/API timeout.")
    retry_limit: int = Field(default=3, description="Maximum transient retry attempts.")
    logging_level: str = Field(default="INFO", description="Standard logging output level.")
    max_concurrency: int = Field(default=5, description="Maximum concurrent connections/requests.")


# Predefined configurations
PROFILES: Dict[str, PipelineProfile] = {
    "development": PipelineProfile(
        profile_name="development",
        worker_count=2,
        batch_size=5,
        timeout=15.0,
        retry_limit=2,
        logging_level="DEBUG",
        max_concurrency=3
    ),
    "testing": PipelineProfile(
        profile_name="testing",
        worker_count=3,
        batch_size=5,
        timeout=10.0,
        retry_limit=1,
        logging_level="INFO",
        max_concurrency=4
    ),
    "production": PipelineProfile(
        profile_name="production",
        worker_count=5,
        batch_size=20,
        timeout=30.0,
        retry_limit=3,
        logging_level="INFO",
        max_concurrency=10
    ),
    "high_throughput": PipelineProfile(
        profile_name="high_throughput",
        worker_count=10,
        batch_size=50,
        timeout=60.0,
        retry_limit=5,
        logging_level="WARNING",
        max_concurrency=20
    )
}


def get_profile(name: str) -> PipelineProfile:
    """Resolves a configuration profile by name, falling back to production."""
    normalized_name = name.lower().strip()
    if normalized_name not in PROFILES:
        import logging
        logging.getLogger(__name__).warning(
            f"Configuration profile '{name}' not found. Falling back to 'production'."
        )
        return PROFILES["production"]
    return PROFILES[normalized_name]
