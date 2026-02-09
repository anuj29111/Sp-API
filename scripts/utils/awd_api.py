"""
AWD (Amazon Warehousing and Distribution) API Module
Uses the AWD API v2024-05-09 to get inventory in AWD distribution centers.

This tracks inventory that's stored in AWD before being distributed to FBA.

Updated to use SPAPIClient for automatic retry and rate limiting.

API Reference: https://developer-docs.amazon.com/sp-api/docs/amazon-warehousing-and-distribution-api-use-case-guide

Response Schema (InventorySummary):
- sku: The seller or merchant SKU
- totalOnhandQuantity: Total quantity present in AWD distribution centers
- totalInboundQuantity: Total quantity in-transit (not yet received at AWD)
- inventoryDetails:
    - availableDistributableQuantity: Available for downstream replenishment
    - reservedDistributableQuantity: Reserved for replenishment orders being prepared
"""

import logging
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime

# Import the new API client (optional import for backward compatibility)
try:
    from utils.api_client import SPAPIClient
except ImportError:
    SPAPIClient = None

logger = logging.getLogger(__name__)

# Regional endpoints (same as other SP-APIs)
ENDPOINTS = {
    "NA": "sellingpartnerapi-na.amazon.com",
    "EU": "sellingpartnerapi-eu.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com",
    "UAE": "sellingpartnerapi-eu.amazon.com"   # UAE uses EU endpoint, different token
}

# AWD API version
AWD_API_VERSION = "2024-05-09"


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def list_inventory(
    access_token: str = None,
    region: str = "NA",
    sku: Optional[str] = None,
    details: bool = True,
    max_results: int = 200,
    next_token: Optional[str] = None,
    client: "SPAPIClient" = None
) -> Dict[str, Any]:
    """
    List AWD inventory from the AWD API.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        region: API region ('NA', 'EU', 'FE')
        sku: Optional SKU filter
        details: Include detailed inventory breakdown (default True)
        max_results: Max results per page (1-200, default 200)
        next_token: Pagination token
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Dict with 'inventory' list and optionally 'nextToken'
    """
    endpoint = get_endpoint(region)
    url = f"https://{endpoint}/awd/{AWD_API_VERSION}/inventory"

    params = {
        "maxResults": min(max_results, 200),
        "details": "SHOW" if details else "HIDE"
    }

    if sku:
        params["sku"] = sku

    if next_token:
        params["nextToken"] = next_token

    headers = {"Content-Type": "application/json"}

    # Use client if provided (preferred), otherwise fall back to direct requests
    if client is not None:
        response = client.get(url, params=params, headers=headers, api_type="awd")
    else:
        # Backward compatibility: direct request (no retry)
        headers["x-amz-access-token"] = access_token
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

    return response.json()


def get_all_awd_inventory(
    access_token: str = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> List[Dict[str, Any]]:
    """
    Get all AWD inventory, handling pagination.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        region: API region
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        List of inventory summary dictionaries
    """
    all_inventory = []
    next_token = None
    page = 1

    while True:
        logger.debug(f"Fetching AWD inventory page {page}")
        print(f"  Fetching AWD inventory page {page}...")

        result = list_inventory(
            access_token=access_token,
            region=region,
            details=True,
            max_results=200,
            next_token=next_token,
            client=client
        )

        inventory = result.get("inventory", [])
        all_inventory.extend(inventory)

        # Check for next page
        next_token = result.get("nextToken")

        if not next_token:
            break

        page += 1

    logger.info(f"Retrieved {len(all_inventory)} AWD inventory items")
    print(f"✓ Retrieved {len(all_inventory)} AWD inventory items")
    return all_inventory


def transform_awd_inventory(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform an AWD inventory item from the API response to our DB format.

    API Response Fields:
    - sku: The seller or merchant SKU
    - totalOnhandQuantity: Total quantity in AWD DCs
    - totalInboundQuantity: Quantity in-transit to AWD
    - inventoryDetails:
        - availableDistributableQuantity: Available for replenishment
        - reservedDistributableQuantity: Reserved for replenishment orders

    Returns:
        Dict with fields matching our sp_awd_inventory table
    """
    details = item.get("inventoryDetails", {})

    total_onhand = item.get("totalOnhandQuantity", 0) or 0
    total_inbound = item.get("totalInboundQuantity", 0) or 0
    available = details.get("availableDistributableQuantity", 0) or 0
    reserved = details.get("reservedDistributableQuantity", 0) or 0

    return {
        "sku": item.get("sku", ""),

        # Core AWD quantities
        "total_onhand_quantity": total_onhand,
        "total_inbound_quantity": total_inbound,
        "available_quantity": available,
        "reserved_quantity": reserved,

        # Calculated total
        "total_quantity": total_onhand + total_inbound,
    }


def pull_awd_inventory(
    access_token: str = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> List[Dict[str, Any]]:
    """
    High-level function to pull AWD inventory.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        region: API region
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        List of transformed inventory records ready for DB insertion
    """
    # Get all inventory
    inventory = get_all_awd_inventory(
        access_token=access_token,
        region=region,
        client=client
    )

    # Transform to DB format
    records = []
    for item in inventory:
        record = transform_awd_inventory(item)
        if record["sku"]:  # Skip records without SKU
            records.append(record)

    return records
