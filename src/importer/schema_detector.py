"""
src/importer/schema_detector.py
================================
Dynamic Excel Schema Detection.

Maps raw sheet column headers to target database schema properties using heuristics.
Does not hardcode exact headers. Reports duplicates or failures.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SchemaDetector:
    """
    Scans list of headers to match system-required and optional columns.
    
    Target system keys:
        - npi
        - first_name
        - last_name
        - middle_name
        - company_name
        - website
        - email
        - phone
        - address_line_1
        - address_line_2
        - city
        - state
        - country
        - postal_code
    """

    # Column mapping regex patterns with support for spaces, underscores, and dashes
    PATTERNS = {
        "npi": r"^(npi|npi[\s_-]*number|national[\s_-]*provider[\s_-]*identifier)$",
        "first_name": r"^(first[\s_-]*name|firstname|given[\s_-]*name)$",
        "last_name": r"^(last[\s_-]*name|lastname|family[\s_-]*name|surname)$",
        "middle_name": r"^(middle[\s_-]*name|middlename)$",
        "company_name": r"^(company|company[\s_-]*name|firm|firm[\s_-]*name|organization|organisation|entity|investor[\s_-]*name)$",
        "website": r"^(website|web|url|domain|source[\s_-]*website|site|link)$",
        "email": r"^(email|email[\s_-]*address|mail|contact[\s_-]*email)$",
        "phone": r"^(phone|phone[\s_-]*number|tel|telephone|mobile|contact[\s_-]*phone)$",
        "address_line_1": r"^(address[\s_-]*line[\s_-]*1|address1|street[\s_-]*address|street|address)$",
        "address_line_2": r"^(address[\s_-]*line[\s_-]*2|address2|suite|office|apt|apartment)$",
        "city": r"^(city|town)$",
        "state": r"^(state|province|region|license[\s_-]*state)$",
        "country": r"^(country|nation)$",
        "postal_code": r"^(postal[\s_-]*code|postal|zip|zip[\s_-]*code|pincode|postcode)$",
    }

    def __init__(self, headers: List[str]) -> None:
        self.headers = [str(h).strip() for h in headers]
        self._validate_headers()

    def _validate_headers(self) -> None:
        """Check for duplicate column names in Excel header list (normalized)."""
        seen = set()
        duplicates = []
        for h in self.headers:
            # Normalize header: lowercase and strip non-alphanumeric characters
            h_norm = re.sub(r'[^a-zA-Z0-9]', '', h).lower()
            if h_norm in seen:
                duplicates.append(h)
            seen.add(h_norm)
        if duplicates:
            raise ValueError(f"Duplicate column headers detected: {duplicates}")

    def detect_mapping(self) -> Dict[str, str]:
        """
        Scan headers and return a map of target_system_key -> raw_excel_header.
        
        A raw header is mapped to the first system key pattern it matches.
        """
        mapping: Dict[str, str] = {}
        
        # Track mapped headers to avoid double mapping
        mapped_headers = set()

        for key, pattern in self.PATTERNS.items():
            regex = re.compile(pattern, re.IGNORECASE)
            for header in self.headers:
                if header in mapped_headers:
                    continue
                if regex.match(header):
                    # For state, prioritize actual "State" over "License state" if both exist
                    if key == "state" and "license" in header.lower() and "state" in mapping:
                        continue
                    mapping[key] = header
                    mapped_headers.add(header)

        # Fallback mappings for state: if "State" is missing but "License state" is available
        if "state" not in mapping:
            for header in self.headers:
                if "state" in header.lower() and header not in mapped_headers:
                    mapping["state"] = header
                    mapped_headers.add(header)
                    break

        logger.info(f"[SchemaDetector] Successfully mapped {len(mapping)} columns: {mapping}")
        return mapping

    def generate_report(self) -> Dict[str, Any]:
        """
        Return metadata report about the schema mapping results.
        """
        mapping = self.detect_mapping()
        unmapped = [h for h in self.headers if h not in mapping.values()]
        return {
            "total_columns": len(self.headers),
            "mapped_count": len(mapping),
            "unmapped_count": len(unmapped),
            "mapping": mapping,
            "unmapped_columns": unmapped,
        }
