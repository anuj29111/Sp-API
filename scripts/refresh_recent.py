#!/usr/bin/env python3
"""
SP-API Recent Data Refresh Script

This script refreshes the last N days of data to capture Amazon's late attribution.
Amazon can update sales/traffic data for up to 14 days as attribution settles.

Usage:
    python refresh_recent.py                    # Refresh last 14 days (default)
    python refresh_recent.py --days 7           # Refresh last 7 days
    python refresh_recent.py --marketplace USA  # Single marketplace

Recommended: Run daily to keep data accurate.
"""

import os
import sys
import argparse
import time
from datetime import date, timedelta
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token
from scripts.utils.reports import pull_single_day_report, MARKETPLACE_IDS
from scripts.utils.db import (
    create_data_import,
    update_data_import,
    create_pull_record,
    update_pull_status,
    upsert_asin_data,
    upsert_totals
)

# Configuration
DEFAULT_REFRESH_DAYS = 14  # How many days back to refresh
RATE_LIMIT_SECONDS = 65    # Wait between report requests

# North America marketplaces
NA_MARKETPLACES = ["USA", "CA", "MX"]

MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES"],
    "FE": ["AU"],
    "UAE": ["UAE"]
}


def refresh_single_day(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    access_token: str = None
) -> dict:
    """
    Refresh data for a single marketplace and date (force overwrite).
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
            access_token = get_access_token(region=region)

        # Create tracking records
        import_id = create_data_import(marketplace_code, report_date)
        pull_id = create_pull_record(marketplace_code, report_date, import_id=import_id)

        # Update pull status
        update_pull_status(pull_id, "processing")

        # Pull the report
        report_data = pull_single_day_report(
            access_token=access_token,
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region
        )

        # Store ASIN data (upsert will overwrite existing)
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

        try:
            if 'pull_id' in locals():
                update_pull_status(pull_id, "failed", error_message=error_msg)
            if 'import_id' in locals():
                update_data_import(import_id, "failed", error_message=error_msg)
        except:
            pass

    return result


def refresh_recent_data(
    marketplaces: List[str],
    days: int = DEFAULT_REFRESH_DAYS,
    region: str = "NA"
) -> dict:
    """
    Refresh the last N days of data for all specified marketplaces.

    Args:
        marketplaces: List of marketplace codes
        days: Number of days back to refresh
        region: API region

    Returns:
        Summary statistics
    """
    # Calculate date range (2 days ago to 2+days days ago)
    end_date = date.today() - timedelta(days=2)  # Amazon data delay
    start_date = end_date - timedelta(days=days - 1)

    print("\n" + "=" * 60)
    print("🔄 SP-API Recent Data Refresh")
    print("=" * 60)
    print(f"📅 Refreshing: {start_date} to {end_date} ({days} days)")
    print(f"🌎 Marketplaces: {', '.join(marketplaces)}")
    print(f"📦 Total requests: {days * len(marketplaces)}")

    # Get access token
    print("\n🔑 Getting access token...")
    access_token = get_access_token(region=region)
    token_time = time.time()

    # Statistics
    stats = {
        "completed": 0,
        "failed": 0,
        "total_asins": 0,
        "errors": []
    }

    request_count = 0
    total_requests = days * len(marketplaces)

    # Process each date (newest first - most likely to have changes)
    current_date = end_date
    while current_date >= start_date:
        for marketplace_code in marketplaces:
            request_count += 1
            progress = request_count / total_requests * 100

            print(f"\n[{progress:.1f}%] Refreshing {marketplace_code} {current_date}")

            # Refresh token every 30 minutes
            if time.time() - token_time > 1800:
                print("🔑 Refreshing access token...")
                access_token = get_access_token(region=region)
                token_time = time.time()

            # Pull data (force overwrite)
            result = refresh_single_day(
                marketplace_code=marketplace_code,
                report_date=current_date,
                region=region,
                access_token=access_token
            )

            if result["status"] == "completed":
                stats["completed"] += 1
                stats["total_asins"] += result["asin_count"]
                print(f"✅ Refreshed: {result['asin_count']} ASINs")
            else:
                stats["failed"] += 1
                stats["errors"].append({
                    "marketplace": marketplace_code,
                    "date": current_date.isoformat(),
                    "error": result["error"]
                })
                print(f"❌ Failed: {result['error'][:100]}")

            # Rate limiting (except for last request)
            if request_count < total_requests:
                print(f"⏳ Waiting {RATE_LIMIT_SECONDS}s...")
                time.sleep(RATE_LIMIT_SECONDS)

        current_date -= timedelta(days=1)

    # Summary
    print("\n" + "=" * 60)
    print("📊 REFRESH COMPLETE")
    print("=" * 60)
    print(f"✅ Completed: {stats['completed']}")
    print(f"❌ Failed: {stats['failed']}")
    print(f"📦 Total ASINs: {stats['total_asins']}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Refresh recent SP-API data to capture late attribution"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_REFRESH_DAYS,
        help=f"Number of days to refresh. Default: {DEFAULT_REFRESH_DAYS}"
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
        choices=["NA", "EU", "FE", "UAE"],
        help="Region to refresh. Default: NA"
    )

    args = parser.parse_args()

    region = args.region.upper()

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(region, NA_MARKETPLACES)

    # Run refresh
    stats = refresh_recent_data(
        marketplaces=marketplaces,
        days=args.days,
        region=region
    )

    # Exit with error code only if majority of requests failed
    # Individual failures are expected (rate limits, transient errors)
    if stats["failed"] > 0 and stats["failed"] > stats.get("completed", 0):
        print(f"\n❌ Majority of requests failed ({stats['failed']} failed vs {stats.get('completed', 0)} completed)")
        sys.exit(1)
    elif stats["failed"] > 0:
        print(f"\n⚠️  {stats['failed']} requests failed but {stats.get('completed', 0)} completed — treating as success")


if __name__ == "__main__":
    main()
