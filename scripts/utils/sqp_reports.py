"""
SP-API Search Query Performance (SQP) & Search Catalog Performance (SCP) Reports Module

Handles report creation, polling, downloading, and parsing for Brand Analytics
search performance reports.

Key differences from Sales & Traffic reports:
- ASIN parameter: space-separated, 200-character limit (~18 ASINs per batch)
- Time periods: WEEK (Sun-Sat), MONTH, QUARTER only - NO daily granularity
- Strict date alignment required (period boundaries)
- ~48hr data availability delay
- Brand-owned ASINs only
- JSON output, same create/poll/download workflow

Updated to use SPAPIClient for automatic retry and rate limiting.
"""

import os
import gzip
import json
import time
import logging
import calendar
from typing import Dict, List, Optional, Any, Tuple
from datetime import date, datetime, timedelta

try:
    from utils.api_client import SPAPIClient
except ImportError:
    SPAPIClient = None

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
    "UK": {"id": "A1F83G8C2ARO7P", "region": "EU"},
    "DE": {"id": "A1PA6795UKMFR9", "region": "EU"},
    "FR": {"id": "A13V1IB3VIYZZH", "region": "EU"},
    "IT": {"id": "APJ6JRA9NG5V4", "region": "EU"},
    "ES": {"id": "A1RKKUPIHCS9HS", "region": "EU"},
    "UAE": {"id": "A2VIGQ35RCS4UG", "region": "UAE"},
    "AU": {"id": "A39IBJ37TRP1C6", "region": "FE"},
    "JP": {"id": "A1VC38T7YXB528", "region": "FE"}
}

# Report type identifiers
SQP_REPORT_TYPE = "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"
SCP_REPORT_TYPE = "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT"


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


# =============================================================================
# Period Boundary Calculations
# =============================================================================

def get_week_boundaries(target_date: date) -> Tuple[date, date]:
    """
    Get the Amazon week boundaries (Sunday-Saturday) containing the given date.

    Args:
        target_date: Any date

    Returns:
        Tuple of (sunday_start, saturday_end)
    """
    # weekday(): Monday=0, Sunday=6
    # We need Sunday=0, so adjust
    days_since_sunday = (target_date.weekday() + 1) % 7
    sunday = target_date - timedelta(days=days_since_sunday)
    saturday = sunday + timedelta(days=6)
    return sunday, saturday


def get_month_boundaries(target_date: date) -> Tuple[date, date]:
    """
    Get the month boundaries for the given date.

    Args:
        target_date: Any date

    Returns:
        Tuple of (first_day, last_day)
    """
    first_day = target_date.replace(day=1)
    _, last_day_num = calendar.monthrange(target_date.year, target_date.month)
    last_day = target_date.replace(day=last_day_num)
    return first_day, last_day


def get_quarter_boundaries(target_date: date) -> Tuple[date, date]:
    """
    Get the quarter boundaries for the given date.

    Returns:
        Tuple of (first_day_of_quarter, last_day_of_quarter)
    """
    quarter = (target_date.month - 1) // 3
    first_month = quarter * 3 + 1
    last_month = first_month + 2
    first_day = date(target_date.year, first_month, 1)
    _, last_day_num = calendar.monthrange(target_date.year, last_month)
    last_day = date(target_date.year, last_month, last_day_num)
    return first_day, last_day


def get_latest_available_week(delay_hours: int = 48) -> Tuple[date, date]:
    """
    Get the most recent complete week that should have data available.

    Amazon SQP data has ~48-hour delay after the period ends.

    Returns:
        Tuple of (sunday_start, saturday_end) for the latest available week
    """
    now = datetime.utcnow()
    # Subtract delay to find the cutoff
    cutoff = now - timedelta(hours=delay_hours)
    cutoff_date = cutoff.date()

    # Get the week containing the cutoff date
    sunday, saturday = get_week_boundaries(cutoff_date)

    # If cutoff is before the end of this week, use the previous week
    if cutoff_date < saturday:
        sunday = sunday - timedelta(days=7)
        saturday = saturday - timedelta(days=7)

    return sunday, saturday


def get_latest_available_month(delay_hours: int = 48) -> Tuple[date, date]:
    """
    Get the most recent complete month that should have data available.

    Returns:
        Tuple of (first_day, last_day) for the latest available month
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=delay_hours)
    cutoff_date = cutoff.date()

    # Get the previous month (current month isn't complete yet)
    first_of_current = cutoff_date.replace(day=1)
    last_of_prev = first_of_current - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)

    return first_of_prev, last_of_prev


def enumerate_weekly_periods(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    """
    Enumerate all Amazon weekly periods (Sunday-Saturday) between start and end dates.
    Only includes complete weeks.

    Args:
        start_date: Earliest date to include
        end_date: Latest date to include

    Returns:
        List of (sunday, saturday) tuples, newest first
    """
    periods = []
    # Start from the first Sunday on or after start_date
    sunday, saturday = get_week_boundaries(start_date)
    if sunday < start_date:
        sunday += timedelta(days=7)
        saturday += timedelta(days=7)

    while saturday <= end_date:
        periods.append((sunday, saturday))
        sunday += timedelta(days=7)
        saturday += timedelta(days=7)

    # Reverse so newest periods are first
    periods.reverse()
    return periods


def enumerate_monthly_periods(start_date: date, end_date: date) -> List[Tuple[date, date]]:
    """
    Enumerate all monthly periods between start and end dates.
    Only includes complete months.

    Returns:
        List of (first_day, last_day) tuples, newest first
    """
    periods = []
    current = start_date.replace(day=1)

    while current <= end_date:
        first_day, last_day = get_month_boundaries(current)
        if last_day <= end_date:
            periods.append((first_day, last_day))
        # Move to next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    periods.reverse()
    return periods


# =============================================================================
# ASIN Batching
# =============================================================================

def batch_asins(asin_list: List[str], char_limit: int = 200) -> List[List[str]]:
    """
    Split ASIN list into batches that fit within the 200-character limit.

    Amazon SQP/SCP reports accept ASINs as a space-separated string with a
    200-character limit. Standard ASINs are 10 characters.
    "ASIN1 ASIN2" = 10 + 1 + 10 = 21 chars for 2 ASINs.
    Max ~18 ASINs per batch (18*10 + 17 spaces = 197 chars).

    Args:
        asin_list: List of ASIN strings
        char_limit: Maximum character length for space-joined ASINs

    Returns:
        List of ASIN batches
    """
    if not asin_list:
        return []

    batches = []
    current_batch = []
    current_length = 0

    for asin in asin_list:
        # Calculate length if we add this ASIN
        additional = len(asin) + (1 if current_batch else 0)  # +1 for space separator

        if current_length + additional > char_limit:
            # Start new batch
            if current_batch:
                batches.append(current_batch)
            current_batch = [asin]
            current_length = len(asin)
        else:
            current_batch.append(asin)
            current_length += additional

    # Don't forget the last batch
    if current_batch:
        batches.append(current_batch)

    return batches


# =============================================================================
# Report Creation
# =============================================================================

def create_sqp_report(
    client: "SPAPIClient",
    marketplace_code: str,
    asins: List[str],
    period_start: date,
    period_end: date,
    period_type: str = "WEEK",
    region: str = "NA"
) -> str:
    """
    Create a Search Query Performance report request.

    Args:
        client: SPAPIClient instance
        marketplace_code: Marketplace code (e.g., 'USA')
        asins: List of ASINs (must fit within 200-char limit when space-joined)
        period_start: Start date of the period
        period_end: End date of the period
        period_type: 'WEEK', 'MONTH', or 'QUARTER'
        region: API region

    Returns:
        Report ID string
    """
    return _create_brand_analytics_report(
        client=client,
        report_type=SQP_REPORT_TYPE,
        marketplace_code=marketplace_code,
        asins=asins,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        region=region
    )


def create_scp_report(
    client: "SPAPIClient",
    marketplace_code: str,
    asins: List[str],
    period_start: date,
    period_end: date,
    period_type: str = "WEEK",
    region: str = "NA"
) -> str:
    """
    Create a Search Catalog Performance report request.

    Args:
        client: SPAPIClient instance
        marketplace_code: Marketplace code (e.g., 'USA')
        asins: List of ASINs
        period_start: Start date of the period
        period_end: End date of the period
        period_type: 'WEEK', 'MONTH', or 'QUARTER'
        region: API region

    Returns:
        Report ID string
    """
    return _create_brand_analytics_report(
        client=client,
        report_type=SCP_REPORT_TYPE,
        marketplace_code=marketplace_code,
        asins=asins,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        region=region
    )


def _create_brand_analytics_report(
    client: "SPAPIClient",
    report_type: str,
    marketplace_code: str,
    asins: List[str],
    period_start: date,
    period_end: date,
    period_type: str,
    region: str
) -> str:
    """Internal helper to create SQP or SCP report requests."""
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    # Space-separated ASINs
    asin_string = " ".join(asins)
    if len(asin_string) > 200:
        raise ValueError(f"ASIN string exceeds 200-char limit: {len(asin_string)} chars ({len(asins)} ASINs)")

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    # SQP uses "asin" (singular, required), SCP uses "asins" (plural, optional)
    is_sqp = "SEARCH_QUERY" in report_type
    asin_key = "asin" if is_sqp else "asins"

    payload = {
        "reportType": report_type,
        "marketplaceIds": [amazon_marketplace_id],
        "dataStartTime": period_start.strftime("%Y-%m-%dT00:00:00Z"),
        "dataEndTime": period_end.strftime("%Y-%m-%dT00:00:00Z"),
        "reportOptions": {
            "reportPeriod": period_type,
            asin_key: asin_string
        }
    }

    headers = {"Content-Type": "application/json"}

    response = client.post(
        url,
        json=payload,
        headers=headers,
        api_type="reports_create"
    )

    data = response.json()
    report_id = data["reportId"]

    report_name = "SQP" if "SEARCH_QUERY" in report_type else "SCP"
    logger.info(f"Created {report_name} report {report_id} for {marketplace_code} ({len(asins)} ASINs, {period_type} {period_start})")
    print(f"  Created {report_name} report {report_id} ({len(asins)} ASINs)")

    return report_id


# =============================================================================
# Report Polling
# =============================================================================

def poll_report_status(
    client: "SPAPIClient",
    report_id: str,
    region: str = "NA",
    max_wait_seconds: int = 300,
    poll_interval: int = 10
) -> Dict[str, Any]:
    """
    Poll for report completion.

    Args:
        client: SPAPIClient instance
        report_id: The report ID to poll
        region: API region
        max_wait_seconds: Maximum time to wait
        poll_interval: Seconds between polls

    Returns:
        Dict with 'reportDocumentId' and 'processingStatus'

    Raises:
        RuntimeError: If report fails (CANCELLED/FATAL)
        TimeoutError: If report doesn't complete in time
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/reports/{report_id}"

    start_time = time.time()

    while True:
        response = client.get(url, api_type="reports_get")
        data = response.json()
        status = data.get("processingStatus")

        if status == "DONE":
            logger.info(f"Report {report_id} completed")
            return {
                "reportDocumentId": data["reportDocumentId"],
                "processingStatus": status
            }

        if status in ["CANCELLED", "FATAL"]:
            raise RuntimeError(f"Report {report_id} failed with status: {status}")

        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise TimeoutError(f"Report {report_id} did not complete within {max_wait_seconds}s")

        time.sleep(poll_interval)


# =============================================================================
# Report Download & Parsing
# =============================================================================

def download_report(
    client: "SPAPIClient",
    report_document_id: str,
    region: str = "NA"
) -> Dict[str, Any]:
    """
    Download and parse a completed report.

    Args:
        client: SPAPIClient instance
        report_document_id: The document ID from poll_report_status
        region: API region

    Returns:
        Parsed report data as dictionary
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/documents/{report_document_id}"

    response = client.get(url, api_type="reports_get")
    doc_info = response.json()

    download_url = doc_info["url"]
    compression = doc_info.get("compressionAlgorithm")

    # Download the actual report (S3 URL - no SP-API auth needed)
    report_response = client.session.get(download_url, timeout=client.timeout)
    report_response.raise_for_status()

    content = report_response.content
    if compression == "GZIP":
        content = gzip.decompress(content)

    report_data = json.loads(content.decode("utf-8"))
    return report_data


def _extract_currency(currency_amount: Optional[Dict]) -> Tuple[Optional[float], Optional[str]]:
    """Extract amount and currency code from a CurrencyAmount object."""
    if not currency_amount:
        return None, None
    return currency_amount.get("amount"), currency_amount.get("currencyCode")


def parse_sqp_response(
    report_data: Dict[str, Any],
    marketplace_id: str,
    period_start: date,
    period_end: date,
    period_type: str
) -> List[Dict]:
    """
    Parse SQP report JSON into flat database rows.

    SQP response structure (each dataByAsin item = 1 ASIN + 1 search query):
    {
      "dataByAsin": [
        {
          "asin": "B00...",
          "searchQueryData": {
            "searchQuery": "...",
            "searchQueryScore": 5,
            "searchQueryVolume": 12345
          },
          "impressionData": { "impressionCount": ..., "impressionShare": ..., ... },
          "clickData": { "clickCount": ..., "clickRate": ..., "clickShare": ..., ... },
          "cartAddData": { "cartAddCount": ..., "cartAddRate": ..., ... },
          "purchaseData": { "purchaseCount": ..., "purchaseRate": ..., ... }
        }
      ]
    }

    Args:
        report_data: Raw JSON from the SQP report
        marketplace_id: Supabase marketplace UUID
        period_start: Period start date
        period_end: Period end date
        period_type: 'WEEK', 'MONTH', or 'QUARTER'

    Returns:
        List of flat dictionaries ready for DB upsert
    """
    rows = []

    asin_data = report_data.get("dataByAsin", [])

    for item in asin_data:
        child_asin = item.get("asin") or item.get("childAsin")
        if not child_asin:
            continue

        # Search query data (dict, not list)
        sqd = item.get("searchQueryData") or {}

        search_query = sqd.get("searchQuery", "")
        if not search_query:
            continue

        # Nested metric sub-objects
        imp = item.get("impressionData") or {}
        click = item.get("clickData") or {}
        cart = item.get("cartAddData") or {}
        purchase = item.get("purchaseData") or {}

        # Extract median prices (CurrencyAmount objects)
        asin_click_price, asin_click_currency = _extract_currency(click.get("asinMedianClickPrice"))
        total_click_price, total_click_currency = _extract_currency(click.get("totalMedianClickPrice"))

        asin_cart_price, asin_cart_currency = _extract_currency(cart.get("asinMedianCartAddPrice"))
        total_cart_price, total_cart_currency = _extract_currency(cart.get("totalMedianCartAddPrice"))

        asin_purchase_price, asin_purchase_currency = _extract_currency(purchase.get("asinMedianPurchasePrice"))
        total_purchase_price, total_purchase_currency = _extract_currency(purchase.get("totalMedianPurchasePrice"))

        row = {
            "marketplace_id": marketplace_id,
            "child_asin": child_asin,
            "search_query": search_query,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "period_type": period_type,

            # Search query metrics
            "search_query_score": sqd.get("searchQueryScore"),
            "search_query_volume": sqd.get("searchQueryVolume"),

            # Impressions
            "total_query_impression_count": imp.get("totalQueryImpressionCount"),
            "asin_impression_count": imp.get("asinImpressionCount"),
            "asin_impression_share": imp.get("asinImpressionShare"),

            # Clicks
            "total_click_count": click.get("totalClickCount"),
            "total_click_rate": click.get("totalClickRate"),
            "asin_click_count": click.get("asinClickCount"),
            "asin_click_share": click.get("asinClickShare"),
            "asin_click_median_price": asin_click_price,
            "asin_click_median_price_currency": asin_click_currency,
            "total_click_median_price": total_click_price,
            "total_click_median_price_currency": total_click_currency,
            "total_same_day_shipping_click_count": click.get("totalSameDayShippingClickCount"),
            "total_one_day_shipping_click_count": click.get("totalOneDayShippingClickCount"),
            "total_two_day_shipping_click_count": click.get("totalTwoDayShippingClickCount"),

            # Cart Adds
            "total_cart_add_count": cart.get("totalCartAddCount"),
            "total_cart_add_rate": cart.get("totalCartAddRate"),
            "asin_cart_add_count": cart.get("asinCartAddCount"),
            "asin_cart_add_share": cart.get("asinCartAddShare"),
            "asin_cart_add_median_price": asin_cart_price,
            "asin_cart_add_median_price_currency": asin_cart_currency,
            "total_cart_add_median_price": total_cart_price,
            "total_cart_add_median_price_currency": total_cart_currency,
            "total_same_day_shipping_cart_add_count": cart.get("totalSameDayShippingCartAddCount"),
            "total_one_day_shipping_cart_add_count": cart.get("totalOneDayShippingCartAddCount"),
            "total_two_day_shipping_cart_add_count": cart.get("totalTwoDayShippingCartAddCount"),

            # Purchases
            "total_purchase_count": purchase.get("totalPurchaseCount"),
            "total_purchase_rate": purchase.get("totalPurchaseRate"),
            "asin_purchase_count": purchase.get("asinPurchaseCount"),
            "asin_purchase_share": purchase.get("asinPurchaseShare"),
            "asin_purchase_median_price": asin_purchase_price,
            "asin_purchase_median_price_currency": asin_purchase_currency,
            "total_purchase_median_price": total_purchase_price,
            "total_purchase_median_price_currency": total_purchase_currency,
            "total_same_day_shipping_purchase_count": purchase.get("totalSameDayShippingPurchaseCount"),
            "total_one_day_shipping_purchase_count": purchase.get("totalOneDayShippingPurchaseCount"),
            "total_two_day_shipping_purchase_count": purchase.get("totalTwoDayShippingPurchaseCount"),
        }
        rows.append(row)

    return rows


def parse_scp_response(
    report_data: Dict[str, Any],
    marketplace_id: str,
    period_start: date,
    period_end: date,
    period_type: str
) -> List[Dict]:
    """
    Parse SCP report JSON into flat database rows.

    SCP is per-ASIN aggregate (no search query dimension).

    Args:
        report_data: Raw JSON from the SCP report
        marketplace_id: Supabase marketplace UUID
        period_start: Period start date
        period_end: Period end date
        period_type: 'WEEK', 'MONTH', or 'QUARTER'

    Returns:
        List of flat dictionaries ready for DB upsert
    """
    rows = []

    # Navigate the report structure - SCP uses "dataByAsin"
    asin_data = report_data.get("dataByAsin", [])

    for item in asin_data:
        child_asin = item.get("asin") or item.get("childAsin")
        if not child_asin:
            continue

        # SCP nests data under category sub-objects
        imp = item.get("impressionData") or {}
        click = item.get("clickData") or {}
        cart = item.get("cartAddData") or {}
        purchase = item.get("purchaseData") or {}

        # Extract median prices (CurrencyAmount objects)
        imp_median_price, imp_median_currency = _extract_currency(imp.get("impressionMedianPrice"))
        click_median_price, click_median_currency = _extract_currency(click.get("clickedMedianPrice"))
        cart_median_price, cart_median_currency = _extract_currency(cart.get("cartAddMedianPrice"))
        purchase_median_price, purchase_median_currency = _extract_currency(purchase.get("purchaseMedianPrice"))

        # SCP-specific: search traffic sales & conversion
        sales_amount, sales_currency = _extract_currency(item.get("searchTrafficSales"))

        row = {
            "marketplace_id": marketplace_id,
            "child_asin": child_asin,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "period_type": period_type,

            # Impressions
            # SCP has no total/asin split - data is per-ASIN aggregate
            "asin_impression_count": imp.get("impressionCount"),
            "asin_click_median_price": imp_median_price,
            "asin_click_median_price_currency": imp_median_currency,

            # Clicks
            "asin_click_count": click.get("clickCount"),
            "total_click_rate": click.get("clickRate"),
            "total_click_median_price": click_median_price,
            "total_click_median_price_currency": click_median_currency,
            "total_same_day_shipping_click_count": click.get("sameDayShippingClickCount"),
            "total_one_day_shipping_click_count": click.get("oneDayShippingClickCount"),
            "total_two_day_shipping_click_count": click.get("twoDayShippingClickCount"),

            # Cart Adds
            "asin_cart_add_count": cart.get("cartAddCount"),
            "total_cart_add_rate": cart.get("cartAddRate"),
            "asin_cart_add_median_price": cart_median_price,
            "asin_cart_add_median_price_currency": cart_median_currency,
            "total_same_day_shipping_cart_add_count": cart.get("sameDayShippingCartAddCount"),
            "total_one_day_shipping_cart_add_count": cart.get("oneDayShippingCartAddCount"),
            "total_two_day_shipping_cart_add_count": cart.get("twoDayShippingCartAddCount"),

            # Purchases
            "asin_purchase_count": purchase.get("purchaseCount"),
            "total_purchase_rate": purchase.get("purchaseRate"),
            "asin_purchase_median_price": purchase_median_price,
            "asin_purchase_median_price_currency": purchase_median_currency,
            "total_same_day_shipping_purchase_count": purchase.get("sameDayShippingPurchaseCount"),
            "total_one_day_shipping_purchase_count": purchase.get("oneDayShippingPurchaseCount"),
            "total_two_day_shipping_purchase_count": purchase.get("twoDayShippingPurchaseCount"),

            # SCP-specific
            "search_traffic_sales": sales_amount,
            "search_traffic_sales_currency": sales_currency,
            "conversion_rate": item.get("conversionRate"),
        }
        rows.append(row)

    return rows


# =============================================================================
# High-Level Pull Functions
# =============================================================================

def pull_sqp_batch(
    client: "SPAPIClient",
    marketplace_code: str,
    asins: List[str],
    period_start: date,
    period_end: date,
    period_type: str = "WEEK",
    region: str = "NA",
    marketplace_id: str = None
) -> Tuple[List[Dict], int]:
    """
    Pull SQP data for a single batch of ASINs.
    Creates report, polls, downloads, and parses.

    Args:
        client: SPAPIClient instance
        marketplace_code: e.g., 'USA'
        asins: List of ASINs (must fit within 200-char limit)
        period_start: Period start date
        period_end: Period end date
        period_type: 'WEEK', 'MONTH', or 'QUARTER'
        region: API region
        marketplace_id: Supabase marketplace UUID

    Returns:
        Tuple of (parsed_rows, query_count)
    """
    report_id = create_sqp_report(
        client=client,
        marketplace_code=marketplace_code,
        asins=asins,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        region=region
    )

    # SQP reports can take longer to process than SCP
    result = poll_report_status(client=client, report_id=report_id, region=region, max_wait_seconds=600)
    report_data = download_report(client=client, report_document_id=result["reportDocumentId"], region=region)

    rows = parse_sqp_response(report_data, marketplace_id, period_start, period_end, period_type)
    query_count = len(set(r["search_query"] for r in rows)) if rows else 0

    return rows, query_count


def pull_scp_batch(
    client: "SPAPIClient",
    marketplace_code: str,
    asins: List[str],
    period_start: date,
    period_end: date,
    period_type: str = "WEEK",
    region: str = "NA",
    marketplace_id: str = None
) -> List[Dict]:
    """
    Pull SCP data for a single batch of ASINs.

    Returns:
        List of parsed rows
    """
    report_id = create_scp_report(
        client=client,
        marketplace_code=marketplace_code,
        asins=asins,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        region=region
    )

    result = poll_report_status(client=client, report_id=report_id, region=region)
    report_data = download_report(client=client, report_document_id=result["reportDocumentId"], region=region)

    rows = parse_scp_response(report_data, marketplace_id, period_start, period_end, period_type)
    return rows
