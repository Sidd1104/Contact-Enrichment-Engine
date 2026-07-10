"""
src/extractor/phone_extractor.py
================================
Extracts and normalizes phone numbers from text and tel links.
"""

from __future__ import annotations

import logging
from typing import Dict, List
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberMatcher

logger = logging.getLogger(__name__)


class PhoneExtractor:
    """
    Finds and normalizes phone numbers to E.164 format using phonenumbers library.
    """

    @classmethod
    def extract(
        cls,
        text: str,
        tel_links: List[str] | None = None,
        default_region: str = "US"
    ) -> Dict[str, float]:
        """
        Parses text and tel links to extract unique phone numbers.
        Returns a dictionary mapping E.164 formatted numbers to confidence scores.
        """
        results: Dict[str, float] = {}

        # 1. Process tel links (highest confidence)
        if tel_links:
            for raw_tel in tel_links:
                cleaned_tel = raw_tel.strip()
                if not cleaned_tel:
                    continue
                # Strip tel: prefix if present
                if cleaned_tel.lower().startswith("tel:"):
                    cleaned_tel = cleaned_tel[4:]
                try:
                    parsed = phonenumbers.parse(cleaned_tel, default_region)
                    if phonenumbers.is_possible_number(parsed):
                        formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                        results[formatted] = 1.0
                except Exception as e:
                    logger.debug(f"Failed to parse tel link {cleaned_tel}: {e}")

        # 2. Match phone numbers in text using PhoneNumberMatcher
        try:
            # PhoneNumberMatcher automatically scans text for telephone numbers
            matcher = PhoneNumberMatcher(text, default_region)
            for match in matcher:
                try:
                    parsed = match.number
                    if phonenumbers.is_possible_number(parsed):
                        formatted = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                        if formatted not in results:
                            results[formatted] = 0.85
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error executing PhoneNumberMatcher: {e}")

        return results
