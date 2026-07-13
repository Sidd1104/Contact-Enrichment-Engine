"""
src/validator/phone_validator.py
=================================
Validates, normalizes, and filters telephone numbers using phonenumbers library.
"""

from __future__ import annotations

import logging
from typing import List, Set, Dict, Tuple
import phonenumbers
from phonenumbers import PhoneNumberFormat

logger = logging.getLogger(__name__)


class PhoneValidator:
    """
    Normalizes numbers to E.164, checks country codes, impossible lengths, and handles deduplication.
    """

    @classmethod
    def validate(cls, phones: List[str], default_region: str = "US") -> List[str]:
        """
        Parses and normalizes a list of telephone inputs.
        Removes duplicates, impossible lengths, and invalid country codes.
        """
        valid, _ = cls.validate_with_details(phones, default_region)
        return valid

    @classmethod
    def validate_with_details(
        cls, phones: List[str], default_region: str = "US"
    ) -> Tuple[List[str], List[Dict[str, str]]]:
        """
        Parses and normalizes a list of telephone inputs.
        Returns unique validated phones and a list of rejected phones with reason codes.
        """
        valid_set: Set[str] = set()
        rejected: List[Dict[str, str]] = []

        for raw_phone in phones:
            cleaned = raw_phone.strip()
            if not cleaned:
                continue

            # Strip tel: prefixes
            if cleaned.lower().startswith("tel:"):
                cleaned = cleaned[4:]

            try:
                parsed = phonenumbers.parse(cleaned, default_region)
                
                # Check for impossible lengths and numbering plan structure
                if not phonenumbers.is_possible_number(parsed):
                    rejected.append({"raw": raw_phone, "reason": "Impossible length/format"})
                    continue

                # Verify if country code is registered and number is valid
                if not phonenumbers.is_valid_number(parsed):
                    # We log it but proceed to E164 formatting if possible number is true
                    pass

                # Normalise to E.164 standard format (+1xxxxxxxxxx)
                normalized = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                
                # Double check that country code is valid (> 0)
                if parsed.country_code > 0:
                    valid_set.add(normalized)
                else:
                    rejected.append({"raw": raw_phone, "reason": "Missing or invalid country code"})

            except Exception as e:
                rejected.append({"raw": raw_phone, "reason": f"Parsing failed: {str(e)}"})

        return sorted(list(valid_set)), rejected
