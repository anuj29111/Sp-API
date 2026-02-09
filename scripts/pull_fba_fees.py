#!/usr/bin/env python3
"""
Pull FBA Fee Estimates Report from SP-API

Uses standard CREATE → POLL → DOWNLOAD pattern.
Report type: GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA

This report shows CURRENT fee estimates per ASIN (not historical).
Used for projections and fee monitoring, NOT for historical CM2 calculation.
(Settlement reports contain actual historical fees.)

Requirements:
- dataStartTime must be at least 72 hours prior to now
- Can only be requested once per day per seller

Fields captured:
- estimated_fee_total (referral + fulfillment)
- estimated_referral_fee_per_unit
- estimated_pick_pack_fee_per_unit (FBA fee)
- estimated_weight_handling_fee_per_unit
- product_size_tier
- your_price, sales_price
- item dimensions and weight

Usage:
    python pull_fba_fees.py                        # All NA marketplaces
    python pull_fba_fees.py --marketplace USA       # Single marketplace
    python pull_fba_fees.py --dry-run              # Test without DB writes

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
from datetime import date, datetime
from typing import Dict, List, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auth import get_access_token
from utils.financial_reports import (
    pull_fba_fee_report,
    FINANCIAL_REPORT_TYPES
)
from utils.inventory_reports import MARKETPLACE_IDS
from utils.db import (
    get_supabase_client,
    create_data_import,
    update_data_import,
    create_financial_pull_record,
    update_financial_pull_status,
    upsert_fba_fee_estimates,
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


def transform_fee_estimate_rows(
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
        sku = row.get("sku", "").strip()
        if not sku:
            continue

        db_row = {
            "marketplace_id": marketplace_id,
            "sku": sku,
            "asin": row.get("asin", "").strip() or None,
            "fnsku": row.get("fnsku", "").strip() or None,
            "product_name": row.get("product-name", "").strip() or None,

            # Pricing
            "your_price": parse_decimal(row.get("your-price", "")),
            "sales_price": parse_decimal(row.get("sales-price", "")),

            # Size tier
            "product_size_tier": row.get("product-size-tier", "").strip() or None,
            "currency_code": row.get("currency", "").strip() or None,

            # Fee estimates
            "estimated_fee_total": parse_decimal(
                row.get("estimated-fee-total", "")
            ),
            "estimated_referral_fee_per_unit": parse_decimal(
                row.get("estimated-referral-fee-per-unit", "")
            ),
            "estimated_variable_closing_fee": parse_decimal(
                row.get("estimated-variable-closing-fee", "")
            ),
            "estimated_pick_pack_fee_per_unit": parse_decimal(
                row.get("estimated-order-handling-fee-per-order",
                         row.get("estimated-pick-pack-fee-per-unit", ""))
            ),
            "estimated_weight_handling_fee_per_unit": parse_decimal(
                row.get("estimated-weight-handling-fee-per-unit", "")
            ),

            # Dimensions
            "longest_side": parse_decimal(row.get("longest-side", "")),
            "median_side": parse_decimal(row.get("median-side", "")),
            "shortest_side": parse_decimal(row.get("shortest-side", "")),
            "length_and_girth": parse_decimal(row.get("length-and-girth", "")),
            "unit_of_dimension": row.get("unit-of-dimension", "").strip() or None,
            "item_package_weight": parse_decimal(row.get("item-package-weight", "")),
            "unit_of_weight": row.get("unit-of-weight", "").strip() or None,

            # Metadata
            "pull_date": date.today().isoformat(),
            "import_id": import_id,
        }
        db_rows.append(db_row)

    # Deduplicate by SKU (keep last occurrence)
    seen = {}
    for row in db_rows:
        seen[row["sku"]] = row
    db_rows = list(seen.values())

    return db_rows


def pull_marketplace_fba_fees(
    access_token: str,
    marketplace_code: str,
    region: str = "NA",
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Pull FBA fee estimates for a single marketplace.
    """
    start_time = time.time()
    report_type = FINANCIAL_REPORT_TYPES["FBA_FEE_ESTIMATES"]

    print(f"\n{'='*50}")
    print(f"Pulling FBA Fee Estimates for {marketplace_code}")
    print(f"{'='*50}")

    # Create tracking records
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            marketplace_code,
            date.today(),
            import_type="sp_api_fba_fee_estimates"
        )
        pull_id = create_financial_pull_record(
            marketplace_code=marketplace_code,
            report_type=report_type,
            pull_date=date.today(),
            import_id=import_id
        )

    try:
        # Pull the report (create → poll → download)
        rows = pull_fba_fee_report(access_token, marketplace_code, region)

        print(f"  Downloaded: {len(rows)} raw rows")

        # Transform rows
        db_rows = transform_fee_estimate_rows(rows, marketplace_code, import_id)
        print(f"  Valid rows (deduped): {len(db_rows)}")

        if dry_run:
            print(f"\n  [DRY RUN] Would upsert {len(db_rows)} fee estimate records")
            if db_rows:
                print("\n  Sample row:")
                sample = db_rows[0]
                for key, value in list(sample.items())[:12]:
                    print(f"    {key}: {value}")
            return {
                "status": "dry_run",
                "marketplace": marketplace_code,
                "row_count": len(db_rows)
            }

        # Upsert to database
        row_count = upsert_fba_fee_estimates(db_rows)
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

        print(f"\n  ✓ Completed: {row_count} fee estimate records")

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
        description="Pull FBA Fee Estimates from SP-API"
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
    print("FBA FEE ESTIMATES PULL")
    print(f"Region: {region}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # Get access token
    print("\nGetting access token...")
    access_token = get_access_token(region=region)
    print("✓ Access token obtained")

    # Process each marketplace
    # NOTE: This report can only be requested once per day per seller.
    # Rate limit: 1 createReport per minute
    results = []
    for i, marketplace in enumerate(marketplaces):
        if i > 0:
            print("\nWaiting 65 seconds (rate limit for createReport)...")
            time.sleep(65)

        result = pull_marketplace_fba_fees(
            access_token,
            marketplace,
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
