#!/usr/bin/env python3
"""
SP-API Daily Sales & Traffic Pull Script

This script pulls daily sales and traffic data from Amazon SP-API
and stores it in Supabase.

Features:
- Automatic retry with exponential backoff on API failures
- Rate limit handling via SPAPIClient
- Checkpoint-based resume capability via PullTracker
- Slack alerts on failures (if SLACK_WEBHOOK_URL is set)

Usage:
    python pull_daily_sales.py                    # Pull today's data for all NA marketplaces (timezone-aware)
    python pull_daily_sales.py --date 2026-02-01  # Pull specific date
    python pull_daily_sales.py --marketplace USA  # Pull specific marketplace only
    python pull_daily_sales.py --days-ago 1       # Pull data from 1 day ago
    python pull_daily_sales.py --resume           # Resume incomplete pull

Environment Variables Required:
    SP_LWA_CLIENT_ID      - Login With Amazon Client ID
    SP_LWA_CLIENT_SECRET  - Login With Amazon Client Secret
    SP_REFRESH_TOKEN_NA   - North America refresh token
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key

Optional Environment Variables:
    SLACK_WEBHOOK_URL     - Slack webhook for failure alerts
    SP_API_MAX_RETRIES    - Max retry attempts (default: 5)
"""

import os
import sys
import argparse
import time
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Optional

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

# Import new resilience modules
from scripts.utils.api_client import SPAPIClient, SPAPIError
from scripts.utils.pull_tracker import PullTracker
from scripts.utils.alerting import alert_failure, alert_partial, send_summary

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# North America marketplaces (using same refresh token)
NA_MARKETPLACES = ["USA", "CA", "MX"]

# All marketplaces by region
MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES", "UAE"],
    "FE": ["AU", "JP"]
}

# Marketplace timezones for calculating "today" in each marketplace
# Amazon uses PST for NA, GMT for EU, JST for FE
MARKETPLACE_TIMEZONES = {
    "USA": "America/Los_Angeles",   # PST/PDT
    "CA": "America/Los_Angeles",    # Amazon uses PST for NA
    "MX": "America/Los_Angeles",    # Amazon uses PST for NA
    "UK": "Europe/London",          # GMT/BST
    "DE": "Europe/Berlin",          # CET
    "FR": "Europe/Paris",           # CET
    "IT": "Europe/Rome",            # CET
    "ES": "Europe/Madrid",          # CET
    "UAE": "Asia/Dubai",            # GST (no DST)
    "AU": "Australia/Sydney",       # AEST
    "JP": "Asia/Tokyo",             # JST
}


def get_marketplace_date(marketplace_code: str, days_ago: int = 0) -> date:
    """
    Get the current date in a marketplace's timezone.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA', 'UK')
        days_ago: Days to subtract from current date (default: 0 = today)

    Returns:
        date object representing today (or days_ago) in that marketplace
    """
    tz_name = MARKETPLACE_TIMEZONES.get(marketplace_code.upper(), "UTC")
    tz = ZoneInfo(tz_name)
    now_in_tz = datetime.now(tz)
    target_date = (now_in_tz - timedelta(days=days_ago)).date()
    return target_date


def pull_marketplace_data(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    skip_existing: bool = True,
    client: SPAPIClient = None,
    tracker: PullTracker = None
) -> dict:
    """
    Pull data for a single marketplace and date.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: Date to pull data for
        region: API region ('NA', 'EU', 'FE')
        skip_existing: Skip if data already exists
        client: SPAPIClient instance (handles retry and rate limiting)
        tracker: PullTracker instance (handles checkpoint/resume)

    Returns:
        Dict with status and counts
    """
    result = {
        "marketplace": marketplace_code,
        "date": report_date.isoformat(),
        "status": "pending",
        "asin_count": 0,
        "error": None,
        "retryable": False
    }

    start_time = time.time()

    # Mark marketplace as in progress in tracker
    if tracker:
        tracker.start_marketplace(marketplace_code)

    try:
        # Check if already pulled (only skip if we have actual data)
        if skip_existing:
            existing = get_existing_pull(marketplace_code, report_date)
            if existing and existing.get("status") == "completed":
                asin_count = existing.get("asin_count", 0)
                if asin_count > 0:
                    print(f"⏭️  {marketplace_code} {report_date} already pulled ({asin_count} ASINs), skipping")
                    result["status"] = "skipped"
                    result["asin_count"] = asin_count
                    if tracker:
                        tracker.complete_marketplace(marketplace_code, asin_count)
                    return result
                else:
                    print(f"🔄 {marketplace_code} {report_date} has 0 ASINs, re-pulling...")

        print(f"\n{'='*50}")
        print(f"📊 Pulling {marketplace_code} data for {report_date}")
        print(f"{'='*50}")

        # Create tracking records
        import_id = create_data_import(marketplace_code, report_date)
        pull_id = create_pull_record(marketplace_code, report_date, import_id=import_id)

        # Get access token (if no client provided)
        if client is None:
            print("🔑 Getting access token...")
            access_token = get_access_token()
        else:
            access_token = None  # Client already has token

        # Update pull status to processing
        update_pull_status(pull_id, "processing")

        # Pull the report (client handles retry and rate limiting)
        print("📥 Requesting report from Amazon...")
        report_data = pull_single_day_report(
            access_token=access_token,
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region,
            client=client
        )

        # Store ASIN data
        print("💾 Storing ASIN data...")
        asin_count = upsert_asin_data(report_data, marketplace_code, report_date, import_id)

        # Store totals
        print("💾 Storing daily totals...")
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

        # Mark complete in tracker
        if tracker:
            tracker.complete_marketplace(marketplace_code, asin_count)

        print(f"✅ {marketplace_code} completed: {asin_count} ASINs in {processing_time_ms}ms")

    except SPAPIError as e:
        # SP-API specific error (may be retryable)
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg
        result["retryable"] = True  # SP-API errors are generally retryable

        logger.error(f"{marketplace_code} failed with SP-API error: {error_msg}")
        print(f"❌ {marketplace_code} failed: {error_msg}")

        # Send alert
        retry_count = client.stats.get("retries", 0) if client else 0
        alert_failure("sales_traffic", marketplace_code, error_msg, retry_count)

        # Update tracker
        if tracker:
            tracker.fail_marketplace(marketplace_code, error_msg)

        # Try to update tracking records
        try:
            if 'pull_id' in locals():
                update_pull_status(pull_id, "failed", error_message=error_msg)
            if 'import_id' in locals():
                update_data_import(import_id, "failed", error_message=error_msg)
        except:
            pass

    except Exception as e:
        # General error
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg

        logger.error(f"{marketplace_code} failed: {error_msg}")
        print(f"❌ {marketplace_code} failed: {error_msg}")

        # Send alert
        alert_failure("sales_traffic", marketplace_code, error_msg, 0)

        # Update tracker
        if tracker:
            tracker.fail_marketplace(marketplace_code, error_msg)

        # Try to update tracking records
        try:
            if 'pull_id' in locals():
                update_pull_status(pull_id, "failed", error_message=error_msg)
            if 'import_id' in locals():
                update_data_import(import_id, "failed", error_message=error_msg)
        except:
            pass

    return result


def pull_region_data(
    region: str,
    report_date: date = None,
    skip_existing: bool = True,
    resume: bool = True,
    days_ago: int = None
) -> List[dict]:
    """
    Pull data for all marketplaces in a region.

    Args:
        region: API region ('NA', 'EU', 'FE')
        report_date: Date to pull data for (if None, uses per-marketplace dates)
        skip_existing: Skip if data already exists
        resume: Resume from checkpoint if previous pull was incomplete
        days_ago: Days ago to pull (used when report_date is None)

    Returns:
        List of results for each marketplace
    """
    pull_start_time = time.time()

    # Get access token once for all marketplaces
    print("🔑 Getting access token...")
    access_token = get_access_token()

    # Create SPAPIClient with retry and rate limiting
    client = SPAPIClient(access_token, region=region)

    # Create PullTracker for checkpoint/resume capability
    # Use a placeholder date for tracker if using per-marketplace dates
    tracker_date = report_date or date.today()
    tracker = PullTracker("sales_traffic", tracker_date, region)
    tracker.start_pull(resume=resume)

    # Get marketplaces to process (supports resume)
    all_marketplaces = MARKETPLACES_BY_REGION.get(region.upper(), [])
    if resume:
        marketplaces = tracker.get_incomplete_marketplaces(all_marketplaces)
        if len(marketplaces) < len(all_marketplaces):
            completed = len(all_marketplaces) - len(marketplaces)
            print(f"📋 Resuming: {completed} marketplaces already done, {len(marketplaces)} remaining")
    else:
        marketplaces = all_marketplaces

    results = []

    for marketplace_code in marketplaces:
        # Determine date for this marketplace
        if report_date is not None:
            mp_date = report_date
        else:
            mp_date = get_marketplace_date(marketplace_code, days_ago or 0)
            print(f"   📅 {marketplace_code}: {mp_date}")

        # SPAPIClient handles rate limiting automatically - no need for fixed sleep
        # The client will wait based on x-amzn-RateLimit-* headers

        result = pull_marketplace_data(
            marketplace_code=marketplace_code,
            report_date=mp_date,
            region=region,
            skip_existing=skip_existing,
            client=client,
            tracker=tracker
        )
        results.append(result)

    # Finish tracking and determine final status
    final_status = tracker.finish_pull()

    # Log client stats
    stats = client.get_stats()
    logger.info(f"API stats: {stats['requests']} requests, {stats['retries']} retries, {stats['rate_limit_waits']} rate limit waits")

    # Send summary/alerts
    total_rows = sum(r["asin_count"] for r in results)
    duration = time.time() - pull_start_time

    completed = [r["marketplace"] for r in results if r["status"] == "completed"]
    failed = [r["marketplace"] for r in results if r["status"] == "failed"]

    if failed:
        errors = {r["marketplace"]: r.get("error", "Unknown") for r in results if r["status"] == "failed"}
        alert_partial("sales_traffic", report_date.isoformat(), completed, failed, errors)
    else:
        send_summary("sales_traffic", report_date.isoformat(), results, total_rows, duration)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Pull daily sales & traffic data from Amazon SP-API"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date to pull (YYYY-MM-DD format). If not specified, uses yesterday in each marketplace's timezone."
    )
    parser.add_argument(
        "--days-ago",
        type=int,
        default=1,
        help="Number of days ago to pull. Default: 1 (yesterday - Sales & Traffic report has ~12-24hr delay)"
    )
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Specific marketplace code (e.g., USA, UK). Omit for all NA marketplaces."
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
        default=True,
        help="Resume from checkpoint if previous pull was incomplete (default: True)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume, start fresh"
    )

    args = parser.parse_args()

    # Handle resume flag
    resume = args.resume and not args.no_resume

    # Determine if using fixed date or per-marketplace dates
    use_fixed_date = args.date is not None
    fixed_date = date.fromisoformat(args.date) if args.date else None
    days_ago = args.days_ago

    print(f"\n🚀 SP-API Daily Pull Script (with retry & rate limiting)")
    if use_fixed_date:
        print(f"📅 Date: {fixed_date} (fixed)")
    else:
        print(f"📅 Date: Today in each marketplace's timezone (days_ago={days_ago})")
    print(f"🌎 Region: {args.region}")
    print(f"🔄 Resume: {resume}")

    # Pull data
    if args.marketplace:
        # Single marketplace - create client and tracker inline
        mp_code = args.marketplace.upper()
        report_date = fixed_date if use_fixed_date else get_marketplace_date(mp_code, days_ago)
        print(f"📍 {mp_code}: pulling date {report_date}")

        print("🔑 Getting access token...")
        access_token = get_access_token()
        client = SPAPIClient(access_token, region=args.region)

        results = [pull_marketplace_data(
            marketplace_code=mp_code,
            report_date=report_date,
            region=args.region,
            skip_existing=not args.force,
            client=client
        )]
    else:
        # All marketplaces in region - each gets its own date
        marketplaces = MARKETPLACES_BY_REGION.get(args.region.upper(), NA_MARKETPLACES)

        # Show what dates will be pulled
        print("\n📍 Marketplace dates:")
        for mp in marketplaces:
            mp_date = fixed_date if use_fixed_date else get_marketplace_date(mp, days_ago)
            print(f"   {mp}: {mp_date}")

        # Pull data with per-marketplace dates
        results = pull_region_data(
            region=args.region,
            report_date=fixed_date,  # Pass None to use per-marketplace dates
            skip_existing=not args.force,
            resume=resume,
            days_ago=days_ago if not use_fixed_date else None
        )

    # Summary
    print(f"\n{'='*50}")
    print("📊 SUMMARY")
    print(f"{'='*50}")

    completed = sum(1 for r in results if r["status"] == "completed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    total_asins = sum(r["asin_count"] for r in results)

    for r in results:
        status_emoji = {"completed": "✅", "skipped": "⏭️", "failed": "❌"}.get(r["status"], "❓")
        print(f"  {status_emoji} {r['marketplace']}: {r['status']} ({r['asin_count']} ASINs)")
        if r.get("error"):
            print(f"     Error: {r['error'][:100]}")

    print(f"\nTotal: {completed} completed, {skipped} skipped, {failed} failed")
    print(f"Total ASINs: {total_asins}")

    # Exit with error code if any failed
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
