"""
src/pipeline/startup_validator.py
================================
Runs system pre-flight checks before executing the main pipeline.
Verifies Python version, environment keys, folders, database logins, and browser drivers.
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Tuple

from src.database.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class StartupValidator:
    """
    Validates execution pre-requisites to ensure high reliability.
    """

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self.conn_mgr = connection_manager

    def validate_all(self) -> Tuple[bool, List[str]]:
        """
        Executes all pre-flight diagnostic checks.
        
        Returns:
            Tuple of (success_boolean, list_of_log_messages).
        """
        logger.info("[StartupValidator] Initiating system pre-flight validation...")
        logs = []
        is_ok = True

        # 1. Verify Python Version
        py_version = sys.version_info
        if py_version < (3, 8):
            logs.append(f"[ERROR] Unsupported Python version: {sys.version}. Requires >= 3.8")
            is_ok = False
        else:
            logs.append(f"[OK] Python version: {sys.version_info.major}.{sys.version_info.minor}")

        # 2. Verify Required Folders
        required_dirs = ["data", "logs", "data/temp", "data/export"]
        for directory in required_dirs:
            p = Path(directory)
            try:
                p.mkdir(parents=True, exist_ok=True)
                # Attempt small write check
                test_file = p / ".write_test"
                test_file.write_text("ok")
                test_file.unlink()
                logs.append(f"[OK] Directory write permissions: {directory}/")
            except Exception as e:
                logs.append(f"[ERROR] Directory write failed: {directory}/ - {e}")
                is_ok = False

        # 3. Verify Environment Configurations
        env_vars = ["GEMINI_API_KEY", "TAVILY_API_KEY"]
        for var in env_vars:
            val = os.getenv(var)
            if not val:
                logs.append(f"[WARNING] API key environment variable missing: {var}")
            else:
                logs.append(f"[OK] API configuration present: {var}")

        # 4. Verify Database Connectivity
        try:
            session = self.conn_mgr.get_session()
            # Perform query test
            from sqlalchemy import text
            session.execute(text("SELECT 1"))
            session.close()
            logs.append("[OK] Database connection established successfully.")
        except Exception as e:
            logs.append(f"[ERROR] Database connection failed: {e}")
            is_ok = False

        # 5. Verify Playwright Availability
        try:
            from playwright.async_api import async_playwright
            logs.append("[OK] Playwright async library imported successfully.")
        except ImportError as e:
            logs.append(f"[ERROR] Playwright library not installed: {e}")
            is_ok = False

        # Log summary
        if is_ok:
            logger.info("[StartupValidator] Pre-flight checks passed successfully.")
        else:
            logger.error("[StartupValidator] Pre-flight check failed! Check logs below.")
            for log in logs:
                if "[ERROR]" in log:
                    logger.error(f"  {log}")

        return is_ok, logs
