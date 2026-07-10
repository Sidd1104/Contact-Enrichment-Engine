"""
src/search/search_validator.py
===============================
Search Result Validation and Sanitization.

Validates that resolved URLs have a correct scheme, are syntactically valid,
and standardizes them.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SearchValidator:
    """
    Sanitizes and checks validity of discovered URL links.
    """

    @staticmethod
    def sanitize_url(url: str) -> str:
        """Strip whitespaces, lowercase scheme/host, and remove tracking params."""
        if not url:
            return ""
        url = url.strip()
        
        # Ensure scheme is present
        if not url.startswith(("http://", "https://")):
            # Default to https
            url = "https://" + url

        try:
            parsed = urlparse(url)
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()
            path = parsed.path
            
            # Reconstruct clean url without query params/hash
            clean_url = f"{scheme}://{netloc}{path}"
            # Strip trailing slash if path is empty or has trailing slash
            if path == "/" or not path:
                clean_url = f"{scheme}://{netloc}"
            else:
                clean_url = clean_url.rstrip("/")
            return clean_url
        except Exception:
            return url

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Verify URL syntax."""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            # Must have scheme and domain
            if not parsed.scheme or not parsed.netloc:
                return False
            # Check domain length and basic dot presence
            if "." not in parsed.netloc or len(parsed.netloc) < 4:
                return False
            return True
        except Exception:
            return False
