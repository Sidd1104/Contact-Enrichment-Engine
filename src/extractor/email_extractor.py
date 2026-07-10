"""
src/extractor/email_extractor.py
================================
Extracts email addresses from text and mailto links, handling obfuscation.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set


class EmailExtractor:
    """
    Identifies and deobfuscates email addresses from plain text and HTML anchors.
    """

    # Regex for standard email format
    STANDARD_EMAIL_REGEX = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE
    )

    # Obfuscation replacement tables
    AT_PATTERNS = [
        r"\s*[\[\(]?\s*at\s*[\]\)]?\s*",
        r"\s*@\s*"
    ]
    
    DOT_PATTERNS = [
        r"\s*[\[\(]?\s*dot\s*[\]\)]?\s*",
        r"\s*\.\s*"
    ]

    # Regex for matching obfuscated email structures
    # Matches: prefix [at] domain [dot] com, prefix(at)domain(dot)com, etc.
    OBFUSCATED_REGEX = re.compile(
        r"[a-zA-Z0-9._%+-]+\s*(?:\[at\]|\(at\)|\s+at\s+)\s*[a-zA-Z0-9.-]+\s*(?:\[dot\]|\(dot\)|\s+dot\s+|\.)\s*[a-zA-Z]{2,6}",
        re.IGNORECASE
    )

    @classmethod
    def deobfuscate(cls, text: str) -> str:
        """
        Deobfuscates text containing representations of [at] and [dot].
        """
        cleaned = text.lower().strip()
        # Replace at symbols
        cleaned = re.sub(r"\[at\]|\(at\)", "@", cleaned)
        cleaned = re.sub(r"\s+at\s+", "@", cleaned)
        # Replace dot symbols
        cleaned = re.sub(r"\[dot\]|\(dot\)", ".", cleaned)
        cleaned = re.sub(r"\s+dot\s+", ".", cleaned)
        # Remove any spacing around dots and ats
        cleaned = re.sub(r"\s*@\s*", "@", cleaned)
        cleaned = re.sub(r"\s*\.\s*", ".", cleaned)
        return cleaned

    @classmethod
    def extract(cls, text: str, mailto_links: List[str] | None = None) -> Dict[str, float]:
        """
        Scans text and mailto links to extract unique emails.
        Returns a dictionary mapping emails to confidence scores (0.0 to 1.0).
        """
        results: Dict[str, float] = {}

        # 1. Process mailto links (highest confidence)
        if mailto_links:
            for email in mailto_links:
                email_clean = email.strip().lower()
                if cls.STANDARD_EMAIL_REGEX.match(email_clean):
                    results[email_clean] = 1.0

        # 2. Extract standard emails from text
        for match in cls.STANDARD_EMAIL_REGEX.finditer(text):
            email = match.group(0).strip().lower()
            # If already added via mailto, keep the 1.0 confidence
            if email not in results:
                results[email] = 0.9

        # 3. Extract obfuscated emails from text
        for match in cls.OBFUSCATED_REGEX.finditer(text):
            raw_match = match.group(0)
            deobfuscated = cls.deobfuscate(raw_match)
            if cls.STANDARD_EMAIL_REGEX.match(deobfuscated):
                if deobfuscated not in results:
                    results[deobfuscated] = 0.7  # Slightly lower confidence due to obfuscation de-parsing

        # Filter out common false positives (like template placeholders)
        placeholders = {"email@domain.com", "yourname@domain.com", "info@yourdomain.com", "example@example.com"}
        for ph in placeholders:
            if ph in results:
                del results[ph]

        return results
