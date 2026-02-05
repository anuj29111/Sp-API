#!/usr/bin/env python3
"""
Pull AWD Inventory from SP-API using the AWD API v2024-05-09

This script pulls the current AWD (Amazon Warehousing and Distribution) inventory.
AWD stores inventory that gets distributed to FBA fulfillment centers.

Fields captured:
- total_onhand_quantity (in AWD distribution centers)
- total_inbound_quantity (in-transit to AWD)
- available_quantity (available for replenishment)
- reserved_quantity (reserved for replenishment orders)

Usage:
    python pull_awd_inventory.py                    # Pull AWD inventory
    python pull_awd_inventory.py --dry-run          # Test without DB writes
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
from utils.awd_api import pull_awd_inventory
from utils.db import (
    get_supabase_client,
    create_data_import,
    update_data_import,
    MARKETPLACE_UUIDS
)

# AWD is typically only for USA marketplace
DEFAULT_MARKETPLACE = "USA"


def create_awd_pull_record(
    marketplace_code: str,
    import_id: str = None
) -> str:
    """Create or update an AWD inventory pull tracking record."""
    client = get_supabase_client()
    today = date.today()

    result = client.table("sp_inventory_pulls").upsert({
        "pull_date": today.isoformat(),
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "report_type": "AWD_INVENTORY_API",
        "status": "pending",
        "import_id": import_id,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "error_message": None,
        "row_count": None
    }, on_conflict="pull_date,marketplace_id,report_type").execute()

    return result.data[0]["id"]


def update_awd_pull_status(
    pull_id: str,
    status: str,
    row_count: int = None,
    error_message: str = None,
    processing_time_ms: int = None
):
    """Update AWD inventory pull tracking record."""
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


def upsert_awd_inventory(
    rows: List[Dict[str, Any]],
    marketplace_code: str,
    import_id: str
) -> int:
    """
    Upsert AWD inventory data to database.

    Args:
        rows: Transformed inventory records from the API
        marketplace_code: Marketplace code
        import_id: Data import tracking ID

    Returns:
        Number of rows upserted
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]
    today = date.today()

    if not rows:
        return 0

    # Add date, marketplace_id, and import_id to each row
    # Remove total_quantity as it's a generated column
    db_rows = []
    for row in rows:
        db_row = {
            "date": today.isoformat(),
            "marketplace_id": marketplace_id,
            "import_id": import_id,
            "sku": row["sku"],
            "total_onhand_quantity": row["total_onhand_quantity"],
            "total_inbound_quantity": row["total_inbound_quantity"],
            "available_quantity": row["available_quantity"],
            "reserved_quantity": row["reserved_quantity"],
        }
        db_rows.append(db_row)

    # Batch upsert
    if db_rows:
        chunk_size = 500
        for i in range(0, len(db_rows), chunk_size):
            chunk = db_rows[i:i + chunk_size]
            client.table("sp_awd_inventory").upsert(
                chunk,
                on_conflict="date,marketplace_id,sku"
            ).execute()

    return len(db_rows)


def pull_awd(
    access_token: str,
    marketplace_code: str = "USA",
    region: str = "NA",
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Pull AWD inventory.

    Returns:
        Dict with status information
    """
    start_time = time.time()

    print(f"\n{'='*50}")
    print(f"Pulling AWD inventory for {marketplace_code}")
    print(f"{'='*50}")

    # Create tracking records
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            marketplace_code,
            date.today(),
            import_type="sp_api_awd_inventory"
        )
        pull_id = create_awd_pull_record(marketplace_code, import_id)

    try:
        # Pull using the AWD API
        rows = pull_awd_inventory(access_token, region)

        if dry_run:
            print(f"\n[DRY RUN] Would upsert {len(rows)} AWD inventory records")
            # Print sample
            if rows:
                print("\nSample row:")
                sample = rows[0]
                for key, value in sample.items():
                    print(f"  {key}: {value}")
            return {
                "status": "dry_run",
                "marketplace": marketplace_code,
                "row_count": len(rows)
            }

        # Upsert to database
        row_count = upsert_awd_inventory(rows, marketplace_code, import_id)

        processing_time = int((time.time() - start_time) * 1000)

        # Update tracking
        update_data_import(import_id, "completed", row_count=row_count, processing_time_ms=processing_time)
        update_awd_pull_status(pull_id, "completed", row_count=row_count, processing_time_ms=processing_time)

        print(f"\n✓ Completed: {row_count} AWD inventory records")

        return {
            "status": "completed",
            "marketplace": marketplace_code,
            "row_count": row_count,
            "processing_time_ms": processing_time
        }

    except Exception as e:
        error_msg = str(e)
        print(f"\n✗ Error: {error_msg}")

        if not dry_run and import_id:
            update_data_import(import_id, "failed", error_message=error_msg)
        if not dry_run and pull_id:
            update_awd_pull_status(pull_id, "failed", error_message=error_msg)

        return {
            "status": "failed",
            "marketplace": marketplace_code,
            "error": error_msg
        }


def main():
    parser = argparse.ArgumentParser(description="Pull AWD Inventory from SP-API")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pull data but don't write to database"
    )

    args = parser.parse_args()

    print("="*60)
    print("AWD INVENTORY PULL (API)")
    print(f"Date: {date.today()}")
    print(f"Marketplace: {DEFAULT_MARKETPLACE}")
    print(f"Dry run: {args.dry_run}")
    print("="*60)

    # Get access token
    print("\nGetting access token...")
    access_token = get_access_token()
    print("✓ Access token obtained")

    # Pull AWD inventory
    result = pull_awd(
        access_token,
        marketplace_code=DEFAULT_MARKETPLACE,
        region="NA",
        dry_run=args.dry_run
    )

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    status = result["status"]
    if status == "completed" or status == "dry_run":
        row_count = result.get("row_count", 0)
        print(f"  {DEFAULT_MARKETPLACE}: ✓ {row_count} AWD records")
    else:
        print(f"  {DEFAULT_MARKETPLACE}: ✗ {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
