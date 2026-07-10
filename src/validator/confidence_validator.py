"""
src/validator/confidence_validator.py
======================================
Evaluates and assigns final confidence scores to business profiles.
"""

from __future__ import annotations

import logging
from .business_profile_validator import BusinessProfile

logger = logging.getLogger(__name__)


class ConfidenceValidator:
    """
    Computes unified confidence scores considering source data quality,
    validation statuses, and AI extractions.
    """

    @classmethod
    def calculate(
        cls,
        profile: BusinessProfile,
        has_contact_page: bool = False,
        has_footer: bool = False,
        source_reliability: float = 1.0
    ) -> float:
        """
        Calculates a final confidence score (0.0 to 1.0) for a BusinessProfile.
        """
        # Baseline confidence is the current score in the profile
        score = profile.confidence

        # If baseline is not set, calculate a base score from contents
        if score <= 0.0:
            if profile.emails:
                score += 0.50
            if profile.phones:
                score += 0.40

        # Adjustments based on validation elements
        # 1. Email validity boost
        if profile.emails:
            # Boost if we have validated emails
            score += 0.05
        
        # 2. Phone validity boost
        if profile.phones:
            # Boost if we have validated phones
            score += 0.05

        # 3. Page layout locations
        if has_contact_page:
            score += 0.05
        if has_footer:
            score += 0.05

        # 4. Website quality penalties (deduct 0.05 for each runtime scraping error)
        if profile.errors:
            penalty = 0.05 * len(profile.errors)
            score -= penalty

        # Apply source reliability multiplier (default 1.0 for first-party official site)
        score *= source_reliability

        # Keep within strict bounds 0.0 to 1.0
        final_score = min(max(round(score, 2), 0.0), 1.0)
        logger.info(f"[Confidence] Calculated profile score: {final_score} (Original: {profile.confidence})")
        return final_score
