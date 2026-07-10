"""
src/scraper/scraper_result.py
==============================
Models representing the output of individual page scraping operations.
"""

from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field


class ScrapedPage(BaseModel):
    """
    Representation of raw scraping output from a single URL.
    """
    url: str = Field(description="The URL of the scraped page.")
    status_code: int = Field(default=0, description="HTTP status code returned (0 if network failure).")
    html: str = Field(default="", description="Raw HTML string extracted from the page.")
    headers: Dict[str, str] = Field(default_factory=dict, description="Response headers from the server.")
    error_message: Optional[str] = Field(default=None, description="Detailed error description if operation failed.")
    latency: float = Field(default=0.0, description="Time taken in seconds to scrape the page.")
    method: str = Field(default="HTTP", description="Method used to fetch page: 'HTTP' or 'Browser'.")
