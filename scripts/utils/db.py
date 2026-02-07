"""
Supabase Database Module
Handles all database operations for SP-API data
"""

import os
from typing import Dict, List, Optional, Any
from datetime import date, datetime
from supabase import create_client, Client

# Supabase client singleton
_supabase_client: Optional[Client] = None

# Marketplace UUID mapping (from Supabase marketplaces table)
MARKETPLACE_UUIDS = {
    "USA": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "CA": "a1b2c3d4-58cc-4372-a567-0e02b2c3d480",
    "UK": "b2c3d4e5-58cc-4372-a567-0e02b2c3d481",
    "DE": "c3d4e5f6-58cc-4372-a567-0e02b2c3d482",
    "FR": "d4e5f6a7-58cc-4372-a567-0e02b2c3d483",
    "UAE": "e5f6a7b8-58cc-4372-a567-0e02b2c3d484",
    "AU": "f6a7b8c9-58cc-4372-a567-0e02b2c3d485",
    "IT": "a7b8c9d0-58cc-4372-a567-0e02b2c3d486",
    "ES": "b8c9d0e1-58cc-4372-a567-0e02b2c3d487",
    "MX": "c9d0e1f2-58cc-4372-a567-0e02b2c3d488",
    "JP": "d0e1f2a3-58cc-4372-a567-0e02b2c3d489"
}

# Amazon Marketplace IDs
AMAZON_MARKETPLACE_IDS = {
    "USA": "ATVPDKIKX0DER",
    "CA": "A2EUQ1WTGCTBG2",
    "MX": "A1AM78C64UM0Y8",
    "UK": "A1F83G8C2ARO7P",
    "DE": "A1PA6795UKMFR9",
    "FR": "A13V1IB3VIYZZH",
    "IT": "APJ6JRA9NG5V4",
    "ES": "A1RKKUPIHCS9HS",
    "UAE": "A2VIGQ35RCS4UG",
    "AU": "A39IBJ37TRP1C6",
    "JP": "A1VC38T7YXB528"
}


def get_supabase_client() -> Client:
    """
    Get or create Supabase client singleton.

    Returns:
        Supabase client instance

    Raises:
        ValueError: If credentials are missing
    """
    global _supabase_client

    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables")

        _supabase_client = create_client(url, key)

    return _supabase_client


def create_data_import(
    marketplace_code: str,
    report_date: date,
    import_type: str = "sp_api_sales_traffic"
) -> str:
    """
    Create a data_imports record for tracking.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: The date being imported
        import_type: Type of import

    Returns:
        Import ID (UUID string)
    """
    client = get_supabase_client()

    result = client.table("data_imports").insert({
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "import_type": import_type,
        "period_start_date": report_date.isoformat(),
        "period_end_date": report_date.isoformat(),
        "period_type": "daily",
        "status": "processing"
    }).execute()

    return result.data[0]["id"]


def update_data_import(
    import_id: str,
    status: str,
    row_count: Optional[int] = None,
    error_message: Optional[str] = None,
    processing_time_ms: Optional[int] = None
):
    """Update a data_imports record."""
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

    client.table("data_imports").update(update_data).eq("id", import_id).execute()


def create_pull_record(
    marketplace_code: str,
    report_date: date,
    report_id: Optional[str] = None,
    import_id: Optional[str] = None
) -> str:
    """
    Create or update an sp_api_pulls record for tracking.
    Uses upsert to handle re-pulls (e.g., for late attribution refresh).

    Returns:
        Pull record ID (UUID string)
    """
    client = get_supabase_client()

    # Use upsert to handle re-pulls (unique constraint on pull_date + marketplace_id)
    result = client.table("sp_api_pulls").upsert({
        "pull_date": report_date.isoformat(),
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "amazon_marketplace_id": AMAZON_MARKETPLACE_IDS[marketplace_code],
        "report_id": report_id,
        "status": "pending",
        "import_id": import_id,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "error_message": None,
        "asin_count": None
    }, on_conflict="pull_date,marketplace_id").execute()

    return result.data[0]["id"]


def update_pull_status(
    pull_id: str,
    status: str,
    report_id: Optional[str] = None,
    report_document_id: Optional[str] = None,
    asin_count: Optional[int] = None,
    error_message: Optional[str] = None,
    processing_time_ms: Optional[int] = None
):
    """Update an sp_api_pulls record."""
    client = get_supabase_client()

    update_data = {"status": status}
    if report_id:
        update_data["report_id"] = report_id
    if report_document_id:
        update_data["report_document_id"] = report_document_id
    if asin_count is not None:
        update_data["asin_count"] = asin_count
    if error_message:
        update_data["error_message"] = error_message
    if processing_time_ms is not None:
        update_data["processing_time_ms"] = processing_time_ms
    if status in ["completed", "failed"]:
        update_data["completed_at"] = datetime.utcnow().isoformat()

    client.table("sp_api_pulls").update(update_data).eq("id", pull_id).execute()


def upsert_asin_data(
    report_data: Dict[str, Any],
    marketplace_code: str,
    report_date: date,
    import_id: str
) -> int:
    """
    Upsert ASIN-level sales and traffic data.

    Args:
        report_data: Parsed report data from SP-API
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: The date of the data
        import_id: The data_imports ID for tracking

    Returns:
        Number of rows upserted
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    asin_data = report_data.get("salesAndTrafficByAsin", [])
    if not asin_data:
        return 0

    # Determine currency from first record
    currency_code = None
    if asin_data:
        first_sales = asin_data[0].get("salesByAsin", {})
        sales_amount = first_sales.get("orderedProductSales", {})
        currency_code = sales_amount.get("currencyCode", "USD")

    # Transform to database format
    rows = []
    for item in asin_data:
        sales = item.get("salesByAsin", {})
        traffic = item.get("trafficByAsin", {})

        row = {
            "date": report_date.isoformat(),
            "marketplace_id": marketplace_id,
            "parent_asin": item.get("parentAsin"),
            "child_asin": item.get("childAsin"),

            # Sales metrics
            "units_ordered": sales.get("unitsOrdered", 0),
            "units_ordered_b2b": sales.get("unitsOrderedB2B", 0),
            "ordered_product_sales": sales.get("orderedProductSales", {}).get("amount", 0),
            "ordered_product_sales_b2b": sales.get("orderedProductSalesB2B", {}).get("amount", 0),
            "currency_code": currency_code,
            "total_order_items": sales.get("totalOrderItems", 0),
            "total_order_items_b2b": sales.get("totalOrderItemsB2B", 0),

            # Traffic metrics
            "sessions": traffic.get("sessions", 0),
            "sessions_b2b": traffic.get("sessionsB2B", 0),
            "page_views": traffic.get("pageViews", 0),
            "page_views_b2b": traffic.get("pageViewsB2B", 0),
            "browser_sessions": traffic.get("browserSessions", 0),
            "mobile_app_sessions": traffic.get("mobileAppSessions", 0),
            "browser_page_views": traffic.get("browserPageViews", 0),
            "mobile_app_page_views": traffic.get("mobileAppPageViews", 0),
            "buy_box_percentage": traffic.get("buyBoxPercentage"),
            "buy_box_percentage_b2b": traffic.get("buyBoxPercentageB2B"),
            "unit_session_percentage": traffic.get("unitSessionPercentage"),
            "unit_session_percentage_b2b": traffic.get("unitSessionPercentageB2B"),

            # Tracking
            "import_id": import_id,
            "data_source": "sales_traffic"
        }
        rows.append(row)

    # Batch upsert (Supabase handles ON CONFLICT)
    if rows:
        client.table("sp_daily_asin_data").upsert(
            rows,
            on_conflict="date,marketplace_id,child_asin"
        ).execute()

    return len(rows)


def upsert_totals(
    report_data: Dict[str, Any],
    marketplace_code: str,
    report_date: date,
    import_id: str
) -> bool:
    """
    Upsert account-level daily totals.

    Args:
        report_data: Parsed report data from SP-API
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: The date of the data
        import_id: The data_imports ID for tracking

    Returns:
        True if successful
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    # Get daily totals from salesAndTrafficByDate
    date_data = report_data.get("salesAndTrafficByDate", [])
    if not date_data:
        return False

    # Should be exactly one entry for single-day report
    day_data = date_data[0]
    sales = day_data.get("salesByDate", {})
    traffic = day_data.get("trafficByDate", {})

    currency_code = sales.get("orderedProductSales", {}).get("currencyCode", "USD")

    row = {
        "date": report_date.isoformat(),
        "marketplace_id": marketplace_id,

        # Sales totals
        "units_ordered": sales.get("unitsOrdered", 0),
        "units_ordered_b2b": sales.get("unitsOrderedB2B", 0),
        "ordered_product_sales": sales.get("orderedProductSales", {}).get("amount", 0),
        "ordered_product_sales_b2b": sales.get("orderedProductSalesB2B", {}).get("amount", 0),
        "currency_code": currency_code,
        "total_order_items": sales.get("totalOrderItems", 0),
        "total_order_items_b2b": sales.get("totalOrderItemsB2B", 0),

        # Traffic totals
        "sessions": traffic.get("sessions", 0),
        "sessions_b2b": traffic.get("sessionsB2B", 0),
        "page_views": traffic.get("pageViews", 0),
        "page_views_b2b": traffic.get("pageViewsB2B", 0),
        "buy_box_percentage": traffic.get("buyBoxPercentage"),
        "unit_session_percentage": traffic.get("unitSessionPercentage"),

        # Tracking
        "import_id": import_id
    }

    client.table("sp_daily_totals").upsert(
        row,
        on_conflict="date,marketplace_id"
    ).execute()

    return True


def get_existing_pull(marketplace_code: str, report_date: date) -> Optional[Dict]:
    """
    Check if a pull already exists for this marketplace/date.

    Returns:
        Pull record if exists, None otherwise
    """
    client = get_supabase_client()

    result = client.table("sp_api_pulls").select("*").eq(
        "marketplace_id", MARKETPLACE_UUIDS[marketplace_code]
    ).eq(
        "pull_date", report_date.isoformat()
    ).execute()

    if result.data:
        return result.data[0]
    return None


# =============================================================================
# Orders Data Functions (near-real-time orders report)
# =============================================================================

def upsert_orders_asin_data(
    rows: List[Dict],
    marketplace_code: str,
    report_date: date,
    chunk_size: int = 500
) -> int:
    """
    Upsert ASIN-level sales data from the orders report.

    Orders data only includes sales columns (units, revenue) — no traffic.
    If a row already has data_source='sales_traffic' (from S&T report),
    we skip it to avoid overwriting more complete data with less accurate orders data.

    Args:
        rows: List of aggregated order dicts with keys:
              child_asin, units_ordered, ordered_product_sales,
              total_order_items, currency_code
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: The date of the data
        chunk_size: Number of rows per upsert batch

    Returns:
        Number of rows upserted (excluding skipped S&T rows)
    """
    if not rows:
        return 0

    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    # Step 1: Check which ASINs already have S&T data for this date/marketplace
    # We don't want to overwrite S&T data (which has traffic metrics) with orders data
    existing = client.table("sp_daily_asin_data") \
        .select("child_asin") \
        .eq("marketplace_id", marketplace_id) \
        .eq("date", report_date.isoformat()) \
        .eq("data_source", "sales_traffic") \
        .execute()

    st_asins = set(r["child_asin"] for r in existing.data) if existing.data else set()

    # Step 2: Filter out ASINs that already have S&T data
    filtered_rows = []
    skipped = 0
    for row in rows:
        if row.get("child_asin") in st_asins:
            skipped += 1
            continue

        filtered_rows.append({
            "date": report_date.isoformat(),
            "marketplace_id": marketplace_id,
            "child_asin": row["child_asin"],
            "parent_asin": row.get("parent_asin"),
            "units_ordered": row.get("units_ordered", 0),
            "ordered_product_sales": row.get("ordered_product_sales", 0),
            "total_order_items": row.get("total_order_items", 0),
            "currency_code": row.get("currency_code", "USD"),
            "data_source": "orders"
        })

    if skipped > 0:
        print(f"  ⏭️  Skipped {skipped} ASINs (already have S&T data)")

    # Step 3: Upsert in chunks
    if not filtered_rows:
        return 0

    total = 0
    num_chunks = (len(filtered_rows) + chunk_size - 1) // chunk_size

    for i in range(0, len(filtered_rows), chunk_size):
        chunk = filtered_rows[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        try:
            client.table("sp_daily_asin_data").upsert(
                chunk,
                on_conflict="date,marketplace_id,child_asin"
            ).execute()
            total += len(chunk)
            if num_chunks > 1:
                print(f"    [upsert chunk {chunk_num}/{num_chunks}: {len(chunk)} rows OK]", flush=True)
        except Exception as e:
            print(f"    [upsert chunk {chunk_num}/{num_chunks}: FAILED - {str(e)[:200]}]", flush=True)
            raise

    return total


# =============================================================================
# Pull Checkpoint Functions (for sp_pull_checkpoints table)
# =============================================================================

def get_pull_checkpoint(
    pull_type: str,
    pull_date: date,
    region: str = "NA"
) -> Optional[Dict]:
    """
    Get checkpoint data for a pull.

    Args:
        pull_type: Type of pull ('sales_traffic', 'fba_inventory', etc.)
        pull_date: Date being pulled
        region: API region

    Returns:
        Checkpoint record if exists, None otherwise
    """
    client = get_supabase_client()

    result = client.table("sp_pull_checkpoints").select("*").eq(
        "pull_type", pull_type
    ).eq(
        "pull_date", pull_date.isoformat()
    ).eq(
        "region", region
    ).execute()

    if result.data:
        return result.data[0]
    return None


def get_incomplete_checkpoints(
    pull_type: str,
    region: str = "NA"
) -> List[Dict]:
    """
    Get all incomplete pull checkpoints for a type.

    Useful for finding pulls that need to be resumed.

    Args:
        pull_type: Type of pull
        region: API region

    Returns:
        List of incomplete checkpoint records
    """
    client = get_supabase_client()

    result = client.table("sp_pull_checkpoints").select("*").eq(
        "pull_type", pull_type
    ).eq(
        "region", region
    ).in_(
        "status", ["in_progress", "partial"]
    ).order("pull_date", desc=True).execute()

    return result.data


def update_pull_checkpoint(
    pull_type: str,
    pull_date: date,
    region: str = "NA",
    status: str = None,
    marketplace_status: Dict = None,
    checkpoint_data: Dict = None,
    error_count: int = None,
    last_error: str = None,
    total_row_count: int = None
) -> str:
    """
    Update or create a pull checkpoint record.

    Uses upsert to handle both create and update.

    Returns:
        Checkpoint record ID
    """
    client = get_supabase_client()

    data = {
        "pull_type": pull_type,
        "pull_date": pull_date.isoformat(),
        "region": region
    }

    if status is not None:
        data["status"] = status
    if marketplace_status is not None:
        data["marketplace_status"] = marketplace_status
    if checkpoint_data is not None:
        data["checkpoint_data"] = checkpoint_data
    if error_count is not None:
        data["error_count"] = error_count
    if last_error is not None:
        data["last_error"] = last_error
    if total_row_count is not None:
        data["total_row_count"] = total_row_count

    if status == "completed":
        data["completed_at"] = datetime.utcnow().isoformat()

    result = client.table("sp_pull_checkpoints").upsert(
        data,
        on_conflict="pull_type,pull_date,region"
    ).execute()

    return result.data[0]["id"]


# =============================================================================
# SQP/SCP Functions (Search Query Performance / Search Catalog Performance)
# =============================================================================

def upsert_sqp_data(rows: List[Dict], chunk_size: int = 200) -> int:
    """
    Batch upsert SQP data rows into sp_sqp_data.

    Uses small chunks (200 rows) to avoid Cloudflare/Supabase POST body size
    limits. SQP rows have ~47 columns so 200 rows ≈ safe payload size.

    Args:
        rows: List of flat dicts ready for insert
        chunk_size: Number of rows per upsert batch (default 200)

    Returns:
        Total number of rows upserted
    """
    if not rows:
        return 0

    client = get_supabase_client()
    total = 0
    num_chunks = (len(rows) + chunk_size - 1) // chunk_size

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        try:
            client.table("sp_sqp_data").upsert(
                chunk,
                on_conflict="marketplace_id,child_asin,search_query,period_start,period_end,period_type"
            ).execute()
            total += len(chunk)
            if num_chunks > 1:
                print(f"    [upsert chunk {chunk_num}/{num_chunks}: {len(chunk)} rows OK]", flush=True)
        except Exception as e:
            print(f"    [upsert chunk {chunk_num}/{num_chunks}: FAILED - {str(e)[:200]}]", flush=True)
            raise

    return total


def upsert_scp_data(rows: List[Dict], chunk_size: int = 200) -> int:
    """
    Batch upsert SCP data rows into sp_scp_data.

    Uses small chunks (200 rows) to avoid Cloudflare/Supabase POST body size
    limits. SCP rows have ~30 columns so 200 rows is safe.

    Args:
        rows: List of flat dicts ready for insert
        chunk_size: Number of rows per upsert batch (default 200)

    Returns:
        Total number of rows upserted
    """
    if not rows:
        return 0

    client = get_supabase_client()
    total = 0
    num_chunks = (len(rows) + chunk_size - 1) // chunk_size

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        try:
            client.table("sp_scp_data").upsert(
                chunk,
                on_conflict="marketplace_id,child_asin,period_start,period_end,period_type"
            ).execute()
            total += len(chunk)
            if num_chunks > 1:
                print(f"    [upsert chunk {chunk_num}/{num_chunks}: {len(chunk)} rows OK]", flush=True)
        except Exception as e:
            print(f"    [upsert chunk {chunk_num}/{num_chunks}: FAILED - {str(e)[:200]}]", flush=True)
            raise

    return total


def create_sqp_pull_record(
    marketplace_code: str,
    report_type: str,
    period_start: date,
    period_end: date,
    period_type: str,
    total_batches: int = 0,
    total_asins: int = 0
) -> str:
    """
    Create or update an sp_sqp_pulls tracking record.
    Uses upsert for idempotency.

    Returns:
        Pull record ID (UUID string)
    """
    client = get_supabase_client()

    result = client.table("sp_sqp_pulls").upsert({
        "pull_date": date.today().isoformat(),
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "report_type": report_type,
        "period_type": period_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "status": "processing",
        "started_at": datetime.utcnow().isoformat(),
        "total_batches": total_batches,
        "completed_batches": 0,
        "failed_batches": 0,
        "batch_status": {},
        "total_asins_requested": total_asins,
        "total_asins_returned": 0,
        "total_rows": 0,
        "total_queries": 0,
        "error_message": None,
        "error_count": 0,
        "completed_at": None,
        "processing_time_ms": None
    }, on_conflict="marketplace_id,report_type,period_start,period_end,period_type").execute()

    return result.data[0]["id"]


def update_sqp_pull_status(
    pull_id: str,
    status: str = None,
    batch_status: Dict = None,
    completed_batches: int = None,
    failed_batches: int = None,
    total_asins_returned: int = None,
    total_rows: int = None,
    total_queries: int = None,
    error_message: str = None,
    error_count: int = None,
    processing_time_ms: int = None
):
    """Update an sp_sqp_pulls record."""
    client = get_supabase_client()

    update_data = {"updated_at": datetime.utcnow().isoformat()}

    if status is not None:
        update_data["status"] = status
    if batch_status is not None:
        update_data["batch_status"] = batch_status
    if completed_batches is not None:
        update_data["completed_batches"] = completed_batches
    if failed_batches is not None:
        update_data["failed_batches"] = failed_batches
    if total_asins_returned is not None:
        update_data["total_asins_returned"] = total_asins_returned
    if total_rows is not None:
        update_data["total_rows"] = total_rows
    if total_queries is not None:
        update_data["total_queries"] = total_queries
    if error_message is not None:
        update_data["error_message"] = error_message
    if error_count is not None:
        update_data["error_count"] = error_count
    if processing_time_ms is not None:
        update_data["processing_time_ms"] = processing_time_ms
    if status in ["completed", "failed"]:
        update_data["completed_at"] = datetime.utcnow().isoformat()

    client.table("sp_sqp_pulls").update(update_data).eq("id", pull_id).execute()


def get_existing_sqp_pull(
    marketplace_code: str,
    report_type: str,
    period_start: date,
    period_end: date,
    period_type: str
) -> Optional[Dict]:
    """
    Check if a pull already exists for this marketplace/report/period.

    Returns:
        Pull record if exists, None otherwise
    """
    client = get_supabase_client()

    result = client.table("sp_sqp_pulls").select("*").eq(
        "marketplace_id", MARKETPLACE_UUIDS[marketplace_code]
    ).eq(
        "report_type", report_type
    ).eq(
        "period_start", period_start.isoformat()
    ).eq(
        "period_end", period_end.isoformat()
    ).eq(
        "period_type", period_type
    ).execute()

    if result.data:
        return result.data[0]
    return None


def record_asin_error(
    marketplace_code: str,
    child_asin: str,
    error_type: str = "UNKNOWN",
    error_message: str = None
):
    """
    Record an ASIN that failed during SQP/SCP pull.
    Auto-suppresses after 3 consecutive failures.
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    # Check if already exists
    existing = client.table("sp_sqp_asin_errors").select("*").eq(
        "marketplace_id", marketplace_id
    ).eq(
        "child_asin", child_asin
    ).execute()

    if existing.data:
        record = existing.data[0]
        new_count = record["occurrence_count"] + 1
        suppressed = new_count >= 3

        client.table("sp_sqp_asin_errors").update({
            "error_type": error_type,
            "error_message": error_message,
            "last_seen_at": datetime.utcnow().isoformat(),
            "occurrence_count": new_count,
            "suppressed": suppressed
        }).eq("id", record["id"]).execute()
    else:
        client.table("sp_sqp_asin_errors").insert({
            "marketplace_id": marketplace_id,
            "child_asin": child_asin,
            "error_type": error_type,
            "error_message": error_message,
            "occurrence_count": 1,
            "suppressed": False
        }).execute()


def get_suppressed_asins(marketplace_code: str) -> List[str]:
    """Get list of suppressed ASINs for a marketplace."""
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    result = client.table("sp_sqp_asin_errors").select("child_asin").eq(
        "marketplace_id", marketplace_id
    ).eq(
        "suppressed", True
    ).execute()

    return [r["child_asin"] for r in result.data]


def get_active_asins_for_sqp(marketplace_code: str, lookback_days: int = 60) -> List[str]:
    """
    Get all distinct child ASINs for a marketplace from recent sales data,
    excluding suppressed ASINs.

    Args:
        marketplace_code: e.g., 'USA'
        lookback_days: How many days back to look for active ASINs

    Returns:
        Sorted list of active ASIN strings
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]
    cutoff = (date.today() - __import__('datetime').timedelta(days=lookback_days)).isoformat()

    result = client.table("sp_daily_asin_data").select("child_asin").eq(
        "marketplace_id", marketplace_id
    ).gte("date", cutoff).execute()

    all_asins = list(set(r["child_asin"] for r in result.data if r.get("child_asin")))

    # Remove suppressed ASINs
    suppressed = get_suppressed_asins(marketplace_code)
    suppressed_set = set(suppressed)
    active_asins = [a for a in all_asins if a not in suppressed_set]

    return sorted(active_asins)


# =============================================================================
# Financial Report Functions (Settlement, Reimbursements, FBA Fee Estimates)
# =============================================================================

def create_financial_pull_record(
    marketplace_code: str,
    report_type: str,
    pull_date: date,
    import_id: str = None,
    settlement_id: str = None,
    report_id: str = None,
    report_document_id: str = None,
    date_range_start: date = None,
    date_range_end: date = None
) -> str:
    """
    Create or update an sp_financial_pulls tracking record.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_type: Report type (e.g., 'GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2')
        pull_date: Date of the pull
        import_id: Data import tracking ID
        settlement_id: Settlement ID (for settlement reports)
        report_id: Amazon report ID
        report_document_id: Amazon report document ID
        date_range_start: Start of data range
        date_range_end: End of data range

    Returns:
        Pull record ID (UUID string)
    """
    client = get_supabase_client()

    data = {
        "pull_date": pull_date.isoformat(),
        "marketplace_id": MARKETPLACE_UUIDS[marketplace_code],
        "report_type": report_type,
        "status": "pending",
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "error_message": None,
        "row_count": None
    }

    if import_id:
        data["import_id"] = import_id
    if settlement_id:
        data["settlement_id"] = settlement_id
    if report_id:
        data["report_id"] = report_id
    if report_document_id:
        data["report_document_id"] = report_document_id
    if date_range_start:
        data["date_range_start"] = date_range_start.isoformat()
    if date_range_end:
        data["date_range_end"] = date_range_end.isoformat()

    result = client.table("sp_financial_pulls").insert(data).execute()

    return result.data[0]["id"]


def update_financial_pull_status(
    pull_id: str,
    status: str,
    row_count: int = None,
    error_message: str = None,
    processing_time_ms: int = None,
    report_id: str = None,
    report_document_id: str = None
):
    """Update an sp_financial_pulls record."""
    client = get_supabase_client()

    update_data = {"status": status}
    if row_count is not None:
        update_data["row_count"] = row_count
    if error_message:
        update_data["error_message"] = error_message
    if processing_time_ms is not None:
        update_data["processing_time_ms"] = processing_time_ms
    if report_id:
        update_data["report_id"] = report_id
    if report_document_id:
        update_data["report_document_id"] = report_document_id
    if status in ["completed", "failed"]:
        update_data["completed_at"] = datetime.utcnow().isoformat()

    client.table("sp_financial_pulls").update(update_data).eq("id", pull_id).execute()


def get_processed_settlement_ids(marketplace_code: str) -> List[str]:
    """
    Get list of settlement IDs already processed for a marketplace.

    Used to skip already-downloaded settlement reports during backfill.

    Returns:
        List of settlement_id strings
    """
    client = get_supabase_client()
    marketplace_id = MARKETPLACE_UUIDS[marketplace_code]

    result = client.table("sp_financial_pulls") \
        .select("settlement_id") \
        .eq("marketplace_id", marketplace_id) \
        .eq("report_type", "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2") \
        .eq("status", "completed") \
        .not_.is_("settlement_id", "null") \
        .execute()

    return [r["settlement_id"] for r in result.data]


def upsert_settlement_transactions(
    transactions: List[Dict],
    chunk_size: int = 500
) -> int:
    """
    Batch upsert settlement transaction rows.

    Uses (marketplace_id, settlement_id, row_hash) for dedup.

    Args:
        transactions: List of transaction dicts from parse_settlement_rows()
        chunk_size: Number of rows per upsert batch

    Returns:
        Total number of rows upserted
    """
    if not transactions:
        return 0

    # Deduplicate by (marketplace_id, settlement_id, row_hash) within the batch
    # Amazon settlement reports can have duplicate rows with identical field values
    seen = set()
    unique_transactions = []
    for tx in transactions:
        key = (tx["marketplace_id"], tx["settlement_id"], tx["row_hash"])
        if key not in seen:
            seen.add(key)
            unique_transactions.append(tx)

    if len(unique_transactions) < len(transactions):
        print(f"  Deduplicated {len(transactions) - len(unique_transactions)} duplicate rows within batch")

    client = get_supabase_client()
    total = 0

    for i in range(0, len(unique_transactions), chunk_size):
        chunk = unique_transactions[i:i + chunk_size]
        client.table("sp_settlement_transactions").upsert(
            chunk,
            on_conflict="marketplace_id,settlement_id,row_hash"
        ).execute()
        total += len(chunk)

    return total


def upsert_settlement_summary(summary: Dict) -> bool:
    """
    Upsert a settlement summary record.

    Uses (marketplace_id, settlement_id) for dedup.

    Args:
        summary: Summary dict from parse_settlement_rows()

    Returns:
        True if successful
    """
    if not summary:
        return False

    client = get_supabase_client()

    client.table("sp_settlement_summaries").upsert(
        summary,
        on_conflict="marketplace_id,settlement_id"
    ).execute()

    return True


def upsert_reimbursements(
    rows: List[Dict],
    chunk_size: int = 500
) -> int:
    """
    Batch upsert reimbursement rows.

    Uses (marketplace_id, reimbursement_id) for dedup.

    Args:
        rows: List of reimbursement dicts
        chunk_size: Number of rows per upsert batch

    Returns:
        Total number of rows upserted
    """
    if not rows:
        return 0

    # Deduplicate by (marketplace_id, reimbursement_id) within the batch
    seen = set()
    unique_rows = []
    for r in rows:
        key = (r.get("marketplace_id"), r.get("reimbursement_id"))
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)

    if len(unique_rows) < len(rows):
        print(f"  Deduplicated {len(rows) - len(unique_rows)} duplicate reimbursement rows within batch")

    client = get_supabase_client()
    total = 0

    for i in range(0, len(unique_rows), chunk_size):
        chunk = unique_rows[i:i + chunk_size]
        client.table("sp_reimbursements").upsert(
            chunk,
            on_conflict="marketplace_id,reimbursement_id"
        ).execute()
        total += len(chunk)

    return total


def upsert_fba_fee_estimates(
    rows: List[Dict],
    chunk_size: int = 500
) -> int:
    """
    Batch upsert FBA fee estimate rows.

    Uses (marketplace_id, sku) for dedup — always latest estimate.

    Args:
        rows: List of fee estimate dicts
        chunk_size: Number of rows per upsert batch

    Returns:
        Total number of rows upserted
    """
    if not rows:
        return 0

    client = get_supabase_client()
    total = 0

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        client.table("sp_fba_fee_estimates").upsert(
            chunk,
            on_conflict="marketplace_id,sku"
        ).execute()
        total += len(chunk)

    return total
