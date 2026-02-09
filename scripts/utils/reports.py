"""
SP-API Reports Module
Handles report creation, polling, and downloading for Sales & Traffic reports

Updated to use SPAPIClient for automatic retry and rate limiting.
"""

import os
import gzip
import json
import time
import logging
import requests
from typing import Dict, List, Optional, Any, Union
from datetime import date, datetime

# Import the new API client (optional import for backward compatibility)
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


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def create_report(
    access_token: str = None,
    marketplace_code: str = None,
    report_date: date = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> str:
    """
    Create a Sales & Traffic report request for a single day.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        marketplace_code: Marketplace code (e.g., 'USA', 'UK')
        report_date: The date to pull data for (single day)
        region: API region ('NA', 'EU', 'FE')
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Report ID string

    Raises:
        ValueError: If marketplace code is invalid
        requests.HTTPError: If API request fails
    """
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    # Format date as ISO 8601 (same start and end for single day)
    date_str = report_date.strftime("%Y-%m-%dT00:00:00Z")

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    payload = {
        "reportType": "GET_SALES_AND_TRAFFIC_REPORT",
        "marketplaceIds": [amazon_marketplace_id],
        "dataStartTime": date_str,
        "dataEndTime": date_str,  # Same date = single day
        "reportOptions": {
            "dateGranularity": "DAY",
            "asinGranularity": "CHILD"
        }
    }

    headers = {"Content-Type": "application/json"}

    # Use client if provided (preferred), otherwise fall back to direct requests
    if client is not None:
        response = client.post(
            url,
            json=payload,
            headers=headers,
            api_type="reports_create"  # 1 request per minute rate limit
        )
    else:
        # Backward compatibility: direct request (no retry)
        headers["x-amz-access-token"] = access_token
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

    data = response.json()
    report_id = data["reportId"]

    logger.info(f"Created report {report_id} for {marketplace_code} on {report_date}")
    print(f"✓ Created report {report_id} for {marketplace_code} on {report_date}")

    return report_id


def poll_report_status(
    access_token: str = None,
    report_id: str = None,
    region: str = "NA",
    max_wait_seconds: int = 300,
    poll_interval: int = 10,
    client: "SPAPIClient" = None
) -> Dict[str, Any]:
    """
    Poll for report completion and return the report document ID.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        report_id: The report ID to poll
        region: API region ('NA', 'EU', 'FE')
        max_wait_seconds: Maximum time to wait for completion
        poll_interval: Seconds between polls
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Dict with 'reportDocumentId' and 'processingStatus'

    Raises:
        TimeoutError: If report doesn't complete in time
        requests.HTTPError: If API request fails
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/reports/{report_id}"

    start_time = time.time()

    while True:
        # Use client if provided (preferred), otherwise fall back to direct requests
        if client is not None:
            response = client.get(url, api_type="reports_get")  # 2 req/sec rate limit
        else:
            # Backward compatibility: direct request (no retry)
            response = requests.get(
                url,
                headers={"x-amz-access-token": access_token}
            )
            response.raise_for_status()

        data = response.json()
        status = data.get("processingStatus")

        if status == "DONE":
            logger.info(f"Report {report_id} completed")
            print(f"✓ Report {report_id} completed")
            return {
                "reportDocumentId": data["reportDocumentId"],
                "processingStatus": status
            }

        if status in ["CANCELLED", "FATAL"]:
            raise RuntimeError(f"Report failed with status: {status}")

        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise TimeoutError(f"Report {report_id} did not complete within {max_wait_seconds} seconds")

        print(f"  Report status: {status}, waiting {poll_interval}s...")
        time.sleep(poll_interval)


def download_report(
    access_token: str = None,
    report_document_id: str = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> Dict[str, Any]:
    """
    Download and parse a completed report.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        report_document_id: The document ID from poll_report_status
        region: API region ('NA', 'EU', 'FE')
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Parsed report data as dictionary

    Raises:
        requests.HTTPError: If download fails
    """
    endpoint = get_endpoint(region)

    # Step 1: Get the pre-signed download URL
    url = f"https://{endpoint}/reports/2021-06-30/documents/{report_document_id}"

    if client is not None:
        response = client.get(url, api_type="reports_get")
    else:
        response = requests.get(
            url,
            headers={"x-amz-access-token": access_token}
        )
        response.raise_for_status()

    doc_info = response.json()

    download_url = doc_info["url"]
    compression = doc_info.get("compressionAlgorithm")

    # Step 2: Download the actual report (S3 URL - no auth needed, but use client for retry)
    if client is not None:
        # Use client session for retry on download, but no SP-API auth header
        report_response = client.session.get(download_url, timeout=client.timeout)
        report_response.raise_for_status()
    else:
        report_response = requests.get(download_url)
        report_response.raise_for_status()

    # Step 3: Decompress if needed
    content = report_response.content
    if compression == "GZIP":
        content = gzip.decompress(content)

    # Step 4: Parse JSON
    report_data = json.loads(content.decode("utf-8"))

    asin_count = len(report_data.get("salesAndTrafficByAsin", []))
    logger.info(f"Downloaded report with {asin_count} ASINs")
    print(f"✓ Downloaded report with {asin_count} ASINs")

    return report_data


def pull_single_day_report(
    access_token: str = None,
    marketplace_code: str = None,
    report_date: date = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> Dict[str, Any]:
    """
    High-level function to create, poll, and download a single day's report.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        marketplace_code: Marketplace code (e.g., 'USA', 'UK')
        report_date: The date to pull data for
        region: API region ('NA', 'EU', 'FE')
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Parsed report data
    """
    # Create report
    report_id = create_report(
        access_token=access_token,
        marketplace_code=marketplace_code,
        report_date=report_date,
        region=region,
        client=client
    )

    # Poll until complete
    result = poll_report_status(
        access_token=access_token,
        report_id=report_id,
        region=region,
        client=client
    )

    # Download and parse
    report_data = download_report(
        access_token=access_token,
        report_document_id=result["reportDocumentId"],
        region=region,
        client=client
    )

    return report_data
