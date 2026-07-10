"""
src/extractor/contact_page_detector.py
======================================
Heuristic evaluator to identify and rank candidate contact/about pages.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


class ContactPageDetector:
    """
    Evaluates links based on URL patterns and anchor text to find contact, about, or team pages.
    """

    # High priority keywords (direct contacts)
    CONTACT_KEYWORDS = [
        r"contact",
        r"contat",
        r"support",
        r"help",
        r"location",
        r"find-us",
        r"reach-us",
        r"address",
        r"office",
        r"phone",
        r"email"
    ]

    # Medium priority keywords (general about/team info)
    ABOUT_KEYWORDS = [
        r"about",
        r"team",
        r"staff",
        r"physician",
        r"doctor",
        r"provider",
        r"leadership",
        r"board",
        r"who-we-are",
        r"history"
    ]

    # Negative patterns (ignore external or unrelated resource pages)
    IGNORE_PATTERNS = [
        r"\.(pdf|png|jpg|jpeg|gif|zip|gz|docx|xlsx|csv)$",
        r"javascript:",
        r"mailto:",
        r"tel:",
        r"sms:",
        r"share",
        r"facebook",
        r"twitter",
        r"linkedin",
        r"instagram",
        r"youtube",
        r"pinterest",
        r"google"
    ]

    @classmethod
    def evaluate_link(cls, url: str, text: str, base_url: str) -> float:
        """
        Evaluate a link and return a score from 0.0 to 1.0 representing
        its likelihood of being a contact/about page.
        """
        url_lower = url.lower().strip()
        text_lower = text.lower().strip()

        # Check domain to ensure it is internal
        parsed_base = urlparse(base_url)
        parsed_url = urlparse(url)
        
        # If it has a netloc and it doesn't match base domain, skip
        if parsed_url.netloc and parsed_url.netloc != parsed_base.netloc:
            # Check for subdomains if needed, but strict domain match is safer
            base_domain = parsed_base.netloc.replace("www.", "")
            url_domain = parsed_url.netloc.replace("www.", "")
            if base_domain not in url_domain:
                return 0.0

        # Skip ignore patterns
        for pattern in cls.IGNORE_PATTERNS:
            if re.search(pattern, url_lower) or re.search(pattern, text_lower):
                return 0.0

        # Score calculations
        score = 0.0

        # Direct exact match of path
        path = parsed_url.path.strip("/")
        if path in ["contact", "contact-us", "contactus", "support"]:
            return 1.0
        if path in ["about", "about-us", "aboutus", "team", "our-team", "staff"]:
            return 0.9

        # Evaluate URL path
        for kw in cls.CONTACT_KEYWORDS:
            if re.search(r"\b" + kw + r"\b", path) or kw in path:
                score = max(score, 0.85)
            # Evaluate text
            if re.search(r"\b" + kw + r"\b", text_lower):
                score = max(score, 0.95)

        for kw in cls.ABOUT_KEYWORDS:
            if re.search(r"\b" + kw + r"\b", path) or kw in path:
                score = max(score, 0.70)
            if re.search(r"\b" + kw + r"\b", text_lower):
                score = max(score, 0.80)

        # Minor boost for links in footer or navigation if categorized (handled externally if layout info exists)
        # Length penalty (longer URLs are often nested blog posts or articles rather than landing pages)
        if len(path.split("/")) > 2:
            score *= 0.8

        return round(score, 3)
