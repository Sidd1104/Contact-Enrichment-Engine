"""
src/extractor/social_extractor.py
==================================
Extracts social media profile links from parsed HTML anchor elements.
"""

from __future__ import annotations

import re
from typing import Dict, List


class SocialExtractor:
    """
    Scans internal and external links to collect social media profiles,
    filtering out share utility endpoints.
    """

    SOCIAL_PATTERNS = {
        "linkedin": re.compile(r"linkedin\.com/(in|company)/[a-zA-Z0-9\-_%]+", re.IGNORECASE),
        "facebook": re.compile(r"facebook\.com/[a-zA-Z0-9\-_%\.]+", re.IGNORECASE),
        "instagram": re.compile(r"instagram\.com/[a-zA-Z0-9\-_%]+", re.IGNORECASE),
        "twitter": re.compile(r"(twitter\.com|x\.com)/[a-zA-Z0-9\-_%]+", re.IGNORECASE),
        "youtube": re.compile(r"youtube\.com/(c|channel|user|@[a-zA-Z0-9\-_%]+)", re.IGNORECASE),
        "github": re.compile(r"github\.com/[a-zA-Z0-9\-_%]+", re.IGNORECASE),
    }

    # Block patterns indicating sharing utility widgets rather than profiles
    SHARE_KEYWORDS = [
        "share",
        "sharer",
        "intent/tweet",
        "pin/create",
        "widgets",
        "javascript",
        "post-share",
        "group"
    ]

    @classmethod
    def is_share_link(cls, url: str) -> bool:
        """
        Returns True if the URL contains sharing widget patterns.
        """
        url_lower = url.lower()
        return any(kw in url_lower for kw in cls.SHARE_KEYWORDS)

    @classmethod
    def extract(cls, all_links: List[Dict[str, str]]) -> Dict[str, str]:
        """
        Scans a list of link dictionaries to find the first valid profile URL for each platform.
        """
        results: Dict[str, str] = {
            "linkedin": "",
            "facebook": "",
            "instagram": "",
            "twitter": "",
            "youtube": "",
            "github": ""
        }

        for link in all_links:
            url = link.get("url", "").strip()
            if not url or cls.is_share_link(url):
                continue

            for platform, regex in cls.SOCIAL_PATTERNS.items():
                # If we haven't found a link for this platform yet
                if not results[platform]:
                    if regex.search(url):
                        # Clean up trailing slashes and keep the absolute URL
                        results[platform] = url

        return results
