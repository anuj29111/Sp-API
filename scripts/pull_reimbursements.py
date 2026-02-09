#!/usr/bin/env python3
"""
Pull Reimbursement Reports from SP-API

Uses standard CREATE → POLL → DOWNLOAD pattern.
Report type: GET_FBA_REIMBURSEMENTS_DATA

Fields captured:
- reimbursement_id, case_id, amazon_order_id
- reason (e.g., CUSTOMER_RETURN_DAMAGE, WAREHOUSE_LOST, etc.)
- sku, fnsku, asin, product_name
- amount_per_unit, amount_total, currency
- quantity_reimbursed_cash, quantity_reimbursed_inventory

Usage:
    python pull_reimbursements.py                           # Last 60 days, all NA
    python pull_reimbursements.py --start-date 2024-01-01   # Backfill from date
    python pull_reimbursements.py --marketplace USA         # Single marketplace
    python pull_reimbursements.py --dry-run                 # Test without DB writes

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

# Default marketplaces
DEFAULT_MARKETPLACES = ["USA", "CA", "MX"]

MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES"],
    "FE": ["AU"],
    "UAE": ["UAE"]
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


def transform_reimbursement_rows(
    rows: List[Dict],
    marketplace_code: str,
    import_id: str = None
) -> List[Dict]:
    """
    Transform raw TSV rows into database format.

    Args:
        rows: Raw report rows from download_report()
        marketplace_code: Marketplace code
        import_id: Data import tracking ID

    Returns:
        List of dicts ready for upsert
    """
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]
    db_rows = []

    for row in rows:
        reimbursement_id = row.get("reimbursement-id", "").strip()
        if not reimbursement_id:
            continue

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
            "currency_unit": row.get("currency-unit", "").strip() or None,
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

    return db_rows


def pull_marketplace_reimbursements(
    access_token: str,
    marketplace_code: str,
    start_date: date,
    end_date: date,
    region: str = "NA",
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Pull reimbursement report for a single marketplace.
    """
    start_time = time.time()
    report_type = FINANCIAL_REPORT_TYPES["REIMBURSEMENTS"]

    print(f"\n{'='*50}")
    print(f"Pulling Reimbursements for {marketplace_code}")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"{'='*50}")

    # Create tracking records
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            marketplace_code,
            start_date,
            import_type="sp_api_reimbursements"
        )
        pull_id = create_financial_pull_record(
            marketplace_code=marketplace_code,
            report_type=report_type,
            pull_date=date.today(),
            import_id=import_id,
            date_range_start=start_date,
            date_range_end=end_date
        )

    try:
        # Pull the report (create → poll → download)
        rows = pull_reimbursement_report(
            access_token, marketplace_code, region, start_date, end_date
        )

        print(f"  Downloaded: {len(rows)} raw rows")

        # Transform rows
        db_rows = transform_reimbursement_rows(rows, marketplace_code, import_id)
        print(f"  Valid rows: {len(db_rows)}")

        if dry_run:
            print(f"\n  [DRY RUN] Would upsert {len(db_rows)} reimbursement records")
            if db_rows:
                print("\n  Sample row:")
                sample = db_rows[0]
                for key, value in list(sample.items())[:10]:
                    print(f"    {key}: {value}")
            return {
                "status": "dry_run",
                "marketplace": marketplace_code,
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

        print(f"\n  ✓ Completed: {row_count} reimbursement records")

        return {
            "status": "completed",
            "marketplace": marketplace_code,
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
            "marketplace": marketplace_code,
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
        help="Specific marketplace to pull (e.g., USA, CA, MX)"
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

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(region, DEFAULT_MARKETPLACES)

    # Validate
    for mp in marketplaces:
        if mp not in MARKETPLACE_IDS:
            print(f"Error: Invalid marketplace '{mp}'")
            sys.exit(1)

    print("=" * 60)
    print("REIMBURSEMENT REPORT PULL")
    print(f"Region: {region}")
    print(f"Date range: {start_date} to {end_date}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # Get access token
    print("\nGetting access token...")
    access_token = get_access_token(region=region)
    print("✓ Access token obtained")

    # Process each marketplace
    results = []
    for i, marketplace in enumerate(marketplaces):
        if i > 0:
            print("\nWaiting 65 seconds (rate limit for createReport)...")
            time.sleep(65)

        result = pull_marketplace_reimbursements(
            access_token,
            marketplace,
            start_date,
            end_date,
            region=region,
            dry_run=args.dry_run
        )
        results.append(result)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total_rows = 0
    failed = 0
    for result in results:
        marketplace = result["marketplace"]
        status = result["status"]

        if status in ["completed", "dry_run"]:
            row_count = result.get("row_count", 0)
            total_rows += row_count
            print(f"  {marketplace}: ✓ {row_count} records")
        else:
            failed += 1
            print(f"  {marketplace}: ✗ {result.get('error', 'Unknown error')}")

    print(f"\nTotal: {total_rows} records from "
          f"{len(marketplaces) - failed}/{len(marketplaces)} marketplaces")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
