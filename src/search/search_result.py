"""
src/search/search_result.py
============================
Structured Search Result Models.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class SearchResolution(BaseModel):
    """
    Standardized result representing the resolution outcome of a website search.
    """
    query: str = Field(description="The search query constructed for the entity.")
    resolved_url: str = Field(default="", description="The resolved official business URL (or empty if none).")
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence ranking of the resolved website (0.0 to 1.0)."
    )
    provider_used: str = Field(default="", description="The search API provider used (e.g. 'tavily', 'bing', 'cache').")
    latency: float = Field(default=0.0, description="Execution time in seconds.")
    cache_hit: bool = Field(default=False, description="Whether the result was retrieved from cache.")
    status: str = Field(
        default="success",
        description="Outcome state: 'success', 'skipped', 'failed'."
    )
    error_message: Optional[str] = Field(default=None, description="Detailed error description if execution failed.")
