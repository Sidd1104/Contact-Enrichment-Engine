"""
src/importer/row_mapper.py
===========================
Data Row Mapper.

Normalizes raw row data into standardized dictionaries based on schema detector mappings.
"""

from __future__ import annotations

from typing import Any, Dict


class RowMapper:
    """
    Standardizes raw row data from Excel sheets into system dictionaries.
    """

    def __init__(self, mapping: Dict[str, str]) -> None:
        """
        Args:
            mapping: Mapping of target_system_key -> raw_excel_header.
        """
        self.mapping = mapping

    def map_row(self, raw_row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map raw row dict to target system schema keys.
        
        Args:
            raw_row: Dictionary representing a single row from the Excel sheet.
            
        Returns:
            Standardized dict containing mapped keys, plus a 'raw_data' entry holding
            the original values.
        """
        standardized: Dict[str, Any] = {}

        # Default standard fields to empty string
        standard_keys = [
            "npi", "first_name", "last_name", "middle_name", "company_name",
            "website", "email", "phone", "address_line_1", "address_line_2",
            "city", "state", "country", "postal_code"
        ]
        for key in standard_keys:
            standardized[key] = ""

        # Map according to detected headers
        for sys_key, raw_header in self.mapping.items():
            if raw_header in raw_row:
                val = raw_row[raw_header]
                # Strip strings or handle float/int/nan values
                if val is None or (isinstance(val, float) and val != val):  # check NaN
                    standardized[sys_key] = ""
                else:
                    standardized[sys_key] = str(val).strip()

        # Attach original raw row data for preservation and reference
        standardized["raw_data"] = raw_row

        return standardized
