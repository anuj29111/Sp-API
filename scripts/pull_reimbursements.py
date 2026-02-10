#!/usr/bin/env python3
"""
Pull Reimbursement Reports from SP-API

Uses standard CREATE → POLL → DOWNLOAD pattern.
Report type: GET_FBA_REIMBURSEMENTS_DATA

IMPORTANT: Amazon returns ALL reimbursements for the entire region regardless
of which marketplace_id you pass. So we pull ONCE per region and resolve each
row to the correct marketplace using the currency-unit field:
  NA:  USD→USA, CAD→CA, MXN→MX
  EU:  GBP→UK, EUR→DE (default — Amazon doesn't distinguish DE/FR/IT/ES)
  FE:  AUD→AU
  UAE: AED→UAE (separate seller account, own refresh token)

Usage:
    python pull_reimbursements.py                           # Last 60 days, all regions
    python pull_reimbursements.py --start-date 2024-01-01   # Backfill from date
    python pull_reimbursements.py --marketplace USA         # Single marketplace
    python pull_reimbursements.py --dry-run                 # Test without DB writes

Environment Variables Required:
    SP_LWA_CLIENT_ID      - Login With Amazon Client ID
    SP_LWA_CLIENT_SECRET  - Login With Amazon Client Secret
    SP_REFRESH_TOKEN_NA   - North America refresh token
    SP_REFRESH_TOKEN_EU   - Europe refresh token
    SP_REFRESH_TOKEN_FE   - Far East refresh token
    SP_REFRESH_TOKEN_UAE  - UAE refresh token (separate seller account)
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key
"""

import os
import sys
import argparse
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auth import get_access_token
from utils.financial_reports import (
    pull_reimbursement_report,
    FINANCIAL_REPORT_TYPES
)
from utils.inventory_reports import MARKETPLACE_IDS
from utils.db import (
    get_supabase_client,
    create_data_import,
    update_data_import,
    create_financial_pull_record,
    update_financial_pull_status,
    upsert_reimbursements,
    MARKETPLACE_UUIDS,
)

MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES"],
    "FE": ["AU"],
    "UAE": ["UAE"]
}

# The first marketplace in each region is used as the "anchor" to create
# the report request. Amazon returns data for the entire region regardless.
REGION_ANCHOR_MARKETPLACE = {
    "NA": "USA",
    "EU": "UK",
    "FE": "AU",
    "UAE": "UAE"
}

# Currency → marketplace code mapping for per-row resolution
# Amazon's reimbursement report returns currency-unit which tells us
# the actual marketplace the reimbursement belongs to
CURRENCY_TO_MARKETPLACE = {
    "USD": "USA",
    "CAD": "CA",
    "MXN": "MX",
    "GBP": "UK",
    "EUR": "DE",   # Default EUR to DE (can't distinguish DE/FR/IT/ES from report)
    "AED": "UAE",
    "AUD": "AU",
    "JPY": "JP",
}


def parse_decimal(value: str) -> float:
    """Parse string to decimal/float, handling empty strings and None."""
    if value is None or value == '' or value == 'N/A':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_int(value: str) -> int:
    """Parse string to int, handling empty strings and None."""
    if value is None or value == '' or value == 'N/A':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def resolve_marketplace_from_currency(currency: str, region: str) -> str:
    """
    Resolve the correct marketplace code from currency-unit field.

    For regions with a single currency (FE=AUD, UAE=AED), this is exact.
    For NA (USD/CAD/MXN), this is exact.
    For EU, GBP→UK is exact, EUR defaults to DE (can't distinguish DE/FR/IT/ES).

    Args:
        currency: The currency-unit value from the report row
        region: The region being pulled

    Returns:
        Marketplace code string (e.g., "USA", "UK")
    """
    if not currency:
        # Fallback: use region anchor
        return REGION_ANCHOR_MARKETPLACE.get(region, "USA")

    marketplace = CURRENCY_TO_MARKETPLACE.get(currency.strip().upper())
    if marketplace:
        return marketplace

    # Unknown currency — use region anchor
    return REGION_ANCHOR_MARKETPLACE.get(region, "USA")


def transform_reimbursement_rows(
    rows: List[Dict],
    region: str,
    import_id: str = None
) -> List[Dict]:
    """
    Transform raw TSV rows into database format with per-row marketplace resolution.

    Each row's marketplace is determined from its currency-unit field, NOT from
    the marketplace used to create the report request. This is because Amazon
    returns ALL reimbursements for the entire region in a single report.

    Args:
        rows: Raw report rows from download_report()
        region: Region code (NA, EU, FE, UAE) — used as fallback
        import_id: Data import tracking ID

    Returns:
        List of dicts ready for upsert
    """
    db_rows = []
    marketplace_counts = {}

    for row in rows:
        reimbursement_id = row.get("reimbursement-id", "").strip()
        if not reimbursement_id:
            continue

        # Resolve marketplace from currency
        currency = row.get("currency-unit", "").strip()
        marketplace_code = resolve_marketplace_from_currency(currency, region)
        marketplace_id = MARKETPLACE_UUIDS.get(marketplace_code)

        if not marketplace_id:
            print(f"  Warning: No UUID for marketplace '{marketplace_code}' (currency={currency}), skipping row")
            continue

        # Track counts per marketplace for logging
        marketplace_counts[marketplace_code] = marketplace_counts.get(marketplace_code, 0) + 1

        db_row = {
            "marketplace_id": marketplace_id,
            "approval_date": row.get("approval-date", "").strip() or None,
            "reimbursement_id": reimbursement_id,
            "case_id": row.get("case-id", "").strip() or None,
            "amazon_order_id": row.get("amazon-order-id", "").strip() or None,
            "reason": row.get("reason", "").strip() or None,
            "sku": row.get("sku", "").strip() or "",  # NOT NULL — part of unique key
            "fnsku": row.get("fnsku", "").strip() or None,
            "asin": row.get("asin", "").strip() or None,
            "product_name": row.get("product-name", "").strip() or None,
            "condition": row.get("condition", "").strip() or None,
            "currency_unit": currency or None,
            "amount_per_unit": parse_decimal(row.get("amount-per-unit", "")),
            "amount_total": parse_decimal(row.get("amount-total", "")),
            "quantity_reimbursed_cash": parse_int(row.get("quantity-reimbursed-cash", "")),
            "quantity_reimbursed_inventory": parse_int(row.get("quantity-reimbursed-inventory", "")),
            "quantity_reimbursed_total": parse_int(row.get("quantity-reimbursed-total", "")),
            "original_reimbursement_id": row.get("original-reimbursement-id", "").strip() or None,
            "original_reimbursement_type": row.get("original-reimbursement-type", "").strip() or None,
            "import_id": import_id,
        }
        db_rows.append(db_row)

    # Log marketplace distribution
    if marketplace_counts:
        print(f"  Marketplace distribution:")
        for mp, count in sorted(marketplace_counts.items()):
            print(f"    {mp}: {count} rows")

    return db_rows


def pull_region_reimbursements(
    access_token: str,
    region: str,
    start_date: date,
    end_date: date,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Pull reimbursement report ONCE for an entire region, then resolve
    each row to the correct marketplace using currency.

    Amazon returns ALL reimbursements for the region regardless of which
    marketplace_id is passed. So we only need one API call per region.

    Args:
        access_token: Valid SP-API access token
        region: Region code (NA, EU, FE, UAE)
        start_date: Start of date range
        end_date: End of date range
        dry_run: If True, don't write to DB

    Returns:
        Dict with status and per-marketplace counts
    """
    start_time = time.time()
    report_type = FINANCIAL_REPORT_TYPES["REIMBURSEMENTS"]

    # Use anchor marketplace for the API request
    anchor_mp = REGION_ANCHOR_MARKETPLACE[region]

    print(f"\n{'='*60}")
    print(f"Pulling Reimbursements for {region} region")
    print(f"  Anchor marketplace: {anchor_mp}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Will resolve per-row marketplace from currency")
    print(f"{'='*60}")

    # Create tracking records using anchor marketplace
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            anchor_mp,
            start_date,
            import_type="sp_api_reimbursements"
        )
        pull_id = create_financial_pull_record(
            marketplace_code=anchor_mp,
            report_type=report_type,
            pull_date=date.today(),
            import_id=import_id,
            date_range_start=start_date,
            date_range_end=end_date
        )

    try:
        # Pull the report ONCE (create → poll → download)
        rows = pull_reimbursement_report(
            access_token, anchor_mp, region, start_date, end_date
        )

        print(f"  Downloaded: {len(rows)} raw rows from Amazon")

        # Transform rows with per-row marketplace resolution
        db_rows = transform_reimbursement_rows(rows, region, import_id)
        print(f"  Valid rows after resolution: {len(db_rows)}")

        if dry_run:
            print(f"\n  [DRY RUN] Would upsert {len(db_rows)} reimbursement records")
            if db_rows:
                print("\n  Sample rows (first 3):")
                for sample in db_rows[:3]:
                    mp_code = [k for k, v in MARKETPLACE_UUIDS.items() if v == sample["marketplace_id"]][0]
                    print(f"    {mp_code} | {sample['reimbursement_id']} | {sample['currency_unit']} | ${sample.get('amount_total', 0)}")
            return {
                "status": "dry_run",
                "region": region,
                "row_count": len(db_rows)
            }

        # Upsert to database
        row_count = upsert_reimbursements(db_rows)
        processing_time = int((time.time() - start_time) * 1000)

        # Update tracking
        update_data_import(
            import_id, "completed",
            row_count=row_count,
            processing_time_ms=processing_time
        )
        update_financial_pull_status(
            pull_id, "completed",
            row_count=row_count,
            processing_time_ms=processing_time
        )

        print(f"\n  ✓ Completed: {row_count} reimbursement records for {region} region")

        return {
            "status": "completed",
            "region": region,
            "row_count": row_count,
            "processing_time_ms": processing_time
        }

    except Exception as e:
        error_msg = str(e)
        print(f"\n  ✗ Error: {error_msg}")

        if not dry_run and import_id:
            update_data_import(import_id, "failed", error_message=error_msg)
        if not dry_run and pull_id:
            update_financial_pull_status(pull_id, "failed", error_message=error_msg)

        return {
            "status": "failed",
            "region": region,
            "error": error_msg
        }


def main():
    parser = argparse.ArgumentParser(
        description="Pull Reimbursement Reports from SP-API"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD). Default: 60 days ago."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD). Default: today."
    )
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Specific marketplace to pull (e.g., USA, CA, MX). "
             "Note: Report still returns ALL data for the region."
    )
    parser.add_argument(
        "--region",
        type=str,
        default="NA",
        choices=["NA", "EU", "FE", "UAE"],
        help="Region to pull. Default: NA"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pull data but don't write to database"
    )

    args = parser.parse_args()

    region = args.region.upper()

    # Determine dates
    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = date.today() - timedelta(days=60)

    if args.end_date:
        end_date = date.fromisoformat(args.end_date)
    else:
        end_date = date.today()

    # Validate marketplace if provided
    if args.marketplace:
        mp = args.marketplace.upper()
        if mp not in MARKETPLACE_IDS:
            print(f"Error: Invalid marketplace '{mp}'")
            sys.exit(1)
        # Even with --marketplace, we pull the whole region report.
        # The marketplace arg is accepted for backward compat but
        # doesn't change behavior — we always resolve per-row.
        print(f"Note: --marketplace {mp} accepted, but report returns "
              f"entire {region} region. Per-row currency resolution will "
              f"assign correct marketplaces.")

    print("=" * 60)
    print("REIMBURSEMENT REPORT PULL")
    print(f"Region: {region}")
    print(f"Anchor marketplace: {REGION_ANCHOR_MARKETPLACE[region]}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Strategy: Pull ONCE per region, resolve marketplace per-row via currency")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # Get access token for this region
    print("\nGetting access token...")
    access_token = get_access_token(region=region)
    print("✓ Access token obtained")

    # Pull ONCE for the entire region
    result = pull_region_reimbursements(
        access_token,
        region,
        start_date,
        end_date,
        dry_run=args.dry_run
    )

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    status = result["status"]
    if status in ["completed", "dry_run"]:
        row_count = result.get("row_count", 0)
        print(f"  {region}: ✓ {row_count} records (resolved per-row)")
    else:
        print(f"  {region}: ✗ {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
