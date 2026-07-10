"""
src/ai/models/response.py
==========================
Structured output models for AI extraction.

These Pydantic models define the exact JSON schema that AI providers
should return. They serve as both validation contracts and documentation
for the expected output format.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class EnrichedContact(BaseModel):
    """
    Structured contact details extracted by an AI provider.
    
    This model is used both as the Pydantic validation target and
    (for providers that support it) as the JSON Schema hint sent
    in the API request to guarantee structured output.
    """
    first_name: str = Field(default="", description="First name of the contact person.")
    last_name: str = Field(default="", description="Last name of the contact person.")
    email: str = Field(default="", description="Business email address.")
    phone: str = Field(default="", description="Phone number with area code.")
    city: str = Field(default="", description="City of the business location.")
    state: str = Field(default="", description="State or province.")
    specialty: str = Field(default="", description="Professional specialty or focus area.")
    credential: str = Field(default="", description="Professional credential (e.g. MD, DO).")
    license_number: str = Field(default="", description="State licensing number.")
    license_state: str = Field(default="", description="State that issued the license.")
    source_website: str = Field(default="", description="URL where the information was found.")
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence level of the extracted data (0.0 to 1.0)."
    )


class SearchResult(BaseModel):
    """
    Structured search result from a web discovery query.
    """
    title: str = Field(default="", description="Page title of the search result.")
    url: str = Field(default="", description="URL of the search result.")
    snippet: str = Field(default="", description="Text snippet from the search result.")
    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated relevance to the search query."
    )


class ExtractionResult(BaseModel):
    """
    Complete extraction result combining contact data with metadata.
    """
    contact: EnrichedContact = Field(
        default_factory=EnrichedContact,
        description="Extracted contact information."
    )
    raw_response: str = Field(
        default="",
        description="Raw AI response text (for debugging)."
    )
    provider_used: str = Field(
        default="",
        description="Name of the AI provider that generated this result."
    )
    model_used: str = Field(
        default="",
        description="Specific model identifier used."
    )
    extraction_latency: float = Field(
        default=0.0,
        description="Time in seconds to produce this extraction."
    )
