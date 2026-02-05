"""
SP-API Inventory Reports Module
Handles FBA inventory, inventory age, and storage fee reports
"""

import os
import gzip
import csv
import io
import time
import requests
from typing import Dict, List, Optional, Any
from datetime import date, datetime

# Regional endpoints
ENDPOINTS = {
    "NA": "sellingpartnerapi-na.amazon.com",
    "EU": "sellingpartnerapi-eu.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com"
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
    "UAE": {"id": "A2VIGQ35RCS4UG", "region": "EU"},
    "AU": {"id": "A39IBJ37TRP1C6", "region": "FE"},
    "JP": {"id": "A1VC38T7YXB528", "region": "FE"}
}

# Inventory report types
REPORT_TYPES = {
    "FBA_INVENTORY": "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA",
    "FBA_ALL_INVENTORY": "GET_FBA_MYI_ALL_INVENTORY_DATA",  # Includes more fields
    "INVENTORY_AGE": "GET_FBA_INVENTORY_AGED_DATA",
    "STORAGE_FEES": "GET_FBA_STORAGE_FEE_CHARGES_DATA"
}


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def create_inventory_report(
    access_token: str,
    marketplace_code: str,
    report_type: str,
    region: str = "NA",
    report_options: Dict[str, str] = None
) -> str:
    """
    Create an inventory report request.

    Note: Inventory reports are snapshot reports - they don't take date parameters.
    They return the current state of inventory.

    Args:
        access_token: Valid SP-API access token
        marketplace_code: Marketplace code (e.g., 'USA', 'UK')
        report_type: One of REPORT_TYPES keys
        region: API region ('NA', 'EU', 'FE')
        report_options: Optional report options dictionary

    Returns:
        Report ID string
    """
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    report_type_name = REPORT_TYPES.get(report_type, report_type)

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    payload = {
        "reportType": report_type_name,
        "marketplaceIds": [amazon_marketplace_id]
    }

    # Add report options if provided (some reports need this)
    if report_options:
        payload["reportOptions"] = report_options

    response = requests.post(
        url,
        json=payload,
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        }
    )

    response.raise_for_status()
    data = response.json()
    report_id = data["reportId"]

    print(f"✓ Created {report_type} report {report_id} for {marketplace_code}")

    return report_id


def create_storage_fee_report(
    access_token: str,
    marketplace_code: str,
    month: date,
    region: str = "NA"
) -> str:
    """
    Create a storage fee report for a specific month.

    Args:
        access_token: Valid SP-API access token
        marketplace_code: Marketplace code
        month: First day of the month to get fees for
        region: API region

    Returns:
        Report ID string
    """
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    # Storage fee reports need date range for the month
    start_date = month.replace(day=1)
    # Get last day of month
    if month.month == 12:
        end_date = month.replace(year=month.year + 1, month=1, day=1)
    else:
        end_date = month.replace(month=month.month + 1, day=1)

    url = f"https://{endpoint}/reports/2021-06-30/reports"

    payload = {
        "reportType": REPORT_TYPES["STORAGE_FEES"],
        "marketplaceIds": [amazon_marketplace_id],
        "dataStartTime": start_date.strftime("%Y-%m-%dT00:00:00Z"),
        "dataEndTime": end_date.strftime("%Y-%m-%dT00:00:00Z")
    }

    response = requests.post(
        url,
        json=payload,
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        }
    )

    response.raise_for_status()
    data = response.json()
    report_id = data["reportId"]

    print(f"✓ Created storage fee report {report_id} for {marketplace_code} ({start_date.strftime('%Y-%m')})")

    return report_id


def poll_report_status(
    access_token: str,
    report_id: str,
    region: str = "NA",
    max_wait_seconds: int = 300,
    poll_interval: int = 10
) -> Dict[str, Any]:
    """
    Poll for report completion and return the report document ID.
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/reports/2021-06-30/reports/{report_id}"

    start_time = time.time()

    while True:
        response = requests.get(
            url,
            headers={"x-amz-access-token": access_token}
        )
        response.raise_for_status()
        data = response.json()

        status = data.get("processingStatus")

        if status == "DONE":
            print(f"✓ Report {report_id} completed")
            return {
                "reportDocumentId": data["reportDocumentId"],
                "processingStatus": status
            }

        if status in ["CANCELLED", "FATAL"]:
            # Include any additional error info from Amazon
            error_info = data.get("processingEndTime", "")
            report_type = data.get("reportType", "")
            raise RuntimeError(f"Report failed with status: {status}. Type: {report_type}. Full response: {data}")

        elapsed = time.time() - start_time
        if elapsed > max_wait_seconds:
            raise TimeoutError(f"Report {report_id} did not complete within {max_wait_seconds} seconds")

        print(f"  Report status: {status}, waiting {poll_interval}s...")
        time.sleep(poll_interval)


def download_report(
    access_token: str,
    report_document_id: str,
    region: str = "NA"
) -> List[Dict[str, Any]]:
    """
    Download and parse an inventory report (TSV format).

    Returns:
        List of dictionaries, one per row
    """
    endpoint = get_endpoint(region)

    # Step 1: Get the pre-signed download URL
    url = f"https://{endpoint}/reports/2021-06-30/documents/{report_document_id}"

    response = requests.get(
        url,
        headers={"x-amz-access-token": access_token}
    )
    response.raise_for_status()
    doc_info = response.json()

    download_url = doc_info["url"]
    compression = doc_info.get("compressionAlgorithm")

    # Step 2: Download the actual report
    report_response = requests.get(download_url)
    report_response.raise_for_status()

    # Step 3: Decompress if needed
    content = report_response.content
    if compression == "GZIP":
        content = gzip.decompress(content)

    # Step 4: Parse TSV (inventory reports are tab-separated)
    # Amazon reports may use different encodings - try UTF-8 first, then CP1252 (Windows-1252)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        # CP1252 is commonly used by Amazon for reports with special characters
        text = content.decode("cp1252")

    reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    rows = list(reader)

    print(f"✓ Downloaded report with {len(rows)} rows")

    return rows


def pull_inventory_report(
    access_token: str,
    marketplace_code: str,
    report_type: str,
    region: str = "NA"
) -> List[Dict[str, Any]]:
    """
    High-level function to create, poll, and download an inventory report.

    Args:
        access_token: Valid SP-API access token
        marketplace_code: Marketplace code
        report_type: One of REPORT_TYPES keys
        region: API region

    Returns:
        List of row dictionaries
    """
    # Create report
    report_id = create_inventory_report(access_token, marketplace_code, report_type, region)

    # Poll until complete
    result = poll_report_status(access_token, report_id, region)

    # Download and parse
    rows = download_report(access_token, result["reportDocumentId"], region)

    return rows


def pull_storage_fee_report(
    access_token: str,
    marketplace_code: str,
    month: date,
    region: str = "NA"
) -> List[Dict[str, Any]]:
    """
    High-level function to pull storage fee report for a month.
    """
    # Create report
    report_id = create_storage_fee_report(access_token, marketplace_code, month, region)

    # Poll until complete
    result = poll_report_status(access_token, report_id, region)

    # Download and parse
    rows = download_report(access_token, result["reportDocumentId"], region)

    return rows
