"""
src/ai/enrichment_result.py
============================
Defines the Pydantic schema target for Gemini structured outputs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AIEnrichmentResult(BaseModel):
    """
    Pydantic model representing structured contact details returned by Gemini.
    """
    official_email: str = Field(
        default="",
        description="The primary official contact email address for the business."
    )
    official_phone: str = Field(
        default="",
        description="The primary official contact phone number for the business."
    )
    reasoning: str = Field(
        default="",
        description="A brief explanation of how the contact details were verified or identified."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence score between 0.0 and 1.0."
    )
class AIEnrichmentResponseModel(BaseModel):
    """
    Wrapper for AIEnrichmentResult to structure the AI's response properly.
    """
    enrichment: AIEnrichmentResult = Field(
        description="Extracted enrichment contact detail fields."
    )
