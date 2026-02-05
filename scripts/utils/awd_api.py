"""
AWD (Amazon Warehousing and Distribution) API Module
Uses the AWD API v2024-05-09 to get inventory in AWD distribution centers.

This tracks inventory that's stored in AWD before being distributed to FBA.

API Reference: https://developer-docs.amazon.com/sp-api/docs/amazon-warehousing-and-distribution-api-use-case-guide

Response Schema (InventorySummary):
- sku: The seller or merchant SKU
- totalOnhandQuantity: Total quantity present in AWD distribution centers
- totalInboundQuantity: Total quantity in-transit (not yet received at AWD)
- inventoryDetails:
    - availableDistributableQuantity: Available for downstream replenishment
    - reservedDistributableQuantity: Reserved for replenishment orders being prepared
"""

import requests
from typing import Dict, List, Any, Optional
from datetime import datetime

# Regional endpoints (same as other SP-APIs)
ENDPOINTS = {
    "NA": "sellingpartnerapi-na.amazon.com",
    "EU": "sellingpartnerapi-eu.amazon.com",
    "FE": "sellingpartnerapi-fe.amazon.com"
}

# AWD API version
AWD_API_VERSION = "2024-05-09"


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def list_inventory(
    access_token: str,
    region: str = "NA",
    sku: Optional[str] = None,
    details: bool = True,
    max_results: int = 200,
    next_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    List AWD inventory from the AWD API.

    Args:
        access_token: Valid SP-API access token
        region: API region ('NA', 'EU', 'FE')
        sku: Optional SKU filter
        details: Include detailed inventory breakdown (default True)
        max_results: Max results per page (1-200, default 200)
        next_token: Pagination token

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

    response = requests.get(
        url,
        params=params,
        headers={
            "x-amz-access-token": access_token,
            "Content-Type": "application/json"
        }
    )

    response.raise_for_status()
    return response.json()


def get_all_awd_inventory(
    access_token: str,
    region: str = "NA"
) -> List[Dict[str, Any]]:
    """
    Get all AWD inventory, handling pagination.

    Args:
        access_token: Valid SP-API access token
        region: API region

    Returns:
        List of inventory summary dictionaries
    """
    all_inventory = []
    next_token = None
    page = 1

    while True:
        print(f"  Fetching AWD inventory page {page}...")

        result = list_inventory(
            access_token,
            region,
            details=True,
            max_results=200,
            next_token=next_token
        )

        inventory = result.get("inventory", [])
        all_inventory.extend(inventory)

        # Check for next page
        next_token = result.get("nextToken")

        if not next_token:
            break

        page += 1

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
    access_token: str,
    region: str = "NA"
) -> List[Dict[str, Any]]:
    """
    High-level function to pull AWD inventory.

    Args:
        access_token: Valid SP-API access token
        region: API region

    Returns:
        List of transformed inventory records ready for DB insertion
    """
    # Get all inventory
    inventory = get_all_awd_inventory(access_token, region)

    # Transform to DB format
    records = []
    for item in inventory:
        record = transform_awd_inventory(item)
        if record["sku"]:  # Skip records without SKU
            records.append(record)

    return records
