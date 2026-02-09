#!/usr/bin/env python3
"""
Pull FBA Inventory from SP-API

Uses two strategies depending on region:
- NA: FBA Inventory API v1 (getInventorySummaries) — fast, has detailed breakdowns
- EU/FE: GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA report — includes Pan-European
  FBA (EFN) cross-border stock. The API only returns physically local inventory,
  which misses remote FC stock fulfillable via European Fulfillment Network.

EU report provides:
- afn-fulfillable-quantity: Total sellable (local + remote)
- afn-fulfillable-quantity-local: Units in same-marketplace FCs
- afn-fulfillable-quantity-remote: Units in other EU FCs (cross-border)

Features:
- Automatic retry with exponential backoff on API failures
- Rate limit handling via SPAPIClient
- Slack alerts on failures (if SLACK_WEBHOOK_URL is set)

Usage:
    python pull_inventory.py                          # All NA marketplaces
    python pull_inventory.py --region EU              # EU marketplaces (report-based)
    python pull_inventory.py --marketplace UAE --region EU  # Single EU marketplace
    python pull_inventory.py --dry-run               # Test without DB writes
"""

import os
import sys
import argparse
import time
import logging
from datetime import date, datetime
from typing import Dict, List, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auth import get_access_token
from utils.fba_inventory_api import pull_fba_inventory, MARKETPLACE_IDS
from utils.inventory_reports import (
    pull_fba_inventory_report,
    parse_fba_inventory_report_row,
)
from utils.db import (
    get_supabase_client,
    create_data_import,
    update_data_import,
    MARKETPLACE_UUIDS
)

# Import new resilience modules
from utils.api_client import SPAPIClient, SPAPIError
from utils.alerting import alert_failure

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default marketplaces to pull
DEFAULT_MARKETPLACES = ["USA", "CA", "MX"]

MARKETPLACES_BY_REGION = {
    "NA": ["USA", "CA", "MX"],
    "EU": ["UK", "DE", "FR", "IT", "ES"],
    "FE": ["AU"],
    "UAE": ["UAE"]
}


def create_inventory_pull_record(
    marketplace_code: str,
    report_type: str,
    import_id: str = None
) -> str:
    """Create or update an inventory pull tracking record."""
    client = get_supabase_client()

    today = date.today()

    result = client.table("sp_inventory_pulls").upsert({
        "pull_date": today.isoformat(),
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


def upsert_fba_inventory(
    rows: List[Dict[str, Any]],
    marketplace_code: str,
    import_id: str
) -> int:
    """
    Upsert FBA inventory data to database.

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
    db_rows = []
    for row in rows:
        db_row = {
            "date": today.isoformat(),
            "marketplace_id": marketplace_id,
            "import_id": import_id,
            **row
        }
        db_rows.append(db_row)

    # Batch upsert
    if db_rows:
        chunk_size = 500
        for i in range(0, len(db_rows), chunk_size):
            chunk = db_rows[i:i + chunk_size]
            client.table("sp_fba_inventory").upsert(
                chunk,
                on_conflict="date,marketplace_id,sku"
            ).execute()

    return len(db_rows)


def pull_marketplace_inventory(
    marketplace_code: str,
    region: str = "NA",
    dry_run: bool = False,
    client: SPAPIClient = None,
    access_token: str = None
) -> Dict[str, Any]:
    """
    Pull FBA inventory for a single marketplace.

    For EU/FE regions, uses GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA report
    which includes Pan-European FBA (EFN) cross-border stock. The FBA Inventory
    API only returns physically local stock, which is wrong for EU marketplaces
    like UAE where most inventory is fulfilled cross-border.

    For NA region, uses the FBA Inventory API v1 (faster, includes detailed
    breakdowns like reserved sub-types and damaged sub-types).

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        region: API region
        dry_run: If True, don't write to database
        client: SPAPIClient instance (handles retry and rate limiting)
        access_token: Access token (used for report-based approach)

    Returns:
        Dict with status information
    """
    start_time = time.time()
    use_report = region.upper() in ("EU", "FE", "UAE")
    report_type = "FBA_INVENTORY_REPORT" if use_report else "FBA_INVENTORY_API"

    print(f"\n{'='*50}")
    print(f"Pulling FBA inventory for {marketplace_code} ({'report' if use_report else 'API'})")
    print(f"{'='*50}")

    # Create tracking records
    import_id = None
    pull_id = None

    if not dry_run:
        import_id = create_data_import(
            marketplace_code,
            date.today(),
            import_type="sp_api_fba_inventory"
        )
        pull_id = create_inventory_pull_record(marketplace_code, report_type, import_id)

    try:
        if use_report:
            # EU/FE: Use report-based approach for correct EFN cross-border fulfillable
            print(f"  Using GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA report (includes EFN cross-border)...")
            raw_rows = pull_fba_inventory_report(
                access_token=access_token,
                marketplace_code=marketplace_code,
                region=region
            )
            # Parse report rows to DB format
            rows = []
            for raw_row in raw_rows:
                parsed = parse_fba_inventory_report_row(raw_row)
                if parsed["sku"]:
                    rows.append(parsed)
            print(f"  Parsed {len(rows)} inventory records from report")
        else:
            # NA: Use FBA Inventory API (includes detailed breakdowns)
            rows = pull_fba_inventory(
                access_token=access_token,
                marketplace_code=marketplace_code,
                region=region,
                client=client
            )

        if dry_run:
            print(f"\n[DRY RUN] Would upsert {len(rows)} inventory records")
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
        row_count = upsert_fba_inventory(rows, marketplace_code, import_id)

        processing_time = int((time.time() - start_time) * 1000)

        # Update tracking
        update_data_import(import_id, "completed", row_count=row_count, processing_time_ms=processing_time)
        update_inventory_pull_status(pull_id, "completed", row_count=row_count, processing_time_ms=processing_time)

        print(f"\n✓ Completed: {row_count} inventory records for {marketplace_code}")

        return {
            "status": "completed",
            "marketplace": marketplace_code,
            "row_count": row_count,
            "processing_time_ms": processing_time
        }

    except SPAPIError as e:
        error_msg = str(e)
        logger.error(f"SP-API error for {marketplace_code}: {error_msg}")
        print(f"\n✗ Error for {marketplace_code}: {error_msg}")

        # Send alert
        retry_count = client.stats.get("retries", 0) if client else 0
        alert_failure("fba_inventory", marketplace_code, error_msg, retry_count)

        if not dry_run and import_id:
            update_data_import(import_id, "failed", error_message=error_msg)
        if not dry_run and pull_id:
            update_inventory_pull_status(pull_id, "failed", error_message=error_msg)

        return {
            "status": "failed",
            "marketplace": marketplace_code,
            "error": error_msg
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error for {marketplace_code}: {error_msg}")
        print(f"\n✗ Error for {marketplace_code}: {error_msg}")

        # Send alert
        alert_failure("fba_inventory", marketplace_code, error_msg, 0)

        if not dry_run and import_id:
            update_data_import(import_id, "failed", error_message=error_msg)
        if not dry_run and pull_id:
            update_inventory_pull_status(pull_id, "failed", error_message=error_msg)

        return {
            "status": "failed",
            "marketplace": marketplace_code,
            "error": error_msg
        }


def main():
    parser = argparse.ArgumentParser(description="Pull FBA Inventory from SP-API")
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

    # Determine marketplaces to process
    if args.marketplace:
        marketplaces = [args.marketplace.upper()]
    else:
        marketplaces = MARKETPLACES_BY_REGION.get(region, DEFAULT_MARKETPLACES)

    # Validate marketplaces
    for mp in marketplaces:
        if mp not in MARKETPLACE_IDS:
            print(f"Error: Invalid marketplace '{mp}'")
            print(f"Valid options: {', '.join(MARKETPLACE_IDS.keys())}")
            sys.exit(1)

    print("="*60)
    print("FBA INVENTORY PULL (API)")
    print(f"Date: {date.today()}")
    print(f"Region: {region}")
    print(f"Marketplaces: {', '.join(marketplaces)}")
    print(f"Dry run: {args.dry_run}")
    print("="*60)

    # Get access token and create API client
    print("\nGetting access token...")
    access_token = get_access_token(region=region)
    print("✓ Access token obtained")

    # Create SPAPIClient with retry and rate limiting
    client = SPAPIClient(access_token, region=region)

    # Process each marketplace
    results = []
    for i, marketplace in enumerate(marketplaces):
        # SPAPIClient handles rate limiting automatically - no fixed sleep needed

        result = pull_marketplace_inventory(
            marketplace_code=marketplace,
            region=region,
            dry_run=args.dry_run,
            client=client,
            access_token=access_token
        )
        results.append(result)

    # Log client stats
    stats = client.get_stats()
    logger.info(f"API stats: {stats['requests']} requests, {stats['retries']} retries")

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
