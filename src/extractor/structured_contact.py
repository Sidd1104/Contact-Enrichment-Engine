"""
src/extractor/structured_contact.py
===================================
Defines the final schema contract for extracted contact results.
"""

from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field


class StructuredContact(BaseModel):
    """
    Standardized contact representation returned by the Website Acquisition Pipeline.
    """
    business_name: str = Field(
        default="",
        description="Name of the business extracted from metadata/JSON-LD."
    )
    official_website: str = Field(
        description="Root URL of the business website."
    )
    emails: List[str] = Field(
        default_factory=list,
        description="List of unique contact email addresses."
    )
    phones: List[str] = Field(
        default_factory=list,
        description="List of unique contact phone numbers in normalized format."
    )
    social_links: Dict[str, str] = Field(
        default_factory=lambda: {
            "linkedin": "",
            "facebook": "",
            "instagram": "",
            "twitter": "",
            "youtube": "",
            "github": ""
        },
        description="Map of social platform names to profile links."
    )
    pages_visited: List[str] = Field(
        default_factory=list,
        description="List of URLs crawled during acquisition."
    )
    extraction_method: str = Field(
        default="HTTP",
        description="Primary technology used: 'HTTP' or 'Browser'."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence score of extraction (0.0 to 1.0)."
    )
    processing_time: float = Field(
        default=0.0,
        description="Total duration of extraction process in seconds."
    )
    errors: List[str] = Field(
        default_factory=list,
        description="List of issues or warning messages logged during pipeline run."
    )
