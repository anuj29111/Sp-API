#!/usr/bin/env python3
"""
SP-API Daily Sales & Traffic Pull Script

This script pulls daily sales and traffic data from Amazon SP-API
and stores it in Supabase.

Usage:
    python pull_daily_sales.py                    # Pull yesterday's data for all NA marketplaces
    python pull_daily_sales.py --date 2026-02-01  # Pull specific date
    python pull_daily_sales.py --marketplace USA  # Pull specific marketplace only
    python pull_daily_sales.py --days-ago 2       # Pull data from 2 days ago

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
from datetime import date, datetime, timedelta
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

# North America marketplaces (using same refresh token)
NA_MARKETPLACES = ["USA", "CA", "MX"]

# All marketplaces by region
MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES", "UAE"],
    "FE": ["AU", "JP"]
}


def pull_marketplace_data(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    skip_existing: bool = True
) -> dict:
    """
    Pull data for a single marketplace and date.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: Date to pull data for
        region: API region ('NA', 'EU', 'FE')
        skip_existing: Skip if data already exists

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
        # Check if already pulled
        if skip_existing:
            existing = get_existing_pull(marketplace_code, report_date)
            if existing and existing.get("status") == "completed":
                print(f"⏭️  {marketplace_code} {report_date} already pulled, skipping")
                result["status"] = "skipped"
                return result

        print(f"\n{'='*50}")
        print(f"📊 Pulling {marketplace_code} data for {report_date}")
        print(f"{'='*50}")

        # Create tracking records
        import_id = create_data_import(marketplace_code, report_date)
        pull_id = create_pull_record(marketplace_code, report_date, import_id=import_id)

        # Get access token
        print("🔑 Getting access token...")
        access_token = get_access_token()

        # Update pull status to processing
        update_pull_status(pull_id, "processing")

        # Pull the report
        print("📥 Requesting report from Amazon...")
        report_data = pull_single_day_report(
            access_token=access_token,
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region
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

        print(f"✅ {marketplace_code} completed: {asin_count} ASINs in {processing_time_ms}ms")

    except Exception as e:
        error_msg = str(e)
        result["status"] = "failed"
        result["error"] = error_msg

        print(f"❌ {marketplace_code} failed: {error_msg}")

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
    report_date: date,
    skip_existing: bool = True
) -> List[dict]:
    """
    Pull data for all marketplaces in a region.

    Args:
        region: API region ('NA', 'EU', 'FE')
        report_date: Date to pull data for
        skip_existing: Skip if data already exists

    Returns:
        List of results for each marketplace
    """
    marketplaces = MARKETPLACES_BY_REGION.get(region.upper(), [])
    results = []

    for marketplace_code in marketplaces:
        # Rate limit: wait between marketplace pulls
        if results:
            print("\n⏳ Waiting 60 seconds before next marketplace (rate limit)...")
            time.sleep(60)

        result = pull_marketplace_data(
            marketplace_code=marketplace_code,
            report_date=report_date,
            region=region,
            skip_existing=skip_existing
        )
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Pull daily sales & traffic data from Amazon SP-API"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date to pull (YYYY-MM-DD format). Defaults to 2 days ago."
    )
    parser.add_argument(
        "--days-ago",
        type=int,
        default=2,
        help="Number of days ago to pull. Default: 2 (Amazon data delay)"
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

    args = parser.parse_args()

    # Determine date
    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = date.today() - timedelta(days=args.days_ago)

    print(f"\n🚀 SP-API Daily Pull Script")
    print(f"📅 Date: {report_date}")
    print(f"🌎 Region: {args.region}")

    # Pull data
    if args.marketplace:
        # Single marketplace
        results = [pull_marketplace_data(
            marketplace_code=args.marketplace.upper(),
            report_date=report_date,
            region=args.region,
            skip_existing=not args.force
        )]
    else:
        # All marketplaces in region
        results = pull_region_data(
            region=args.region,
            report_date=report_date,
            skip_existing=not args.force
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
