"""
src/ai/enrichment_prompts.py
=============================
Houses reusable prompts used to instruct Gemini to find or verify contact details.
"""

from __future__ import annotations


class EnrichmentPrompts:
    """
    Templates for generating prompts instructing AI providers to extract contact profiles.
    """

    ENRICHMENT_TEMPLATE = """
You are a professional data analysis assistant for the Contact Enrichment Engine.
Your task is to analyze the provided web crawl transcripts and identify the official contact details for the specified business.

Target Business Name: {business_name}
Target Business Website: {website_url}

=== Crawled Website Text Snippets ===
{crawled_text}
=====================================

Instructions:
1. Examine the crawled texts (if any) and identify the official business email and official phone number.
2. If multiple emails/phones are found, identify the most general or official one (e.g. info@, support@, office@, or main clinic number).
3. Do not invent or guess information. If a detail is missing, return an empty string.
4. Normalize phone numbers if found.
5. Provide your brief reasoning and self-assessed confidence score (0.0 to 1.0) based on source clarity.

You must return a structured JSON response matching the required schema.
"""

    @classmethod
    def get_enrichment_prompt(cls, business_name: str, website_url: str, crawled_text: str) -> str:
        """
        Builds a customized prompt string using target business variables.
        """
        # Truncate crawled text to prevent token overflows (e.g., limit to 8000 characters)
        truncated_text = crawled_text[:8000] if crawled_text else "[No text successfully crawled from website]"
        return cls.ENRICHMENT_TEMPLATE.format(
            business_name=business_name,
            website_url=website_url,
            crawled_text=truncated_text
        )
