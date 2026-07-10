"""
src/validator/email_validator.py
=================================
Validates email addresses checking syntax, duplicates, TLDs, and disposable domains.
"""

from __future__ import annotations

import re
from typing import List, Set


class EmailValidator:
    """
    Cleans, filters, and validates email list syntax and domain trustworthiness.
    """

    # Comprehensive syntax checking matching standard characters
    SYNTAX_REGEX = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63}$"
    )

    # Common disposable email provider domains to reject
    DISPOSABLE_DOMAINS: Set[str] = {
        "mailinator.com", "yopmail.com", "trashmail.com", "10minutemail.com",
        "tempmail.com", "guerrillamail.com", "getairmail.com", "sharklasers.com",
        "dispostable.com", "yopmail.fr", "yopmail.net", "dropmail.me", "maildrop.cc"
    }

    @classmethod
    def is_valid_syntax(cls, email: str) -> bool:
        """Checks if the email string matches syntax regex."""
        return bool(cls.SYNTAX_REGEX.match(email))

    @classmethod
    def is_disposable(cls, email: str) -> bool:
        """Checks if the domain is listed as disposable or is a subdomain of one."""
        try:
            domain = email.split("@")[1].lower().strip()
            return domain in cls.DISPOSABLE_DOMAINS or any(
                domain.endswith("." + d) for d in cls.DISPOSABLE_DOMAINS
            )
        except IndexError:
            return True

    @classmethod
    def is_valid_tld(cls, email: str) -> bool:
        """Checks if TLD portion is only letters and has a length of 2 to 63 characters."""
        try:
            domain = email.split("@")[1]
            parts = domain.split(".")
            tld = parts[-1]
            # Must be only alphabetic characters and length between 2 and 63
            return tld.isalpha() and 2 <= len(tld) <= 63
        except Exception:
            return False

    @classmethod
    def validate(cls, emails: List[str]) -> List[str]:
        """
        Filters and validates a list of emails.
        Removes duplicates, malformed, disposable, and invalid TLD items.
        """
        valid_set: Set[str] = set()

        for raw_email in emails:
            email = raw_email.strip().lower()
            if not email:
                continue

            # Verify syntax, check for malformed formats
            if not cls.is_valid_syntax(email):
                continue

            # Verify TLD correctness
            if not cls.is_valid_tld(email):
                continue

            # Block disposable email providers
            if cls.is_disposable(email):
                continue

            valid_set.add(email)

        # Return unique validated emails maintaining stable order if possible
        return sorted(list(valid_set))
