#!/usr/bin/env python3
"""
Contact Enrichment Engine - Command Line Entrypoint.
Phase 2H - Production Pipeline Orchestrator Integration.
"""

from __future__ import annotations

import os
import sys
import argparse
from src.pipeline.pipeline_manager import PipelineManager


def setup_parser() -> argparse.ArgumentParser:
    """Configure command line arguments."""
    parser = argparse.ArgumentParser(
        description="Contact Enrichment Engine CLI - Manage import, scraping, extraction, and export tasks.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. Run Subcommand
    run_parser = subparsers.add_parser("run", help="Start the contact enrichment pipeline")
    run_parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to the Excel file to import"
    )
    run_parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit processing to a specific number of records"
    )
    run_parser.add_argument(
        "--profile", "-p",
        type=str,
        default="production",
        help="Pipeline profile (development, testing, production, high_throughput)"
    )
    run_parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Disable the live terminal dashboard updates"
    )

    # 2. Benchmark Subcommand
    benchmark_parser = subparsers.add_parser("benchmark", help="Run performance benchmarks across worker and batch sizes")
    benchmark_parser.add_argument(
        "--file", "-f",
        type=str,
        required=True,
        help="Excel file path used as target source for benchmark runs"
    )

    # 3. Profile Subcommand
    profile_parser = subparsers.add_parser("profile", help="Run pipeline with a specific configuration profile")
    profile_parser.add_argument(
        "profile_name",
        type=str,
        help="Name of execution profile (development, testing, production, high_throughput)"
    )
    profile_parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Excel file path used as target source for profile run"
    )

    # 4. Health Subcommand
    subparsers.add_parser("health", help="Execute pre-flight checks and diagnose resource health status")

    # 5. Status Subcommand
    subparsers.add_parser("status", help="Show current enrichment database stats")

    return parser


def main() -> None:
    parser = setup_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        PipelineManager.run_pipeline(
            profile=args.profile,
            file_path=args.file,
            export_dir="data/export",
            limit=args.limit,
            show_dashboard=not args.no_dashboard
        )

    elif args.command == "benchmark":
        PipelineManager.run_benchmark(file_path=args.file)

    elif args.command == "profile":
        PipelineManager.run_pipeline(
            profile=args.profile_name,
            file_path=args.file,
            export_dir="data/export",
            limit=None,
            show_dashboard=True
        )

    elif args.command == "health":
        PipelineManager.check_health()

    elif args.command == "status":
        PipelineManager.show_status()


if __name__ == "__main__":
    main()
