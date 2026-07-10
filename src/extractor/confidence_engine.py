"""
src/extractor/confidence_engine.py
==================================
Heuristic-based scoring engine for contact extraction quality.
"""

from __future__ import annotations

from typing import List
from urllib.parse import urlparse
from .contact_page_detector import ContactPageDetector


class ConfidenceEngine:
    """
    Computes confidence metrics for extracted contacts using location, domain matching, and context heuristics.
    """

    GENERIC_DOMAINS = {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "live.com", "aol.com", "icloud.com", "mail.com", "zoho.com",
        "protonmail.com", "proton.me", "yandex.com", "gmx.com"
    }

    @classmethod
    def compute_email_confidence(
        cls,
        email: str,
        page_url: str,
        is_mailto: bool,
        is_in_footer: bool,
        website_url: str
    ) -> float:
        """
        Calculates confidence score (0.0 to 1.0) for an email address.
        """
        score = 0.60  # default base score

        if is_mailto:
            score = 0.95
        
        # Check if extracted on a contact page
        contact_page_score = ContactPageDetector.evaluate_link(page_url, "", website_url)
        if contact_page_score >= 0.8:
            score += 0.10
        elif contact_page_score >= 0.5:
            score += 0.05

        # Check if in footer
        if is_in_footer:
            score += 0.05

        # Check domain matching
        try:
            email_domain = email.split("@")[1].lower().strip()
            parsed_web = urlparse(website_url)
            web_domain = parsed_web.netloc.replace("www.", "").lower().strip()

            if email_domain == web_domain or web_domain in email_domain:
                score += 0.10
            elif email_domain in cls.GENERIC_DOMAINS:
                # No penalty for generic email domains (common for small businesses)
                pass
            else:
                # Slight penalty if it's a completely different third-party business domain
                score -= 0.10
        except Exception:
            pass

        return min(max(round(score, 2), 0.0), 1.0)

    @classmethod
    def compute_phone_confidence(
        cls,
        phone: str,
        page_url: str,
        is_tel: bool,
        is_in_footer: bool,
        website_url: str
    ) -> float:
        """
        Calculates confidence score (0.0 to 1.0) for a phone number.
        """
        score = 0.65  # default base score

        if is_tel:
            score = 0.95

        # Check if extracted on a contact page
        contact_page_score = ContactPageDetector.evaluate_link(page_url, "", website_url)
        if contact_page_score >= 0.8:
            score += 0.10
        elif contact_page_score >= 0.5:
            score += 0.05

        # Check if in footer
        if is_in_footer:
            score += 0.05

        return min(max(round(score, 2), 0.0), 1.0)

    @classmethod
    def get_aggregate_confidence(cls, email_scores: List[float], phone_scores: List[float]) -> float:
        """
        Calculates an aggregate confidence score for the entire profile.
        """
        all_scores = email_scores + phone_scores
        if not all_scores:
            return 0.0
        # Return average of top scores or a weighted score
        return round(sum(all_scores) / len(all_scores), 2)
