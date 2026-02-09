#!/usr/bin/env python3
"""
SP-API SQP/SCP Historical Backfill Script

Backfills historical search performance data from ~Dec 2023 to present.

Constraints:
- ~110 weeks of weekly data available
- NA: ~44 batches per period (32 USA + 11 CA) x 2 report types = ~88 requests per period
- EU: ~20-40 batches per period (UK, DE, FR, IT, ES, UAE) x 2 report types
- FE: ~2-6 batches per period (AU only) x 2 report types
- At 1 request/min = ~88 minutes per period
- Rate limit budget: ~186 available/day after daily pulls
- Default: 2 periods per GitHub Actions run (~3 hours)

Strategy:
- Process latest periods first (most valuable)
- Skip existing completed pulls
- Resume interrupted backfills at batch level

Usage:
    python backfill_sqp.py                              # Backfill latest-first, 2 periods/run
    python backfill_sqp.py --max-periods 3              # More periods per run
    python backfill_sqp.py --start-date 2024-01-01      # From specific date
    python backfill_sqp.py --report-type SQP            # SQP only
    python backfill_sqp.py --period-type MONTH           # Monthly backfill
    python backfill_sqp.py --marketplace USA             # Single marketplace
    python backfill_sqp.py --dry-run                    # Show plan
"""

import os
import sys
import argparse
import time
import logging
from datetime import date, datetime, timedelta
from typing import List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token
from scripts.utils.api_client import SPAPIClient, SPAPIError
from scripts.utils.alerting import alert_failure, send_summary
from scripts.utils.db import (
    get_existing_sqp_pull,
)
from scripts.utils.sqp_reports import (
    enumerate_weekly_periods,
    enumerate_monthly_periods,
    get_latest_available_week,
    get_latest_available_month,
)
from scripts.pull_sqp import pull_for_marketplace

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default backfill start: Dec 2023 (SQP data generally available from here)
DEFAULT_BACKFILL_START = date(2023, 12, 3)  # First Sunday in Dec 2023

# Marketplaces by region for Brand Analytics (SQP/SCP)
# MX excluded (Brand Analytics not available)
MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA"],
    "EU": ["UK", "DE", "FR", "IT", "ES", "UAE"],
    "FE": ["AU"]
}

# Token refresh interval (30 minutes)
TOKEN_REFRESH_INTERVAL = 30 * 60


def check_backfill_progress(
    period_type: str,
    marketplaces: List[str],
    report_types: List[str],
    periods: List[Tuple[date, date]]
) -> Tuple[int, int]:
    """
    Check how many periods are already completed.

    Returns:
        Tuple of (completed_count, total_count)
    """
    total = len(periods) * len(marketplaces) * len(report_types)
    completed = 0

    for period_start, period_end in periods:
        for mp in marketplaces:
            for rt in report_types:
                existing = get_existing_sqp_pull(mp, rt, period_start, period_end, period_type)
                if existing and existing["status"] == "completed":
                    completed += 1

    return completed, total


def main():
    parser = argparse.ArgumentParser(
        description="Backfill historical SQP/SCP data from Amazon SP-API"
    )
    parser.add_argument(
        "--max-periods",
        type=int,
        default=2,
        help="Max periods to process per run (default: 2)"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Backfill start date (YYYY-MM-DD). Default: Dec 2023"
    )
    parser.add_argument(
        "--report-type",
        type=str,
        choices=["SQP", "SCP", "both"],
        default="both",
        help="Report type to backfill (default: both)"
    )
    parser.add_argument(
        "--period-type",
        type=str,
        choices=["WEEK", "MONTH"],
        default="WEEK",
        help="Period granularity (default: WEEK)"
    )
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Specific marketplace code (e.g., USA, UK, AU). Omit for all in region."
    )
    parser.add_argument(
        "--region",
        type=str,
        default="NA",
        choices=["NA", "EU", "FE"],
        help="Region (default: NA)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")

    args = parser.parse_args()

    # Determine parameters
    start_date = date.fromisoformat(args.start_date) if args.start_date else DEFAULT_BACKFILL_START

    if args.period_type == "WEEK":
        latest_start, latest_end = get_latest_available_week()
    else:
        latest_start, latest_end = get_latest_available_month()

    if args.report_type == "both":
        report_types = ["SQP", "SCP"]
    else:
        report_types = [args.report_type]

    marketplaces = [args.marketplace.upper()] if args.marketplace else MARKETPLACES_BY_REGION.get(args.region.upper(), ["USA", "CA"])

    # Enumerate all periods
    if args.period_type == "WEEK":
        all_periods = enumerate_weekly_periods(start_date, latest_end)
    else:
        all_periods = enumerate_monthly_periods(start_date, latest_end)

    print(f"\nSP-API SQP/SCP Backfill Script")
    print(f"Period type: {args.period_type}")
    print(f"Date range: {start_date} to {latest_end}")
    print(f"Total periods available: {len(all_periods)}")
    print(f"Reports: {', '.join(report_types)}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Max periods per run: {args.max_periods}")
    print(f"{'='*60}")

    # Check progress
    print("Checking backfill progress...")
    completed, total = check_backfill_progress(args.period_type, marketplaces, report_types, all_periods)
    pct = (completed / total * 100) if total > 0 else 0
    print(f"Progress: {completed}/{total} ({pct:.1f}%) marketplace-report-period combinations completed")

    if pct > 99:
        print("Backfill is >99% complete. Exiting.")
        return

    # Find periods that need processing (newest first, already sorted that way)
    pending_periods = []
    for period_start, period_end in all_periods:
        needs_work = False
        for mp in marketplaces:
            for rt in report_types:
                existing = get_existing_sqp_pull(mp, rt, period_start, period_end, args.period_type)
                if not existing or existing["status"] != "completed":
                    needs_work = True
                    break
            if needs_work:
                break
        if needs_work:
            pending_periods.append((period_start, period_end))

    # Limit to max_periods
    periods_to_process = pending_periods[:args.max_periods]

    print(f"\nPending periods: {len(pending_periods)}")
    print(f"Processing this run: {len(periods_to_process)}")

    for p_start, p_end in periods_to_process:
        print(f"  {p_start} to {p_end}")

    if args.dry_run:
        print("\n[DRY RUN] Would process the above periods. Exiting.")
        return

    if not periods_to_process:
        print("No periods to process. Backfill is complete.")
        return

    # Get access token and create client
    print(f"\nGetting access token for region {args.region}...")
    access_token = get_access_token(region=args.region)
    client = SPAPIClient(access_token, region=args.region)
    last_token_refresh = time.time()

    all_results = []
    total_start_time = time.time()

    for period_idx, (period_start, period_end) in enumerate(periods_to_process):
        print(f"\n{'='*60}")
        print(f"Period {period_idx + 1}/{len(periods_to_process)}: {period_start} to {period_end}")
        print(f"{'='*60}")

        for marketplace_code in marketplaces:
            # Refresh token if needed
            elapsed = time.time() - last_token_refresh
            if elapsed > TOKEN_REFRESH_INTERVAL:
                print(f"Refreshing access token for region {args.region}...")
                access_token = get_access_token(region=args.region)
                client = SPAPIClient(access_token, region=args.region)
                last_token_refresh = time.time()

            for report_type in report_types:
                result = pull_for_marketplace(
                    client=client,
                    marketplace_code=marketplace_code,
                    report_type=report_type,
                    period_start=period_start,
                    period_end=period_end,
                    period_type=args.period_type,
                    region=args.region,
                    resume=True,
                    force=False,
                    dry_run=False
                )
                all_results.append(result)

    # Summary
    total_duration = time.time() - total_start_time
    print(f"\n{'='*60}")
    print("BACKFILL SUMMARY")
    print(f"{'='*60}")

    completed = sum(1 for r in all_results if r["status"] == "completed")
    skipped = sum(1 for r in all_results if r["status"] == "skipped")
    partial = sum(1 for r in all_results if r["status"] == "partial")
    failed = sum(1 for r in all_results if r["status"] == "failed")
    total_rows = sum(r["total_rows"] for r in all_results)

    print(f"Periods processed: {len(periods_to_process)}")
    print(f"Completed: {completed} | Skipped: {skipped} | Partial: {partial} | Failed: {failed}")
    print(f"Total rows: {total_rows}")
    print(f"Duration: {total_duration/60:.1f} minutes")

    # Updated progress
    print("\nUpdated backfill progress:")
    completed_now, total_now = check_backfill_progress(args.period_type, marketplaces, report_types, all_periods)
    pct_now = (completed_now / total_now * 100) if total_now > 0 else 0
    print(f"  {completed_now}/{total_now} ({pct_now:.1f}%)")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
