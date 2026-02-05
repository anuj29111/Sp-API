#!/usr/bin/env python3
"""
Monthly Inventory Snapshot Capture Script

Captures the current inventory state to the monthly snapshots table.
Should be run on the 1st-2nd of each month (via inventory-daily.yml workflow).

This script is idempotent - running multiple times for the same month
will update (not duplicate) the snapshot.

Usage:
    python capture_monthly_inventory.py                    # Auto-detect (only runs on 1st-2nd)
    python capture_monthly_inventory.py --force            # Force capture regardless of date
    python capture_monthly_inventory.py --month 2026-02    # Capture for specific month
    python capture_monthly_inventory.py --dry-run          # Show what would be captured

Environment Variables Required:
    SUPABASE_URL          - Supabase project URL
    SUPABASE_SERVICE_KEY  - Supabase service role key
"""

import os
import sys
import argparse
import time
from datetime import date, datetime
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.db import get_supabase_client, MARKETPLACE_UUIDS


def should_capture_today() -> bool:
    """Check if today is a valid day for monthly capture (1st or 2nd)."""
    return date.today().day <= 2


def get_snapshot_date(month_str: Optional[str] = None) -> date:
    """
    Get the snapshot date (1st of month).

    Args:
        month_str: Optional month in YYYY-MM format, or None for current month

    Returns:
        Date representing 1st of the month
    """
    if month_str:
        # Parse YYYY-MM format
        year, month = map(int, month_str.split("-"))
        return date(year, month, 1)
    else:
        today = date.today()
        return date(today.year, today.month, 1)


def get_latest_inventory_date() -> Optional[date]:
    """Get the most recent date we have inventory data for."""
    client = get_supabase_client()

    result = client.table("sp_fba_inventory") \
        .select("date") \
        .order("date", desc=True) \
        .limit(1) \
        .execute()

    if result.data:
        return date.fromisoformat(result.data[0]["date"])
    return None


def get_inventory_for_snapshot(source_date: date) -> List[Dict]:
    """
    Get all inventory records for a given date.

    Args:
        source_date: The date to get inventory from

    Returns:
        List of inventory records
    """
    client = get_supabase_client()

    result = client.table("sp_fba_inventory") \
        .select("*") \
        .eq("date", source_date.isoformat()) \
        .execute()

    return result.data


def capture_monthly_snapshot(
    snapshot_date: date,
    source_date: date,
    dry_run: bool = False
) -> Dict:
    """
    Capture inventory snapshot for a month.

    Args:
        snapshot_date: 1st of the month to store as snapshot_date
        source_date: Actual date the inventory data is from
        dry_run: If True, don't actually save

    Returns:
        Dict with capture statistics
    """
    print(f"\n📸 Capturing monthly inventory snapshot")
    print(f"   Snapshot date: {snapshot_date} (1st of month)")
    print(f"   Source date: {source_date}")

    # Get inventory data
    inventory_records = get_inventory_for_snapshot(source_date)

    if not inventory_records:
        print(f"   ⚠️  No inventory data found for {source_date}")
        return {"status": "no_data", "records": 0}

    print(f"   📦 Found {len(inventory_records)} inventory records")

    if dry_run:
        print(f"   🏃 DRY RUN - Would capture {len(inventory_records)} records")
        return {"status": "dry_run", "records": len(inventory_records)}

    # Transform records for snapshot table
    snapshot_records = []
    for inv in inventory_records:
        snapshot_record = {
            "snapshot_date": snapshot_date.isoformat(),
            "marketplace_id": inv["marketplace_id"],
            "sku": inv["sku"],
            "asin": inv.get("asin"),
            "fnsku": inv.get("fnsku"),
            "product_name": inv.get("product_name"),
            "fulfillable_quantity": inv.get("fulfillable_quantity", 0),
            "reserved_quantity": inv.get("reserved_quantity", 0),
            "reserved_fc_transfers": inv.get("reserved_fc_transfers", 0),
            "reserved_fc_processing": inv.get("reserved_fc_processing", 0),
            "reserved_customer_orders": inv.get("reserved_customer_orders", 0),
            "inbound_working_quantity": inv.get("inbound_working_quantity", 0),
            "inbound_shipped_quantity": inv.get("inbound_shipped_quantity", 0),
            "inbound_receiving_quantity": inv.get("inbound_receiving_quantity", 0),
            "unfulfillable_quantity": inv.get("unfulfillable_quantity", 0),
            "researching_quantity": inv.get("researching_quantity", 0),
            "source_date": source_date.isoformat(),
            "captured_at": datetime.now().isoformat()
        }
        snapshot_records.append(snapshot_record)

    # Upsert to snapshot table (idempotent)
    client = get_supabase_client()

    # Insert in chunks to avoid timeout
    chunk_size = 100
    inserted_count = 0

    for i in range(0, len(snapshot_records), chunk_size):
        chunk = snapshot_records[i:i + chunk_size]
        client.table("sp_inventory_monthly_snapshots") \
            .upsert(chunk, on_conflict="snapshot_date,marketplace_id,sku") \
            .execute()
        inserted_count += len(chunk)
        print(f"   ✅ Saved {inserted_count}/{len(snapshot_records)} records")

    return {
        "status": "success",
        "records": len(snapshot_records),
        "snapshot_date": snapshot_date.isoformat(),
        "source_date": source_date.isoformat()
    }


def check_existing_snapshot(snapshot_date: date) -> int:
    """Check if we already have a snapshot for this month."""
    client = get_supabase_client()

    result = client.table("sp_inventory_monthly_snapshots") \
        .select("id", count="exact") \
        .eq("snapshot_date", snapshot_date.isoformat()) \
        .limit(1) \
        .execute()

    return result.count or 0


def main():
    parser = argparse.ArgumentParser(
        description="Capture monthly inventory snapshot"
    )
    parser.add_argument(
        "--month",
        type=str,
        help="Month to capture (YYYY-MM format). Default: current month"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force capture even if not 1st-2nd of month"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be captured without saving"
    )

    args = parser.parse_args()

    # Check if we should run today
    if not args.force and not args.month and not should_capture_today():
        print(f"📅 Today is {date.today()}, not 1st or 2nd of month")
        print("   Use --force to capture anyway, or --month YYYY-MM for specific month")
        return

    # Determine snapshot date (1st of month)
    snapshot_date = get_snapshot_date(args.month)

    print("\n" + "=" * 60)
    print("📸 MONTHLY INVENTORY SNAPSHOT CAPTURE")
    print("=" * 60)
    print(f"📅 Snapshot month: {snapshot_date.strftime('%B %Y')}")

    # Check for existing snapshot
    existing_count = check_existing_snapshot(snapshot_date)
    if existing_count > 0:
        print(f"   ⚠️  Existing snapshot found ({existing_count} records)")
        print("   Will update/replace existing records (idempotent)")

    # Get latest inventory date
    latest_inv_date = get_latest_inventory_date()
    if not latest_inv_date:
        print("   ❌ No inventory data found in database")
        sys.exit(1)

    print(f"   📦 Latest inventory data: {latest_inv_date}")

    # Determine source date
    # Prefer 1st of month, but use latest if 1st not available
    source_date = snapshot_date if snapshot_date <= latest_inv_date else latest_inv_date

    # Warn if source date is not exactly the 1st
    if source_date != snapshot_date:
        print(f"   ⚠️  Using {source_date} as source (1st not available)")

    # Capture snapshot
    result = capture_monthly_snapshot(
        snapshot_date=snapshot_date,
        source_date=source_date,
        dry_run=args.dry_run
    )

    # Summary
    print("\n" + "=" * 60)
    print("📊 CAPTURE SUMMARY")
    print("=" * 60)
    print(f"   Status: {result['status']}")
    print(f"   Records: {result['records']}")

    if result["status"] == "success":
        print(f"   ✅ Monthly snapshot captured successfully!")
    elif result["status"] == "dry_run":
        print(f"   🏃 Dry run complete - no data saved")
    else:
        print(f"   ⚠️  No data captured")


if __name__ == "__main__":
    main()
