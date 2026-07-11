"""
src/pipeline/dashboard.py
==========================
Renders a live terminal status dashboard representing pipeline throughput,
durations, success rates, resource parameters, and warnings.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class Dashboard:
    """
    Renders status telemetry to stdout.
    """

    def __init__(self, disabled: bool = False) -> None:
        self.disabled = disabled
        # Track whether we should clear screen
        self.is_windows = sys.platform == "win32"

    def clear_screen(self) -> None:
        """Clears the console screen."""
        if self.disabled:
            return
        if self.is_windows:
            os.system("cls")
        else:
            sys.stdout.write("\033[H\033[J")
            sys.stdout.flush()

    def render(self, stats: Dict[str, Any], health: Dict[str, Any]) -> None:
        """Renders the dashboard block to terminal stdout."""
        if self.disabled:
            return

        self.clear_screen()

        state = stats.get("state", "idle").upper()
        profile = stats.get("profile", {}).get("profile_name", "unknown").upper()
        elapsed = stats.get("elapsed_time_seconds", 0.0)
        
        current_batch = stats.get("current_batch_index", 0)
        total_batches = stats.get("total_batches", 0)
        total_records = stats.get("total_records", 0)
        processed = stats.get("processed_records", 0)
        
        success = stats.get("success_count", 0)
        failed = stats.get("failed_count", 0)
        retry = stats.get("retry_count", 0)
        dup = stats.get("duplicate_count", 0)

        emails = stats.get("emails_found", 0)
        phones = stats.get("phones_found", 0)
        ai_calls = stats.get("ai_calls", 0)
        ai_avoided = stats.get("ai_avoided", 0)
        browsers = stats.get("browser_launches", 0)
        active_workers = stats.get("active_workers", 0)

        cpu = health.get("cpu_usage_percent", 0.0)
        ram = health.get("ram_usage_percent", 0.0)
        db_status = "OK" if health.get("database_ok", True) else "ERROR"
        api_status = "OK" if health.get("api_availability", True) else "ERROR"

        # Derived metrics
        throughput = (processed / elapsed) if elapsed > 0 else 0.0
        success_rate = (success / processed) * 100 if processed > 0 else 0.0
        ai_total = ai_calls + ai_avoided
        ai_cache_ratio = (ai_avoided / ai_total) * 100 if ai_total > 0 else 0.0
        
        percent_complete = (processed / total_records) * 100 if total_records > 0 else 0.0
        
        # Calculate ETA
        remaining = total_records - processed
        eta_seconds = (remaining / throughput) if throughput > 0 else 0.0
        
        # Format duration/ETA as HH:MM:SS
        def format_time(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        elapsed_str = format_time(elapsed)
        eta_str = format_time(eta_seconds) if processed < total_records else "00:00:00"

        # Color codes
        green = "\033[92m"
        yellow = "\033[93m"
        red = "\033[91m"
        cyan = "\033[96m"
        reset = "\033[0m"
        bold = "\033[1m"

        state_color = green if state == "RUNNING" else (yellow if state in ("PAUSED", "STARTING") else (cyan if state == "COMPLETED" else red))
        db_color = green if db_status == "OK" else red
        api_color = green if api_status == "OK" else red

        output = f"""{bold}========================================================================{reset}
{bold}  CONTACT ENRICHMENT ENGINE - PIPELINE MONITOR{reset}
{bold}========================================================================{reset}
  State: {state_color}{bold}{state}{reset} | Profile: {bold}{profile}{reset} | Duration: {bold}{elapsed_str}{reset}
------------------------------------------------------------------------
  {bold}Ingestion Progress:{reset}
    Records:    [{processed}/{total_records}] ({percent_complete:.1f}%) | Batch: [{current_batch}/{total_batches}]
    Throughput: {bold}{throughput:.2f} rec/sec{reset} | ETA: {bold}{eta_str}{reset}
    Successes:  {green}{success}{reset} | Failures: {red}{failed}{reset} | Retry Queue: {yellow}{retry}{reset} | Dups: {cyan}{dup}{reset}
    Success Rate: {bold}{success_rate:.2f}%{reset}

  {bold}Intelligence Statistics:{reset}
    Emails Found:    {bold}{emails}{reset} | Phones Found: {bold}{phones}{reset}
    AI API Calls:    {yellow}{ai_calls}{reset} | AI Cache Hits: {green}{ai_avoided}{reset} ({ai_cache_ratio:.1f}%)
    Active Scrapers: {bold}{active_workers}{reset} workers | Browser Launches: {bold}{browsers}{reset}

  {bold}System Diagnostics & Health:{reset}
    CPU Usage:       {cpu:.1f}% | RAM Usage: {ram:.1f}%
    Database Health: {db_color}{db_status}{reset} | API Connections: {api_color}{api_status}{reset}
"""
        
        # Print recently processed rows log
        rows_log = stats.get("processed_rows_log", [])
        if rows_log:
            output += f"\n  {bold}Recently Processed Rows:{reset}\n"
            for log_item in rows_log:
                row_val = str(log_item.get("row", "?"))
                name_val = log_item.get("name", "Unknown")
                status_val = log_item.get("status", "SUCCESS")
                details_val = log_item.get("details", "")
                
                status_colored = f"{green}{status_val}{reset}" if status_val == "SUCCESS" else f"{red}{status_val}{reset}"
                output += f"    Row {row_val:4s} | {name_val[:25]:25s} | {status_colored} | {details_val}\n"
        
        # Print recent warnings or errors
        warnings = stats.get("warnings", [])
        errors = stats.get("errors", [])
        if warnings or errors:
            output += f"\n  {bold}{red}Alert logs:{reset}\n"
            for err in errors[-3:]:
                output += f"    {red}[ERROR] {err}{reset}\n"
            for warn in warnings[-3:]:
                output += f"    {yellow}[WARNING] {warn}{reset}\n"

        output += f"{bold}========================================================================{reset}\n"
        
        sys.stdout.write(output)
        sys.stdout.flush()
