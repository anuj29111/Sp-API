"""
SP-API Brand Analytics Search Terms Report Module

Handles report creation, streaming download, and parsing for the Search Terms
Report (GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT).

Key differences from SQP/SCP reports:
- NO ASIN parameter — returns entire marketplace data
- Massive output (~12M rows, ~2.3 GB) — requires streaming JSON parse
- Only reportOption is reportPeriod (WEEK/MONTH/QUARTER/DAY)
- Returns top 3 clicked ASINs per search term with click/conversion share
- We filter to only keep terms matching our SQP keywords

Uses ijson for streaming JSON parsing to keep memory usage under 50 MB
regardless of report size.
"""

import gzip
import json
import time
import logging
import requests
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple, Set, Callable
from datetime import date

try:
    import ijson
except ImportError:
    ijson = None

try:
    from utils.api_client import SPAPIClient
except ImportError:
    SPAPIClient = None

logger = logging.getLogger(__name__)

SEARCH_TERMS_REPORT_TYPE = "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT"

# Regional endpoints (same as sqp_reports.py)
ENDPOINTS = {
    "NA": "sellingpartnerapi-na.amazon.com",
    "EU": "sellingpartnerapi-eu.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com",
    "UAE": "sellingpartnerapi-eu.amazon.com"
}

# Amazon Marketplace IDs (same as sqp_reports.py)
MARKETPLACE_IDS = {
    "USA": {"id": "ATVPDKIKX0DER", "region": "NA"},
    "CA": {"id": "A2EUQ1WTGCTBG2", "region": "NA"},
    "MX": {"id": "A1AM78C64UM0Y8", "region": "NA"},
    "UK": {"id": "A1F83G8C2ARO7P", "region": "EU"},
    "DE": {"id": "A1PA6795UKMFR9", "region": "EU"},
    "FR": {"id": "A13V1IB3VIYZZH", "region": "EU"},
    "IT": {"id": "APJ6JRA9NG5V4", "region": "EU"},
    "ES": {"id": "A1RKKUPIHCS9HS", "region": "EU"},
    "UAE": {"id": "A2VIGQ35RCS4UG", "region": "EU"},
    "AU": {"id": "A39IBJ37TRP1C6", "region": "FE"},
}


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


# =============================================================================
# Report Creation
# =============================================================================

def create_search_terms_report(
    client: "SPAPIClient",
    marketplace_code: str,
    period_start: date,
    period_end: date,
    period_type: str = "WEEK",
    region: str = "NA"
) -> str:
    """
    Create a Search Terms Report request.

    Unlike SQP/SCP, this report has NO ASIN parameter — it returns the entire
    marketplace's search term data.

    Args:
        client: SPAPIClient instance
        marketplace_code: Marketplace code (e.g., 'USA')
        period_start: Start date of the period (must align to period boundaries)
        period_end: End date of the period
        period_type: 'WEEK', 'MONTH', 'QUARTER', or 'DAY'
        region: API region

    Returns:
        Report ID string
    """
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    payload = {
        "reportType": SEARCH_TERMS_REPORT_TYPE,
        "marketplaceIds": [amazon_marketplace_id],
        "dataStartTime": period_start.strftime("%Y-%m-%dT00:00:00Z"),
        "dataEndTime": period_end.strftime("%Y-%m-%dT00:00:00Z"),
        "reportOptions": {
            "reportPeriod": period_type
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

    logger.info(f"Created Search Terms report {report_id} for {marketplace_code} ({period_type} {period_start})")
    print(f"  Created Search Terms report {report_id} ({period_type} {period_start} to {period_end})")

    return report_id


# =============================================================================
# Report Download URL (separate from download — we stream the content)
# =============================================================================

def get_report_download_info(
    client: "SPAPIClient",
    report_document_id: str,
    region: str = "NA"
) -> Dict[str, str]:
    """
    Get the S3 download URL and compression info for a completed report.

    This does NOT download the report content — it only gets the URL.
    The actual download is done via streaming in stream_and_filter_search_terms().

    Args:
        client: SPAPIClient instance
        report_document_id: Document ID from poll_report_status
        region: API region

    Returns:
        Dict with 'url' and 'compressionAlgorithm' keys
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/documents/{report_document_id}"

    response = client.get(url, api_type="reports_get")
    doc_info = response.json()

    download_url = doc_info["url"]
    compression = doc_info.get("compressionAlgorithm")

    logger.info(f"Got download URL for document {report_document_id} (compression: {compression})")
    return {
        "url": download_url,
        "compressionAlgorithm": compression
    }


# =============================================================================
# Streaming Download + Filter + Parse
# =============================================================================

def transform_search_term_row(
    item: Dict,
    marketplace_id: str,
    period_start: date,
    period_end: date,
    period_type: str
) -> Dict:
    """
    Transform a single report item into a database row dict.

    Args:
        item: Raw JSON item from the report
        marketplace_id: Supabase marketplace UUID
        period_start/period_end: Period boundaries
        period_type: 'WEEK', 'MONTH', etc.

    Returns:
        Flat dict ready for Supabase upsert
    """
    return {
        "marketplace_id": marketplace_id,
        "search_term": item.get("searchTerm", "").strip(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_type": period_type,
        "department_name": item.get("departmentName"),
        "search_frequency_rank": item.get("searchFrequencyRank"),
        "clicked_asin": item.get("clickedAsin", ""),
        "click_share_rank": item.get("clickShareRank"),
        "click_share": item.get("clickShare"),
        "conversion_share": item.get("conversionShare"),
    }


def stream_and_filter_search_terms(
    download_url: str,
    compression: Optional[str],
    sqp_keywords_set: Set[str],
    marketplace_id: str,
    period_start: date,
    period_end: date,
    period_type: str,
    upsert_callback: Callable[[List[Dict]], int],
    batch_size: int = 200
) -> Tuple[int, int]:
    """
    Stream-download the Search Terms Report, filter to SQP keywords, and upsert matches.

    This is the core function that handles the ~2.3 GB report without loading it
    into memory. Uses ijson for streaming JSON parsing.

    Args:
        download_url: S3 pre-signed URL for the report
        compression: 'GZIP' or None
        sqp_keywords_set: Set of lowercased search query strings from SQP data
        marketplace_id: Supabase marketplace UUID
        period_start/period_end: Period boundaries
        period_type: Period type string
        upsert_callback: Function to call with batches of rows (e.g., upsert_search_terms_data)
        batch_size: Number of rows per upsert batch

    Returns:
        Tuple of (matched_terms_count, total_rows_upserted)
        matched_terms_count = unique search terms that matched
        total_rows_upserted = total rows (each term has up to 3 ASIN rows)
    """
    if ijson is None:
        raise ImportError("ijson is required for streaming Search Terms Report. Install with: pip install ijson")

    print(f"  Streaming download from S3 (compression: {compression})...")
    logger.info(f"Starting stream download, filtering against {len(sqp_keywords_set)} SQP keywords")

    # Stream the S3 response
    response = requests.get(download_url, stream=True, timeout=600)
    response.raise_for_status()

    # Set up the stream — handle gzip decompression
    if compression == "GZIP":
        # Wrap the raw stream in GzipFile for on-the-fly decompression
        # Note: response.raw.decode_content doesn't always work with ijson,
        # so we explicitly wrap in gzip.GzipFile
        stream = gzip.GzipFile(fileobj=response.raw)
    else:
        stream = response.raw

    # Track progress
    matched_terms = set()
    total_rows = 0
    total_scanned = 0
    batch_buffer = []
    last_progress = time.time()

    try:
        # Stream-parse the JSON array items one at a time
        # The report structure is: { "dataByDepartmentAndSearchTerm": [...items...] }
        items = ijson.items(stream, 'dataByDepartmentAndSearchTerm.item')

        for item in items:
            total_scanned += 1

            # Progress logging every 30 seconds
            now = time.time()
            if now - last_progress > 30:
                print(f"    Scanned {total_scanned:,} items, matched {len(matched_terms):,} terms ({total_rows:,} rows)...", flush=True)
                last_progress = now

            # Check if this search term matches our SQP keywords
            search_term = item.get("searchTerm", "")
            if not search_term:
                continue

            search_term_lower = search_term.lower().strip()
            if search_term_lower not in sqp_keywords_set:
                continue

            # Match found — transform and buffer
            matched_terms.add(search_term_lower)
            row = transform_search_term_row(
                item, marketplace_id, period_start, period_end, period_type
            )
            batch_buffer.append(row)

            # Upsert when buffer is full
            if len(batch_buffer) >= batch_size:
                upserted = upsert_callback(batch_buffer)
                total_rows += upserted
                batch_buffer = []

        # Flush remaining buffer
        if batch_buffer:
            upserted = upsert_callback(batch_buffer)
            total_rows += upserted

    except Exception as e:
        # Flush any buffered rows before re-raising
        if batch_buffer:
            try:
                upserted = upsert_callback(batch_buffer)
                total_rows += upserted
                print(f"    Flushed {len(batch_buffer)} buffered rows before error")
            except Exception:
                pass
        raise RuntimeError(f"Error streaming Search Terms Report: {str(e)}") from e
    finally:
        response.close()

    print(f"  Stream complete: scanned {total_scanned:,} items, matched {len(matched_terms):,} terms, {total_rows:,} rows upserted")
    logger.info(f"Stream complete: {total_scanned} scanned, {len(matched_terms)} matched, {total_rows} rows")

    return len(matched_terms), total_rows


def download_and_filter_fallback(
    download_url: str,
    compression: Optional[str],
    sqp_keywords_set: Set[str],
    marketplace_id: str,
    period_start: date,
    period_end: date,
    period_type: str,
    upsert_callback: Callable[[List[Dict]], int],
    batch_size: int = 200
) -> Tuple[int, int]:
    """
    Fallback: Download full report to memory, then filter.

    Use this if ijson streaming doesn't work (e.g., unexpected JSON structure).
    WARNING: Requires ~3+ GB memory. Only use for debugging/testing.

    Args: Same as stream_and_filter_search_terms()
    Returns: Tuple of (matched_terms_count, total_rows_upserted)
    """
    print(f"  WARNING: Using memory-based fallback (not streaming)")
    logger.warning("Using memory-based fallback for Search Terms Report")

    response = requests.get(download_url, timeout=600)
    response.raise_for_status()

    content = response.content
    if compression == "GZIP":
        content = gzip.decompress(content)

    report_data = json.loads(content.decode("utf-8"))
    items = report_data.get("dataByDepartmentAndSearchTerm", [])

    print(f"  Downloaded {len(items):,} items, filtering against {len(sqp_keywords_set):,} SQP keywords...")

    matched_terms = set()
    total_rows = 0
    batch_buffer = []

    for item in items:
        search_term = item.get("searchTerm", "")
        if not search_term:
            continue

        search_term_lower = search_term.lower().strip()
        if search_term_lower not in sqp_keywords_set:
            continue

        matched_terms.add(search_term_lower)
        row = transform_search_term_row(
            item, marketplace_id, period_start, period_end, period_type
        )
        batch_buffer.append(row)

        if len(batch_buffer) >= batch_size:
            upserted = upsert_callback(batch_buffer)
            total_rows += upserted
            batch_buffer = []

    if batch_buffer:
        upserted = upsert_callback(batch_buffer)
        total_rows += upserted

    print(f"  Fallback complete: {len(items):,} items → matched {len(matched_terms):,} terms, {total_rows:,} rows")
    return len(matched_terms), total_rows
