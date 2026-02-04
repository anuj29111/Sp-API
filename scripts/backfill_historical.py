#!/usr/bin/env python3
"""
SP-API Historical Backfill Script

This script pulls historical sales & traffic data from Amazon SP-API
for up to 2 years back. It handles rate limiting and supports resume
from interruption.

Usage:
    # Full 2-year backfill for all NA marketplaces
    python backfill_historical.py

    # Custom date range
    python backfill_historical.py --start-date 2024-01-01 --end-date 2024-12-31

    # Single marketplace
    python backfill_historical.py --marketplace USA

    # Resume from last successful date
    python backfill_historical.py --resume

    # Dry run (show what would be pulled)
    python backfill_historical.py --dry-run

Environment Variables Required:
    SP_LWA_CLIENT_ID      - Login With Amazon Client ID
    SP_LWA_CLIENT_SECRET  - Login With Amazon Client Secret
    SP_REFRESH_TOKEN_NA   - North America refresh token
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key
"""

import os
import sys
import argparse
import time
import json
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Tuple
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token, get_refresh_token_for_region
from scripts.utils.reports import pull_single_day_report, MARKETPLACE_IDS
from scripts.utils.db import (
    create_data_import,
    update_data_import,
    create_pull_record,
    update_pull_status,
    upsert_asin_data,
    upsert_totals,
    get_existing_pull
)

# Configuration
MAX_HISTORY_DAYS = 730  # 2 years (Amazon SP-API limit)
RATE_LIMIT_SECONDS = 65  # Wait between report requests (Amazon limit ~1/min)
BATCH_SIZE = 30  # Days per batch before longer pause
BATCH_PAUSE_SECONDS = 120  # Pause between batches

# North America marketplaces
NA_MARKETPLACES = ["USA", "CA", "MX"]

# State file for resume capability
STATE_FILE = Path(__file__).parent / ".backfill_state.json"


def load_state() -> Dict:
    """Load backfill state from file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: Dict):
    """Save backfill state to file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def get_date_range(start_date: date, end_date: date) -> List[date]:
    """Generate list of dates from start to end (inclusive)."""
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def check_existing_data(marketplace_code: str, report_date: date) -> bool:
    """Check if data already exists for this marketplace and date."""
    existing = get_existing_pull(marketplace_code, report_date)
    return existing is not None and existing.get("status") == "completed"


def pull_single_day(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    access_token: Optional[str] = None
) -> dict:
    """
    Pull data for a single marketplace and date.

    Returns:
        Dict with status and counts
    """
    result = {
        "marketplace": marketplace_code,
        "date": report_date.isoformat(),
        "status": "pending",
        "asin_count": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # Get fresh access token if not provided
        if not access_token:
            access_token = get_access_token()

        # Create tracking records
        import_id = create_data_import(marketplace_code, report_date)
        pull_id = create_pull_record(marketplace_code, report_date, import_id=import_id)

        # Update pull status to processing
        update_pull_status(pull_id, "processing")

        # Pull the report
        report_data = pull_single_day_report(
            access_token=access_token,
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region
        )

        # Store ASIN data
        asin_count = upsert_asin_data(report_data, marketplace_code, report_date, import_id)

        # Store totals
        upsert_totals(report_data, marketplace_code, report_date, import_id)

        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Update tracking records
        update_pull_status(
            pull_id,
            "completed",
            asin_count=asin_count,
            processing_time_ms=processing_time_ms
        )
        update_data_import(
            import_id,
            "completed",
            row_count=asin_count,
            processing_time_ms=processing_time_ms
        )

        result["status"] = "completed"
        result["asin_count"] = asin_count

    except Exception as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg

        # Try to update tracking records
        try:
            if 'pull_id' in locals():
                update_pull_status(pull_id, "failed", error_message=error_msg)
            if 'import_id' in locals():
                update_data_import(import_id, "failed", error_message=error_msg)
        except:
            pass

    return result


def run_backfill(
    marketplaces: List[str],
    start_date: date,
    end_date: date,
    region: str = "NA",
    skip_existing: bool = True,
    dry_run: bool = False
) -> Dict:
    """
    Run historical backfill for specified marketplaces and date range.

    Args:
        marketplaces: List of marketplace codes to backfill
        start_date: First date to pull
        end_date: Last date to pull (should be at least 2 days ago)
        region: API region
        skip_existing: Skip dates that already have data
        dry_run: If True, just show what would be pulled

    Returns:
        Summary statistics
    """
    dates = get_date_range(start_date, end_date)
    total_requests = len(dates) * len(marketplaces)

    print("\n" + "=" * 60)
    print("📊 SP-API Historical Backfill")
    print("=" * 60)
    print(f"📅 Date range: {start_date} to {end_date} ({len(dates)} days)")
    print(f"🌎 Marketplaces: {', '.join(marketplaces)}")
    print(f"📦 Total potential requests: {total_requests}")

    # Estimate time
    estimated_minutes = total_requests * RATE_LIMIT_SECONDS / 60
    estimated_hours = estimated_minutes / 60
    print(f"⏱️  Estimated time: {estimated_hours:.1f} hours ({estimated_minutes:.0f} minutes)")

    if dry_run:
        print("\n🏃 DRY RUN - No data will be pulled")
        # Show what would be pulled (skip DB check in dry run if not available)
        to_pull = []
        skipped_count = 0

        try:
            # Try to check existing data if DB is available
            for d in dates:
                for mp in marketplaces:
                    if skip_existing and check_existing_data(mp, d):
                        skipped_count += 1
                        continue
                    to_pull.append((d, mp))
        except Exception as e:
            # DB not available - show all as "would pull"
            print(f"⚠️  Cannot check existing data (no DB connection): {str(e)[:50]}")
            print(f"📝 Without skipping, would pull {total_requests} date/marketplace combinations")
            print(f"\n📋 First 10 dates would be:")
            for i, d in enumerate(dates[:10]):
                for mp in marketplaces:
                    print(f"   - {mp} {d}")
            print(f"   ... and {total_requests - 30} more")
            return {"dry_run": True, "would_pull": total_requests, "note": "DB not available, showing all"}

        print(f"📝 Would pull {len(to_pull)} date/marketplace combinations")
        if skipped_count > 0:
            print(f"⏭️  Would skip {skipped_count} (already exist)")
        if len(to_pull) <= 20:
            for d, mp in to_pull:
                print(f"   - {mp} {d}")
        else:
            for d, mp in to_pull[:10]:
                print(f"   - {mp} {d}")
            print(f"   ... and {len(to_pull) - 10} more")

        return {"dry_run": True, "would_pull": len(to_pull)}

    # Initialize state
    state = load_state()
    state["start_time"] = datetime.now().isoformat()
    state["start_date"] = start_date.isoformat()
    state["end_date"] = end_date.isoformat()
    state["marketplaces"] = marketplaces

    # Statistics
    stats = {
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "total_asins": 0,
        "errors": []
    }

    # Get initial access token
    print("\n🔑 Getting access token...")
    access_token = get_access_token()
    token_time = time.time()

    # Process in batches
    request_count = 0
    batch_count = 0

    for day_idx, report_date in enumerate(dates):
        for mp_idx, marketplace_code in enumerate(marketplaces):
            request_count += 1

            # Progress
            progress = request_count / total_requests * 100
            print(f"\n[{progress:.1f}%] Processing {marketplace_code} {report_date} ({request_count}/{total_requests})")

            # Skip if already exists
            if skip_existing and check_existing_data(marketplace_code, report_date):
                print(f"⏭️  Already exists, skipping")
                stats["skipped"] += 1
                continue

            # Refresh token every 30 minutes
            if time.time() - token_time > 1800:
                print("🔑 Refreshing access token...")
                access_token = get_access_token()
                token_time = time.time()

            # Pull data
            result = pull_single_day(
                marketplace_code=marketplace_code,
                report_date=report_date,
                region=region,
                access_token=access_token
            )

            # Update stats
            if result["status"] == "completed":
                stats["completed"] += 1
                stats["total_asins"] += result["asin_count"]
                print(f"✅ Completed: {result['asin_count']} ASINs")
            else:
                stats["failed"] += 1
                stats["errors"].append({
                    "marketplace": marketplace_code,
                    "date": report_date.isoformat(),
                    "error": result["error"]
                })
                print(f"❌ Failed: {result['error'][:100]}")

            # Save state for resume
            state["last_completed"] = {
                "marketplace": marketplace_code,
                "date": report_date.isoformat()
            }
            state["stats"] = stats
            save_state(state)

            # Rate limiting
            batch_count += 1
            if batch_count >= BATCH_SIZE:
                print(f"\n⏸️  Batch complete. Pausing {BATCH_PAUSE_SECONDS}s...")
                time.sleep(BATCH_PAUSE_SECONDS)
                batch_count = 0
            else:
                # Standard rate limit
                print(f"⏳ Waiting {RATE_LIMIT_SECONDS}s (rate limit)...")
                time.sleep(RATE_LIMIT_SECONDS)

    # Final summary
    print("\n" + "=" * 60)
    print("📊 BACKFILL COMPLETE")
    print("=" * 60)
    print(f"✅ Completed: {stats['completed']}")
    print(f"⏭️  Skipped: {stats['skipped']}")
    print(f"❌ Failed: {stats['failed']}")
    print(f"📦 Total ASINs: {stats['total_asins']}")

    if stats["errors"]:
        print(f"\n⚠️  Errors encountered:")
        for err in stats["errors"][:10]:
            print(f"   - {err['marketplace']} {err['date']}: {err['error'][:50]}")
        if len(stats["errors"]) > 10:
            print(f"   ... and {len(stats['errors']) - 10} more errors")

    # Clean up state file on successful completion
    if stats["failed"] == 0:
        STATE_FILE.unlink(missing_ok=True)

    return stats


def get_resume_info() -> Tuple[Optional[date], Optional[str]]:
    """Get resume information from state file."""
    state = load_state()
    if not state or "last_completed" not in state:
        return None, None

    last = state["last_completed"]
    return date.fromisoformat(last["date"]), last["marketplace"]


def main():
    parser = argparse.ArgumentParser(
        description="Pull historical sales & traffic data from Amazon SP-API"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD). Default: 2 years ago"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD). Default: 2 days ago"
    )
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Single marketplace code (e.g., USA). Default: all NA marketplaces"
    )
    parser.add_argument(
        "--region",
        type=str,
        default="NA",
        choices=["NA", "EU", "FE"],
        help="Region to pull. Default: NA"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-pull even if data exists"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last successful pull"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be pulled without actually pulling"
    )

    args = parser.parse_args()

    # Determine date range
    if args.end_date:
        end_date = date.fromisoformat(args.end_date)
    else:
        end_date = date.today() - timedelta(days=2)  # Amazon data delay

    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        # Default: 2 years back (max allowed)
        start_date = end_date - timedelta(days=MAX_HISTORY_DAYS)

    # Handle resume
    if args.resume:
        resume_date, resume_mp = get_resume_info()
        if resume_date:
            print(f"📂 Resuming from {resume_mp} {resume_date}")
            start_date = resume_date
        else:
            print("⚠️  No resume state found, starting from beginning")

    # Validate dates
    if start_date > end_date:
        print(f"❌ Error: Start date {start_date} is after end date {end_date}")
        sys.exit(1)

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = NA_MARKETPLACES

    # Run backfill
    stats = run_backfill(
        marketplaces=marketplaces,
        start_date=start_date,
        end_date=end_date,
        region=args.region,
        skip_existing=not args.force,
        dry_run=args.dry_run
    )

    # Exit with error code if any failed
    if stats.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
