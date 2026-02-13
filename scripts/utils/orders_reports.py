"""
SP-API Orders Reports Module
Handles near-real-time order data via GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL

This report provides order-level data with ~30 minute delay (vs 24-72hrs for Sales & Traffic).
Used to populate same-day sales data before the full S&T report is available.

Key differences from Sales & Traffic:
- TSV format (not JSON)
- Order-level rows (not ASIN-level aggregates)
- No traffic metrics (sessions, page views, buy box %)
- Much faster availability (~30 min vs 24-72 hrs)

TSV columns used:
- asin: Product ASIN
- quantity: Units in line item
- item-price: Total price for line item (quantity * unit price)
- amazon-order-id: Unique order ID (for counting distinct orders)
- currency: Currency code (USD, CAD, MXN)
- order-status: Order status (Shipped, Pending, Cancelled, etc.)
- purchase-date: When order was placed

Excluded statuses: Cancelled only (Pending included — matches S&T behavior)
"""

import csv
import gzip
import io
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Regional endpoints
ENDPOINTS = {
    "NA": "sellingpartnerapi-na.amazon.com",
    "EU": "sellingpartnerapi-eu.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com",
    "UAE": "sellingpartnerapi-eu.amazon.com"   # UAE uses EU endpoint, different token
}

# Amazon Marketplace IDs
MARKETPLACE_IDS = {
    "USA": {"id": "ATVPDKIKX0DER", "region": "NA"},
    "CA": {"id": "A2EUQ1WTGCTBG2", "region": "NA"},
    "MX": {"id": "A1AM78C64UM0Y8", "region": "NA"},
    "BR": {"id": "A2Q3Y263D00KWC", "region": "NA"},
    "UK": {"id": "A1F83G8C2ARO7P", "region": "EU"},
    "DE": {"id": "A1PA6795UKMFR9", "region": "EU"},
    "FR": {"id": "A13V1IB3VIYZZH", "region": "EU"},
    "IT": {"id": "APJ6JRA9NG5V4", "region": "EU"},
    "ES": {"id": "A1RKKUPIHCS9HS", "region": "EU"},
    "UAE": {"id": "A2VIGQ35RCS4UG", "region": "UAE"},
    "AU": {"id": "A39IBJ37TRP1C6", "region": "FE"},
    "JP": {"id": "A1VC38T7YXB528", "region": "FE"}
}

# Marketplace timezone mapping — used to convert local dates to UTC boundaries
# for the orders report API (which expects UTC timestamps)
MARKETPLACE_TIMEZONES = {
    "USA": "America/Los_Angeles",
    "CA": "America/Los_Angeles",
    "MX": "America/Los_Angeles",
    "BR": "America/Sao_Paulo",
    "UK": "Europe/London",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "UAE": "Asia/Dubai",
    "AU": "Australia/Sydney",
    "JP": "Asia/Tokyo",
}

# Order statuses to exclude from aggregation
# Only exclude Cancelled — Pending orders are real orders that haven't shipped yet.
# Amazon's Sales & Traffic report counts them immediately, so we should too.
# Cancellation rate is typically <2%, and S&T overwrites this data within 24hrs anyway.
EXCLUDED_STATUSES = {"Cancelled"}

REPORT_TYPE = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"

# Sales channel mapping for filtering orders by marketplace
# The orders report returns ALL orders for the region (especially EU unified account),
# so we must filter by sales-channel to get only the requested marketplace's orders.
SALES_CHANNEL_MAP = {
    "USA": "Amazon.com",
    "CA": "Amazon.ca",
    "MX": "Amazon.com.mx",
    "UK": "Amazon.co.uk",
    "DE": "Amazon.de",
    "FR": "Amazon.fr",
    "IT": "Amazon.it",
    "ES": "Amazon.es",
    "UAE": "Amazon.ae",
    "AU": "Amazon.com.au",
    "JP": "Amazon.co.jp",
}


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def create_orders_report(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    client=None,
    access_token: str = None
) -> str:
    """
    Create an orders report for a single day.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: Date to pull orders for
        region: API region
        client: SPAPIClient instance (preferred)
        access_token: Direct access token (fallback)

    Returns:
        Report ID string
    """
    import requests as req_lib

    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    # Convert marketplace local date to UTC boundaries
    # e.g., USA Feb 11 (PST) = Feb 11 08:00:00Z to Feb 12 07:59:59Z
    tz_name = MARKETPLACE_TIMEZONES.get(marketplace_code.upper(), "UTC")
    tz = ZoneInfo(tz_name)
    local_start = datetime(report_date.year, report_date.month, report_date.day, 0, 0, 0, tzinfo=tz)
    local_end = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=tz)
    utc_start = local_start.astimezone(ZoneInfo("UTC"))
    utc_end = local_end.astimezone(ZoneInfo("UTC"))

    start_time = utc_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_time = utc_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"  📅 Date range: {report_date} ({tz_name}) → {start_time} to {end_time}")

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    payload = {
        "reportType": REPORT_TYPE,
        "marketplaceIds": [amazon_marketplace_id],
        "dataStartTime": start_time,
        "dataEndTime": end_time
    }

    headers = {"Content-Type": "application/json"}

    if client is not None:
        response = client.post(
            url,
            json=payload,
            headers=headers,
            api_type="reports_create"
        )
    else:
        headers["x-amz-access-token"] = access_token
        response = req_lib.post(url, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    report_id = data["reportId"]

    logger.info(f"Created orders report {report_id} for {marketplace_code} on {report_date}")
    print(f"✓ Created orders report {report_id} for {marketplace_code} on {report_date}")

    return report_id


def poll_report_status(
    report_id: str,
    region: str = "NA",
    max_wait_seconds: int = 600,
    poll_interval: int = 15,
    client=None,
    access_token: str = None
) -> Dict[str, Any]:
    """
    Poll for orders report completion.

    Orders reports can take longer than S&T reports (up to 10 minutes),
    so default max_wait is 600 seconds.
    """
    import requests as req_lib

    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/reports/{report_id}"

    start_time = time.time()

    while True:
        if client is not None:
            response = client.get(url, api_type="reports_get")
        else:
            response = req_lib.get(
                url,
                headers={"x-amz-access-token": access_token}
            )
            response.raise_for_status()

        data = response.json()
        status = data.get("processingStatus")

        if status == "DONE":
            logger.info(f"Orders report {report_id} completed")
            print(f"✓ Orders report {report_id} completed")
            return {
                "reportDocumentId": data["reportDocumentId"],
                "processingStatus": status
            }

        if status in ["CANCELLED", "FATAL"]:
            raise RuntimeError(
                f"Orders report failed with status: {status}. "
                f"Type: {data.get('reportType', '')}. Response: {data}"
            )

        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise TimeoutError(
                f"Orders report {report_id} did not complete within {max_wait_seconds}s"
            )

        print(f"  Orders report status: {status}, waiting {poll_interval}s...")
        time.sleep(poll_interval)


def download_orders_report(
    report_document_id: str,
    region: str = "NA",
    client=None,
    access_token: str = None
) -> List[Dict[str, str]]:
    """
    Download and parse orders report (TSV format).

    Returns:
        List of row dictionaries (one per order line item)
    """
    import requests as req_lib

    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/documents/{report_document_id}"

    if client is not None:
        response = client.get(url, api_type="reports_get")
    else:
        response = req_lib.get(
            url,
            headers={"x-amz-access-token": access_token}
        )
        response.raise_for_status()

    doc_info = response.json()
    download_url = doc_info["url"]
    compression = doc_info.get("compressionAlgorithm")

    # Download the report file
    if client is not None:
        report_response = client.session.get(download_url, timeout=client.timeout)
        report_response.raise_for_status()
    else:
        report_response = req_lib.get(download_url)
        report_response.raise_for_status()

    # Decompress if needed
    content = report_response.content
    if compression == "GZIP":
        content = gzip.decompress(content)

    # Parse TSV
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1252")

    reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    rows = list(reader)

    print(f"✓ Downloaded orders report with {len(rows)} line items")

    return rows


def aggregate_orders_by_asin(
    rows: List[Dict[str, str]],
    report_date: date = None,
    marketplace_code: str = None
) -> List[Dict[str, Any]]:
    """
    Aggregate order line items by ASIN.

    Groups by ASIN and counts:
    - COUNT line items → units_ordered (each row = 1 unit, matching Amazon's S&T definition)
    - item-price → ordered_product_sales (total for line item, not per-unit)
    - COUNT DISTINCT amazon-order-id → total_order_items

    Excludes Cancelled orders only (Pending are included — they're real orders
    that Amazon's S&T also counts immediately).
    Filters by sales-channel when marketplace_code is provided (critical for EU
    where the unified account returns orders from all EU marketplaces).

    Args:
        rows: Raw TSV rows from download_orders_report()
        report_date: Date for the data (optional, for logging)
        marketplace_code: Marketplace code to filter by (e.g., 'UK', 'DE')

    Returns:
        List of aggregated dicts ready for upsert
    """
    # Filter by sales-channel if marketplace_code provided
    expected_channel = SALES_CHANNEL_MAP.get(marketplace_code.upper()) if marketplace_code else None

    # Aggregate by ASIN
    asin_data = defaultdict(lambda: {
        "units_ordered": 0,
        "ordered_product_sales": 0.0,
        "order_ids": set(),
        "currency_code": None
    })

    excluded_count = 0
    channel_filtered_count = 0

    for row in rows:
        # Filter by sales-channel (critical for EU unified account)
        if expected_channel:
            row_channel = row.get("sales-channel", "").strip()
            if row_channel and row_channel != expected_channel:
                channel_filtered_count += 1
                continue

        # Get order status
        order_status = row.get("order-status", "").strip()
        if order_status in EXCLUDED_STATUSES:
            excluded_count += 1
            continue

        asin = row.get("asin", "").strip()
        if not asin:
            continue

        # Parse item-price (total for this line item)
        try:
            item_price = float(row.get("item-price", "0").strip())
        except (ValueError, TypeError):
            item_price = 0.0

        # Get order ID for distinct count
        order_id = row.get("amazon-order-id", "").strip()

        # Get currency
        currency = row.get("currency", "").strip()

        # Aggregate
        # Each line item = 1 unit ordered (matches Amazon S&T / Seller Central definition)
        # NOT summing quantity — quantity > 1 means multi-pack, but Amazon counts it as 1 unit
        asin_data[asin]["units_ordered"] += 1
        asin_data[asin]["ordered_product_sales"] += item_price
        if order_id:
            asin_data[asin]["order_ids"].add(order_id)
        if currency and not asin_data[asin]["currency_code"]:
            asin_data[asin]["currency_code"] = currency

    if channel_filtered_count > 0:
        print(f"  🔍 Filtered out {channel_filtered_count} rows from other marketplaces (kept {expected_channel})")
    if excluded_count > 0:
        print(f"  ⏭️  Excluded {excluded_count} Cancelled order lines")

    # Convert to list of dicts
    result = []
    for asin, data in asin_data.items():
        result.append({
            "child_asin": asin,
            "units_ordered": data["units_ordered"],
            "ordered_product_sales": round(data["ordered_product_sales"], 2),
            "total_order_items": len(data["order_ids"]),
            "currency_code": data["currency_code"] or "USD"
        })

    date_str = report_date.isoformat() if report_date else "unknown"
    print(f"  📊 Aggregated {len(rows)} line items → {len(result)} ASINs for {date_str}")
    print(f"     Total units: {sum(r['units_ordered'] for r in result)}")
    print(f"     Total sales: ${sum(r['ordered_product_sales'] for r in result):,.2f}")

    return result


def pull_orders_report(
    marketplace_code: str,
    report_date: date,
    region: str = "NA",
    client=None,
    access_token: str = None
) -> List[Dict[str, Any]]:
    """
    High-level function to create, poll, download, and aggregate an orders report.

    Args:
        marketplace_code: Marketplace code (e.g., 'USA')
        report_date: Date to pull orders for
        region: API region
        client: SPAPIClient instance (preferred)
        access_token: Direct access token (fallback)

    Returns:
        List of aggregated ASIN dicts ready for upsert
    """
    # Create report
    report_id = create_orders_report(
        marketplace_code=marketplace_code,
        report_date=report_date,
        region=region,
        client=client,
        access_token=access_token
    )

    # Poll until complete
    result = poll_report_status(
        report_id=report_id,
        region=region,
        client=client,
        access_token=access_token
    )

    # Download and parse TSV
    raw_rows = download_orders_report(
        report_document_id=result["reportDocumentId"],
        region=region,
        client=client,
        access_token=access_token
    )

    # Aggregate by ASIN (filtered by marketplace sales-channel)
    aggregated = aggregate_orders_by_asin(raw_rows, report_date, marketplace_code)

    return aggregated
