"""
src/importer/filters.py
========================
Data Filters and Validation rules.

Handles filtering out:
  - Empty rows.
  - Fully enriched rows (those already containing both valid phone and email).
  - Duplicate rows (based on primary key NPI).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


def is_empty_value(val: Any) -> bool:
    """Check if value is null, NaN, empty string, or standard placeholder."""
    if val is None:
        return True
    if isinstance(val, float) and val != val:  # NaN check
        return True
    
    val_str = str(val).strip().lower()
    return val_str in ("", "nan", "null", "none", "n/a", "-", "undefined")


class ImportFilter:
    """
    Handles filtering logic for Excel row imports.
    """

    def __init__(self) -> None:
        self.seen_npis: Set[str] = set()

    def is_row_empty(self, row: Dict[str, Any], mapped_cols: Dict[str, str]) -> bool:
        """
        Check if the row is entirely empty across all mapped columns.
        """
        # If all mapped columns are empty/placeholders, the row is considered empty
        for raw_header in mapped_cols.values():
            if raw_header in row and not is_empty_value(row[raw_header]):
                return False
        return True

    def is_fully_enriched(self, mapped_row: Dict[str, Any]) -> bool:
        """
        Smart Filtering: Returns True if the row already contains BOTH phone and email.
        Fully enriched rows skip queue placement because they require no enrichment.
        """
        email = mapped_row.get("email", "")
        phone = mapped_row.get("phone", "")

        email_exists = not is_empty_value(email)
        phone_exists = not is_empty_value(phone)

        return email_exists and phone_exists

    def is_duplicate(self, mapped_row: Dict[str, Any]) -> bool:
        """
        Check for duplicate record based on primary key NPI.
        """
        npi = mapped_row.get("npi", "").strip()
        if not npi:
            return False  # Let validator flag empty primary key, don't filter as duplicate yet
        
        if npi in self.seen_npis:
            return True
        
        self.seen_npis.add(npi)
        return False

    def clear(self) -> None:
        """Clear seen tracking sets."""
        self.seen_npis.clear()
