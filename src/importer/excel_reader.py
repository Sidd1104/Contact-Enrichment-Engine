"""
src/importer/excel_reader.py
=============================
Production-ready Excel Reader.

Auto-detects Excel files in the input directory, selects the correct sheet
dynamically, and streams row dictionaries. Handles data validation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from ..config.importer_config import importer_config

logger = logging.getLogger(__name__)


class ExcelReader:
    """
    Scans directories for Excel files, automatically detects primary data sheets,
    and reads rows efficiently.
    """

    def __init__(self, input_dir: Optional[str] = None) -> None:
        self.input_dir = Path(input_dir or importer_config.input_directory)
        self.max_rows = importer_config.max_memory_rows

    def find_excel_files(self) -> List[Path]:
        """List all .xlsx and .xls files in the input directory."""
        if not self.input_dir.exists():
            logger.warning(f"Input directory does not exist: {self.input_dir}")
            return []
        
        files = []
        for ext in ("*.xlsx", "*.xls"):
            files.extend(self.input_dir.glob(ext))
        
        # Exclude temp files starting with ~$
        files = [f for f in files if not f.name.startswith("~$")]
        
        logger.info(f"[ExcelReader] Found Excel files in {self.input_dir}: {[f.name for f in files]}")
        return files

    def detect_primary_file(self) -> Path:
        """
        Auto-detect the primary dataset Excel file.
        
        If multiple exist, prioritizes files containing 'investor' or 'contact'
        in their name, otherwise picks the largest file.
        """
        files = self.find_excel_files()
        if not files:
            raise FileNotFoundError(f"No Excel files found in {self.input_dir}")

        if len(files) == 1:
            return files[0]

        # Prioritize based on keywords
        keywords = ("enriched", "investor", "contact", "customer", "lead")
        for file in files:
            name_lower = file.name.lower()
            if any(k in name_lower for k in keywords):
                logger.info(f"[ExcelReader] Auto-selected file by keyword: {file.name}")
                return file

        # Default fallback: pick largest file size
        files.sort(key=lambda f: f.stat().st_size, reverse=True)
        logger.info(f"[ExcelReader] Auto-selected largest file: {files[0].name}")
        return files[0]

    def detect_primary_sheet(self, file_path: Path) -> str:
        """
        Automatically select the primary worksheet.
        
        Ignores metadata or status sheets (e.g. sheets named 'status', 'summary',
        'metadata', 'readme'). Picks the worksheet with the largest data grid (rows * cols).
        """
        xls = pd.ExcelFile(file_path)
        sheet_names = xls.sheet_names

        if len(sheet_names) == 1:
            return sheet_names[0]

        sheet_stats: List[Tuple[str, int]] = []
        ignored_sheets = []

        for name in sheet_names:
            name_lower = name.lower()
            # Ignore standard status/metadata sheet names
            if any(k in name_lower for k in ("status", "summary", "metadata", "readme", "config")):
                ignored_sheets.append(name)
                continue

            try:
                # Load dimensions only (header-only or very fast sample)
                df = pd.read_excel(file_path, sheet_name=name, nrows=5)
                # Read total dimensions (if pandas ExcelFile parsing allows, or count via openpyxl)
                # To be fast, let's load sheet dimensions by reading sheet description
                # Or just load the full dimensions of the sheet.
                # Since we need accurate dimensions, we read it
                df_full = pd.read_excel(file_path, sheet_name=name)
                rows, cols = df_full.shape
                cells = rows * cols
                sheet_stats.append((name, cells))
            except Exception as e:
                logger.warning(f"Error checking sheet '{name}' dimensions: {e}")
                continue

        if not sheet_stats:
            # If all were ignored or failed, fallback to scanning all sheets and choosing largest
            for name in sheet_names:
                df_full = pd.read_excel(file_path, sheet_name=name)
                sheet_stats.append((name, df_full.shape[0] * df_full.shape[1]))

        # Sort by cells count descending
        sheet_stats.sort(key=lambda x: x[1], reverse=True)
        primary_sheet = sheet_stats[0][0]
        
        logger.info(
            f"[ExcelReader] Sheet analysis completed for {file_path.name}. "
            f"Ignored sheets: {ignored_sheets}. Selected primary sheet: '{primary_sheet}' "
            f"({sheet_stats[0][1]} cells)."
        )
        return primary_sheet

    def read_rows(self, file_path: Path, sheet_name: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Read all rows from the specified sheet and validate.
        
        Returns:
            Tuple of (headers, list of raw row dictionaries).
        """
        logger.info(f"[ExcelReader] Reading dataset from '{file_path.name}' [sheet: '{sheet_name}']")
        
        # Load the sheet
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        except Exception as e:
            raise ValueError(f"Failed to read sheet '{sheet_name}' from Excel file: {e}")

        total_rows = len(df)
        if total_rows > self.max_rows:
            raise ValueError(
                f"Dataset row count ({total_rows}) exceeds configured safety limit "
                f"MAX_MEMORY_ROWS ({self.max_rows})."
            )

        headers = [str(col).strip() for col in df.columns]
        
        # Convert df to list of dicts. Clean NaN values to None.
        raw_rows = df.to_dict(orient="records")
        cleaned_rows = []
        for idx, row in enumerate(raw_rows):
            cleaned_row = {}
            for k, v in row.items():
                k_clean = str(k).strip()
                # Clean up float NaN representation to None
                if v is None or (isinstance(v, float) and v != v):
                    cleaned_row[k_clean] = None
                else:
                    cleaned_row[k_clean] = v
            cleaned_row["_row_number"] = idx + 2
            cleaned_rows.append(cleaned_row)

        logger.info(
            f"[ExcelReader] Successfully loaded '{sheet_name}': "
            f"{len(headers)} columns, {len(cleaned_rows)} rows."
        )
        return headers, cleaned_rows
