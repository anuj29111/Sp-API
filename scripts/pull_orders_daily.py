#!/usr/bin/env python3
"""
SP-API Near-Real-Time Orders Pull Script

Pulls same-day order data from Amazon SP-API using the
GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL report.

This provides near-real-time sales data (~30 min delay) to complement
the Sales & Traffic report (24-72hr delay). Orders data populates
units_ordered and ordered_product_sales columns in sp_daily_asin_data
with data_source='orders'. When the S&T report arrives later, it
overwrites with attribution-corrected values + traffic metrics.

Usage:
    python pull_orders_daily.py                       # Pull today + yesterday for all NA
    python pull_orders_daily.py --date 2026-02-07     # Pull specific date
    python pull_orders_daily.py --marketplace USA     # Single marketplace
    python pull_orders_daily.py --today-only           # Skip yesterday catch-up
    python pull_orders_daily.py --dry-run              # Show what would be pulled
    python pull_orders_daily.py --force                # Overwrite even if S&T data exists

Environment Variables Required:
    SP_LWA_CLIENT_ID      - Login With Amazon Client ID
    SP_LWA_CLIENT_SECRET  - Login With Amazon Client Secret
    SP_REFRESH_TOKEN_NA   - North America refresh token
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key

Optional Environment Variables:
    SLACK_WEBHOOK_URL     - Slack webhook for failure alerts
"""

import os
import sys
import argparse
import time
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.auth import get_access_token
from scripts.utils.orders_reports import pull_orders_report
from scripts.utils.db import upsert_orders_asin_data, MARKETPLACE_UUIDS
from scripts.utils.api_client import SPAPIClient, SPAPIError
from scripts.utils.alerting import alert_failure, send_summary

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# North America marketplaces
NA_MARKETPLACES = ["USA", "CA", "MX"]

MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES", "UAE"],
    "FE": ["AU", "JP"]
}

# Marketplace timezones (same as pull_daily_sales.py)
MARKETPLACE_TIMEZONES = {
    "USA": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "MX": "America/Los_Angeles",
    "UK": "Europe/London",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "UAE": "Asia/Dubai",
    "AU": "Australia/Sydney",
    "JP": "Asia/Tokyo",
}


def get_marketplace_date(marketplace_code: str, days_ago: int = 0) -> date:
    """Get the current date in a marketplace's timezone."""
    tz_name = MARKETPLACE_TIMEZONES.get(marketplace_code.upper(), "UTC")
    tz = ZoneInfo(tz_name)
    now_in_tz = datetime.now(tz)
    target_date = (now_in_tz - timedelta(days=days_ago)).date()
    return target_date


def pull_orders_for_marketplace(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    client: SPAPIClient = None,
    dry_run: bool = False
) -> dict:
    """
    Pull and upsert orders data for a single marketplace and date.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: Date to pull orders for
        region: API region
        client: SPAPIClient instance
        dry_run: If True, pull and aggregate but don't upsert

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
        print(f"\n{'='*50}")
        print(f"📦 Pulling orders for {marketplace_code} on {report_date}")
        print(f"{'='*50}")

        # Pull orders report (create → poll → download → aggregate)
        aggregated = pull_orders_report(
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region,
            client=client
        )

        if not aggregated:
            print(f"⚠️  No orders data for {marketplace_code} on {report_date}")
            result["status"] = "completed"
            result["asin_count"] = 0
            return result

        # Upsert to database (skips ASINs with existing S&T data)
        if dry_run:
            print(f"🏃 DRY RUN - would upsert {len(aggregated)} ASINs")
            result["asin_count"] = len(aggregated)
        else:
            upserted = upsert_orders_asin_data(
                rows=aggregated,
                marketplace_code=marketplace_code,
                report_date=report_date
            )
            result["asin_count"] = upserted
            print(f"💾 Upserted {upserted} ASINs (of {len(aggregated)} aggregated)")

        elapsed_ms = int((time.time() - start_time) * 1000)
        result["status"] = "completed"
        print(f"✅ {marketplace_code} orders completed in {elapsed_ms}ms")

    except SPAPIError as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg
        logger.error(f"{marketplace_code} orders failed: {error_msg}")
        print(f"❌ {marketplace_code} orders failed: {error_msg}")
        alert_failure("orders", marketplace_code, error_msg, 0)

    except Exception as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg
        logger.error(f"{marketplace_code} orders failed: {error_msg}")
        print(f"❌ {marketplace_code} orders failed: {error_msg}")
        alert_failure("orders", marketplace_code, error_msg, 0)

    return result


def pull_orders_region(
    region: str = "NA",
    report_date: date = None,
    today_only: bool = False,
    marketplace_filter: str = None,
    dry_run: bool = False
) -> List[dict]:
    """
    Pull orders for all marketplaces in a region.

    Default behavior: pulls TODAY + YESTERDAY for each marketplace
    (today = near-real-time, yesterday = catch up any missed data)

    Args:
        region: API region
        report_date: Specific date to pull (overrides today/yesterday logic)
        today_only: Only pull today (skip yesterday catch-up)
        marketplace_filter: Single marketplace to process
        dry_run: Show what would be pulled without upserting

    Returns:
        List of result dicts
    """
    pull_start_time = time.time()

    # Get access token
    print("🔑 Getting access token...")
    access_token = get_access_token()

    # Create SPAPIClient
    client = SPAPIClient(access_token, region=region)

    # Determine marketplaces
    if marketplace_filter:
        marketplaces = [marketplace_filter.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(region.upper(), [])

    results = []

    for marketplace_code in marketplaces:
        if report_date:
            # Specific date provided
            dates_to_pull = [report_date]
        else:
            # Default: today + yesterday in marketplace timezone
            today = get_marketplace_date(marketplace_code, days_ago=0)
            yesterday = get_marketplace_date(marketplace_code, days_ago=1)

            if today_only:
                dates_to_pull = [today]
                print(f"   📅 {marketplace_code}: today only → {today}")
            else:
                dates_to_pull = [today, yesterday]
                print(f"   📅 {marketplace_code}: today={today}, yesterday={yesterday}")

        for pull_date in dates_to_pull:
            result = pull_orders_for_marketplace(
                marketplace_code=marketplace_code,
                report_date=pull_date,
                region=region,
                client=client,
                dry_run=dry_run
            )
            results.append(result)

    # Summary
    duration = time.time() - pull_start_time
    total_asins = sum(r["asin_count"] for r in results)
    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] == "failed"]

    print("\n" + "=" * 60)
    print("📊 ORDERS PULL SUMMARY")
    print("=" * 60)
    print(f"✅ Completed: {len(completed)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"📦 Total ASINs: {total_asins}")
    print(f"⏱️  Duration: {duration:.1f}s")

    if failed:
        for r in failed:
            print(f"   ❌ {r['marketplace']} {r['date']}: {r.get('error', 'Unknown')[:80]}")

    # Log client stats
    stats = client.get_stats()
    logger.info(
        f"API stats: {stats['requests']} requests, "
        f"{stats['retries']} retries, "
        f"{stats['rate_limit_waits']} rate limit waits"
    )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Pull near-real-time orders data from Amazon SP-API"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Specific date to pull (YYYY-MM-DD). Default: today + yesterday per marketplace timezone."
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
        "--today-only",
        action="store_true",
        help="Only pull today's data (skip yesterday catch-up)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-pull even if data exists (note: S&T data still won't be overwritten)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pull and aggregate but don't upsert to database"
    )

    args = parser.parse_args()

    # Parse date if provided
    report_date = None
    if args.date:
        report_date = date.fromisoformat(args.date)

    print("\n" + "=" * 60)
    print("📦 NEAR-REAL-TIME ORDERS PULL")
    print("=" * 60)
    print(f"📅 Date: {report_date or 'today + yesterday (per marketplace TZ)'}")
    print(f"🌎 Region: {args.region}")
    print(f"🏪 Marketplace: {args.marketplace or 'All ' + args.region}")
    if args.dry_run:
        print("🏃 DRY RUN MODE")
    print()

    # Run the pull
    results = pull_orders_region(
        region=args.region,
        report_date=report_date,
        today_only=args.today_only,
        marketplace_filter=args.marketplace,
        dry_run=args.dry_run
    )

    # Exit with error if all failed
    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] == "failed"]

    if not completed and failed:
        print("\n❌ All pulls failed")
        sys.exit(1)
    elif failed:
        print(f"\n⚠️  {len(failed)} pulls failed, {len(completed)} completed")
        # Exit success — partial failures are OK, will be caught on next run


if __name__ == "__main__":
    main()
