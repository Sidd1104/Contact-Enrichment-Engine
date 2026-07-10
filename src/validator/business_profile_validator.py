"""
src/validator/business_profile_validator.py
============================================
Defines the Pydantic model for the unified BusinessProfile and validates completeness.
"""

from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field


class BusinessProfile(BaseModel):
    """
    Unified business profile standardizing scraped and AI-enriched data.
    """
    business_name: str = Field(
        default="",
        description="Identified company/business name."
    )
    official_website: str = Field(
        default="",
        description="Root URL of the business website."
    )
    emails: List[str] = Field(
        default_factory=list,
        description="Unique, syntactically validated email addresses."
    )
    phones: List[str] = Field(
        default_factory=list,
        description="Unique, E.164 normalized telephone numbers."
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
        description="Collected social platform profile links."
    )
    address: str = Field(
        default="",
        description="Aggregated postal mailing address."
    )
    pages_visited: List[str] = Field(
        default_factory=list,
        description="Subpages crawled during details gathering."
    )
    extraction_method: str = Field(
        default="HTTP",
        description="Technology used: 'HTTP', 'Browser', 'AI', or 'Merged'."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Heuristically computed final confidence score."
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Log of warning or runtime error strings."
    )
    provenance: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value mapping of field names to sources (e.g. {'emails': 'scraper', 'phones': 'AI'})."
    )


class BusinessProfileValidator:
    """
    Heuristics to check quality and completeness of a BusinessProfile.
    """

    @classmethod
    def is_complete(cls, profile: BusinessProfile) -> bool:
        """
        Returns True if the profile contains a name, website, and at least
        one email and one phone number with a non-zero confidence.
        """
        has_name = bool(profile.business_name.strip())
        has_website = bool(profile.official_website.strip())
        has_email = len(profile.emails) > 0
        has_phone = len(profile.phones) > 0
        has_conf = profile.confidence > 0.0

        return has_name and has_website and has_email and has_phone and has_conf
