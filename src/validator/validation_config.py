"""
src/validator/validation_config.py
===================================
Loads environment variables for validation thresholds, fallback toggle, and matching rules.
"""

from __future__ import annotations

import os
from pydantic import BaseModel, Field


class ValidationConfig(BaseModel):
    """
    Configuration settings for validation and AI enrichment routing.
    """
    validation_confidence_threshold: float = Field(
        default=0.8,
        description="Scraper confidence score below which AI fallback is triggered."
    )
    ai_confidence_threshold: float = Field(
        default=0.7,
        description="Target confidence threshold below which AI results are marked low-confidence."
    )
    enable_ai_fallback: bool = Field(
        default=True,
        description="Flag to toggle AI extraction fallback."
    )
    max_ai_retries: int = Field(
        default=3,
        description="Maximum retries permitted on transient AI failures."
    )
    max_duplicate_distance: int = Field(
        default=2,
        description="Maximum Levenshtein distance for duplicate name grouping."
    )

    @classmethod
    def from_env(cls) -> ValidationConfig:
        """
        Creates config instance reading directly from environment variables.
        """
        return cls(
            validation_confidence_threshold=float(os.getenv("VALIDATION_CONFIDENCE_THRESHOLD", "0.8")),
            ai_confidence_threshold=float(os.getenv("AI_CONFIDENCE_THRESHOLD", "0.7")),
            enable_ai_fallback=os.getenv("ENABLE_AI_FALLBACK", "true").lower() == "true",
            max_ai_retries=int(os.getenv("MAX_AI_RETRIES", "3")),
            max_duplicate_distance=int(os.getenv("MAX_DUPLICATE_DISTANCE", "2")),
        )


validation_config = ValidationConfig.from_env()
