#!/usr/bin/env python3
"""
Pull FBA Storage Fee Report from SP-API

This script pulls monthly storage fee data.
Report type: GET_FBA_STORAGE_FEE_CHARGES_DATA

Fields captured:
- estimated_monthly_storage_fee
- storage_type (standard/oversize)
- product_size_tier
- average_quantity_on_hand
- average_quantity_pending_removal

Usage:
    python pull_storage_fees.py                          # Current month, all marketplaces
    python pull_storage_fees.py --month 2026-01          # Specific month
    python pull_storage_fees.py --marketplace USA        # Single marketplace
    python pull_storage_fees.py --dry-run               # Test without DB writes
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
from utils.inventory_reports import pull_storage_fee_report, MARKETPLACE_IDS
from utils.db import (
    get_supabase_client,
    create_data_import,
    update_data_import,
    MARKETPLACE_UUIDS,
    AMAZON_MARKETPLACE_IDS
)

# Default marketplaces to pull
DEFAULT_MARKETPLACES = ["USA", "CA", "MX"]


def parse_decimal(value: str) -> float:
    """Parse string to decimal/float, handling empty strings and None."""
    if value is None or value == '' or value == 'N/A':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def create_inventory_pull_record(
    marketplace_code: str,
    report_type: str,
    pull_date: date,
    import_id: str = None
) -> str:
    """Create or update an inventory pull tracking record."""
    client = get_supabase_client()

    result = client.table("sp_inventory_pulls").upsert({
        "pull_date": pull_date.isoformat(),
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "report_type": report_type,
        "status": "pending",
        "import_id": import_id,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "error_message": None,
        "row_count": None
    }, on_conflict="pull_date,marketplace_id,report_type").execute()

    return result.data[0]["id"]


def update_inventory_pull_status(
    pull_id: str,
    status: str,
    row_count: int = None,
    error_message: str = None,
    processing_time_ms: int = None
):
    """Update inventory pull tracking record."""
    client = get_supabase_client()

    update_data = {"status": status}
    if row_count is not None:
        update_data["row_count"] = row_count
    if error_message:
        update_data["error_message"] = error_message
    if processing_time_ms is not None:
        update_data["processing_time_ms"] = processing_time_ms
    if status in ["completed", "failed"]:
        update_data["completed_at"] = datetime.utcnow().isoformat()

    client.table("sp_inventory_pulls").update(update_data).eq("id", pull_id).execute()


def upsert_storage_fees(
    rows: List[Dict[str, Any]],
    marketplace_code: str,
    month: date,
    import_id: str
) -> int:
    """
    Upsert storage fee data to database.

    Args:
        rows: Parsed report rows
        marketplace_code: Marketplace code
        month: First day of the month
        import_id: Data import tracking ID

    Returns:
        Number of rows upserted
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    if not rows:
        return 0

    # Transform to database format
    # Note: Amazon report uses underscores in field names (e.g., product_name, not product-name)
    db_rows = []
    for row in rows:
        db_row = {
            "month": month.isoformat(),
            "marketplace_id": marketplace_id,
            "sku": row.get("sku", ""),
            "asin": row.get("asin"),
            "fnsku": row.get("fnsku"),
            "product_name": row.get("product_name"),

            # Fee data
            "storage_type": row.get("dangerous_goods_storage_type", row.get("storage_type")),
            "product_size_tier": row.get("product_size_tier"),
            "average_quantity_on_hand": parse_decimal(row.get("average_quantity_on_hand")),
            "average_quantity_pending_removal": parse_decimal(row.get("average_quantity_pending_removal")),
            "estimated_monthly_storage_fee": parse_decimal(row.get("estimated_monthly_storage_fee")),
            "currency_code": row.get("currency"),

            "import_id": import_id
        }

        # Skip rows without SKU
        if db_row["sku"]:
            db_rows.append(db_row)

    # Batch upsert
    if db_rows:
        chunk_size = 500
        for i in range(0, len(db_rows), chunk_size):
            chunk = db_rows[i:i + chunk_size]
            client.table("sp_storage_fees").upsert(
                chunk,
                on_conflict="month,marketplace_id,sku"
            ).execute()

    return len(db_rows)


def pull_marketplace_storage_fees(
    access_token: str,
    marketplace_code: str,
    month: date,
    region: str = "NA",
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Pull storage fees for a single marketplace and month.
    """
    start_time = time.time()
    report_type = "GET_FBA_STORAGE_FEE_CHARGES_DATA"

    print(f"\n{'='*50}")
    print(f"Pulling Storage Fees for {marketplace_code} ({month.strftime('%Y-%m')})")
    print(f"{'='*50}")

    # Create tracking records
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            marketplace_code,
            month,
            import_type="sp_api_storage_fees"
        )
        pull_id = create_inventory_pull_record(marketplace_code, report_type, month, import_id)

    try:
        # Pull the report
        rows = pull_storage_fee_report(access_token, marketplace_code, month, region)

        if dry_run:
            print(f"\n[DRY RUN] Would upsert {len(rows)} storage fee records")
            if rows:
                print("\nSample row:")
                sample = rows[0]
                for key, value in sample.items():
                    print(f"  {key}: {value}")
            return {
                "status": "dry_run",
                "marketplace": marketplace_code,
                "month": month.strftime('%Y-%m'),
                "row_count": len(rows)
            }

        # Upsert to database
        row_count = upsert_storage_fees(rows, marketplace_code, month, import_id)

        processing_time = int((time.time() - start_time) * 1000)

        # Update tracking
        update_data_import(import_id, "completed", row_count=row_count, processing_time_ms=processing_time)
        update_inventory_pull_status(pull_id, "completed", row_count=row_count, processing_time_ms=processing_time)

        print(f"\n✓ Completed: {row_count} storage fee records for {marketplace_code}")

        return {
            "status": "completed",
            "marketplace": marketplace_code,
            "month": month.strftime('%Y-%m'),
            "row_count": row_count,
            "processing_time_ms": processing_time
        }

    except Exception as e:
        error_msg = str(e)
        print(f"\n✗ Error for {marketplace_code}: {error_msg}")

        if not dry_run and import_id:
            update_data_import(import_id, "failed", error_message=error_msg)
        if not dry_run and pull_id:
            update_inventory_pull_status(pull_id, "failed", error_message=error_msg)

        return {
            "status": "failed",
            "marketplace": marketplace_code,
            "month": month.strftime('%Y-%m'),
            "error": error_msg
        }


def main():
    parser = argparse.ArgumentParser(description="Pull Storage Fees from SP-API")
    parser.add_argument(
        "--marketplace",
        type=str,
        help="Specific marketplace to pull (e.g., USA, CA, MX)"
    )
    parser.add_argument(
        "--month",
        type=str,
        help="Month to pull fees for (YYYY-MM format). Defaults to previous month."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pull data but don't write to database"
    )

    args = parser.parse_args()

    # Determine month
    if args.month:
        try:
            month = datetime.strptime(args.month, "%Y-%m").date().replace(day=1)
        except ValueError:
            print(f"Error: Invalid month format '{args.month}'. Use YYYY-MM.")
            sys.exit(1)
    else:
        # Default to previous month
        today = date.today()
        if today.month == 1:
            month = date(today.year - 1, 12, 1)
        else:
            month = date(today.year, today.month - 1, 1)

    # Determine marketplaces
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = DEFAULT_MARKETPLACES

    # Validate marketplaces
    for mp in marketplaces:
        if mp not in MARKETPLACE_IDS:
            print(f"Error: Invalid marketplace '{mp}'")
            sys.exit(1)

    print("="*60)
    print("STORAGE FEE PULL")
    print(f"Month: {month.strftime('%Y-%m')}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Dry run: {args.dry_run}")
    print("="*60)

    # Get access token
    print("\nGetting access token...")
    access_token = get_access_token()
    print("✓ Access token obtained")

    # Process each marketplace
    results = []
    for i, marketplace in enumerate(marketplaces):
        if i > 0:
            print("\nWaiting 65 seconds (rate limit)...")
            time.sleep(65)

        result = pull_marketplace_storage_fees(
            access_token,
            marketplace,
            month,
            region="NA",
            dry_run=args.dry_run
        )
        results.append(result)

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    total_rows = 0
    failed = 0
    for result in results:
        status = result["status"]
        marketplace = result["marketplace"]

        if status == "completed" or status == "dry_run":
            row_count = result.get("row_count", 0)
            total_rows += row_count
            print(f"  {marketplace}: ✓ {row_count} records")
        else:
            failed += 1
            print(f"  {marketplace}: ✗ {result.get('error', 'Unknown error')}")

    print(f"\nTotal: {total_rows} records from {len(marketplaces) - failed}/{len(marketplaces)} marketplaces")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
