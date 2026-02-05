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
            "import_id": import_id
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
