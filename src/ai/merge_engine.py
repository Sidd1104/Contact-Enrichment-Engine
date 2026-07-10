"""
src/ai/merge_engine.py
========================
Combines scraper BusinessProfile outputs with AIEnrichmentResult fields.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set
from ..validator.business_profile_validator import BusinessProfile
from ..validator.email_validator import EmailValidator
from ..validator.phone_validator import PhoneValidator
from .enrichment_result import AIEnrichmentResult

logger = logging.getLogger(__name__)


class MergeEngine:
    """
    Implements prioritization and merging rules:
    - Never overwrite valid scraper data with lower-confidence AI data.
    - Prefer Validated -> Scraper -> AI.
    - Maintain field-level provenance tracking.
    """

    @classmethod
    def merge(
        cls,
        scraper_profile: BusinessProfile,
        ai_result: AIEnrichmentResult
    ) -> BusinessProfile:
        """
        Merges AI enrichment result into the scraper profile.
        Returns a new merged BusinessProfile.
        """
        # Create a deep copy of the scraper profile fields
        merged = BusinessProfile(
            business_name=scraper_profile.business_name,
            official_website=scraper_profile.official_website,
            address=scraper_profile.address,
            emails=list(scraper_profile.emails),
            phones=list(scraper_profile.phones),
            social_links=scraper_profile.social_links.copy(),
            pages_visited=list(scraper_profile.pages_visited),
            extraction_method=scraper_profile.extraction_method,
            confidence=scraper_profile.confidence,
            errors=list(scraper_profile.errors),
            provenance=scraper_profile.provenance.copy()
        )

        ai_merged_occurred = False

        # --- 1. Merge Emails ---
        ai_email = ai_result.official_email.strip().lower()
        if ai_email:
            validated_ai = EmailValidator.validate([ai_email])
            if validated_ai:
                email_to_add = validated_ai[0]
                
                # Check priority rules
                if not scraper_profile.emails:
                    # Scraper had no email, safe to use AI
                    merged.emails = [email_to_add]
                    merged.provenance["emails"] = "AI"
                    ai_merged_occurred = True
                    logger.info(f"[Merge] Added AI email: {email_to_add} (provenance=AI)")
                else:
                    # Scraper already has valid email(s).
                    # Check if the AI email is already present
                    if email_to_add not in scraper_profile.emails:
                        # Append the AI email, but keep provenance as primary scraper
                        merged.emails = list(scraper_profile.emails) + [email_to_add]
                        merged.provenance["emails"] = f"{scraper_profile.provenance.get('emails', 'scraper')},AI"
                        ai_merged_occurred = True
                        logger.info(f"[Merge] Appended AI email: {email_to_add} (provenance=scraper,AI)")
                    else:
                        logger.info(f"[Merge] AI email {email_to_add} already present in scraper data. Skipping overwrite.")

        # --- 2. Merge Phones ---
        ai_phone = ai_result.official_phone.strip()
        if ai_phone:
            validated_ai = PhoneValidator.validate([ai_phone])
            if validated_ai:
                phone_to_add = validated_ai[0]
                
                # Check priority rules
                if not scraper_profile.phones:
                    # Scraper had no phone, safe to use AI
                    merged.phones = [phone_to_add]
                    merged.provenance["phones"] = "AI"
                    ai_merged_occurred = True
                    logger.info(f"[Merge] Added AI phone: {phone_to_add} (provenance=AI)")
                else:
                    # Scraper already has valid phone(s).
                    if phone_to_add not in scraper_profile.phones:
                        # Append the AI phone, keeping scraper as primary
                        merged.phones = list(scraper_profile.phones) + [phone_to_add]
                        merged.provenance["phones"] = f"{scraper_profile.provenance.get('phones', 'scraper')},AI"
                        ai_merged_occurred = True
                        logger.info(f"[Merge] Appended AI phone: {phone_to_add} (provenance=scraper,AI)")
                    else:
                        logger.info(f"[Merge] AI phone {phone_to_add} already present in scraper data. Skipping overwrite.")

        # --- 3. Finalize Metadata & Confidence ---
        if ai_merged_occurred:
            merged.extraction_method = "Merged"
            # Update confidence to the max of scraper confidence and AI confidence
            merged.confidence = max(scraper_profile.confidence, ai_result.confidence)
            # Log the AI reasoning in errors/warnings as traceback detail
            if ai_result.reasoning:
                merged.errors.append(f"AI Reasoning: {ai_result.reasoning}")

        return merged
