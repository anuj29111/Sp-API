"""
FBA Inventory API Module
Uses the FBA Inventory API v1 to get real-time inventory summaries.

This is more reliable than the report-based approach (GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA)
which has known issues with FATAL status errors.

Updated to use SPAPIClient for automatic retry and rate limiting.

API Reference: https://developer-docs.amazon.com/sp-api/docs/fba-inventory-api
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


def get_endpoint(region: str) -> str:
    """Get the API endpoint for a region."""
    return ENDPOINTS.get(region.upper(), ENDPOINTS["NA"])


def get_inventory_summaries(
    access_token: str = None,
    marketplace_code: str = None,
    region: str = "NA",
    details: bool = True,
    seller_skus: Optional[List[str]] = None,
    next_token: Optional[str] = None,
    client: "SPAPIClient" = None
) -> Dict[str, Any]:
    """
    Get inventory summaries from the FBA Inventory API.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        marketplace_code: Marketplace code (e.g., 'USA', 'CA', 'MX')
        region: API region ('NA', 'EU', 'FE')
        details: Include detailed inventory breakdown
        seller_skus: Optional list of SKUs to filter (max 50)
        next_token: Pagination token
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        Dict with 'inventorySummaries' list and optionally 'nextToken'
    """
    marketplace_info = MARKETPLACE_IDS.get(marketplace_code.upper())
    if not marketplace_info:
        raise ValueError(f"Invalid marketplace code: {marketplace_code}")

    amazon_marketplace_id = marketplace_info["id"]
    endpoint = get_endpoint(region)

    url = f"https://{endpoint}/fba/inventory/v1/summaries"

    params = {
        "granularityType": "Marketplace",
        "granularityId": amazon_marketplace_id,
        "marketplaceIds": amazon_marketplace_id,
        "details": str(details).lower()
    }

    if seller_skus:
        params["sellerSkus"] = ",".join(seller_skus[:50])  # Max 50 SKUs

    if next_token:
        params["nextToken"] = next_token

    headers = {"Content-Type": "application/json"}

    # Use client if provided (preferred), otherwise fall back to direct requests
    if client is not None:
        response = client.get(url, params=params, headers=headers, api_type="inventory")
    else:
        # Backward compatibility: direct request (no retry)
        headers["x-amz-access-token"] = access_token
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()

    return response.json()


def get_all_inventory_summaries(
    access_token: str = None,
    marketplace_code: str = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> List[Dict[str, Any]]:
    """
    Get all inventory summaries for a marketplace, handling pagination.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        marketplace_code: Marketplace code
        region: API region
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        List of inventory summary dictionaries
    """
    all_summaries = []
    next_token = None
    page = 1

    while True:
        logger.debug(f"Fetching inventory page {page}")
        print(f"  Fetching inventory page {page}...")

        result = get_inventory_summaries(
            access_token=access_token,
            marketplace_code=marketplace_code,
            region=region,
            details=True,
            next_token=next_token,
            client=client
        )

        payload = result.get("payload", {})
        summaries = payload.get("inventorySummaries", [])
        all_summaries.extend(summaries)

        # Check for next page - nextToken is at payload level, NOT inside pagination
        next_token = payload.get("nextToken")

        if not next_token:
            break

        page += 1

    logger.info(f"Retrieved {len(all_summaries)} inventory summaries")
    print(f"✓ Retrieved {len(all_summaries)} inventory summaries")
    return all_summaries


def transform_inventory_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform an inventory summary from the API response to our DB format.

    API Response Fields:
    - asin, fnSku, sellerSku, condition, productName
    - inventoryDetails:
        - fulfillableQuantity
        - inboundWorkingQuantity
        - inboundShippedQuantity
        - inboundReceivingQuantity
        - reservedQuantity:
            - totalReservedQuantity
            - pendingCustomerOrderQuantity
            - pendingTransshipmentQuantity
            - fcProcessingQuantity
        - unfulfillableQuantity:
            - totalUnfulfillableQuantity
            - customerDamagedQuantity
            - warehouseDamagedQuantity
            - distributorDamagedQuantity
            - carrierDamagedQuantity
            - defectiveQuantity
            - expiredQuantity
        - researchingQuantity:
            - totalResearchingQuantity
            - researchingQuantityBreakdown (list)

    Returns:
        Dict with fields matching our sp_fba_inventory table
    """
    details = summary.get("inventoryDetails", {})
    reserved = details.get("reservedQuantity", {})
    unfulfillable = details.get("unfulfillableQuantity", {})
    researching = details.get("researchingQuantity", {})

    # Core quantities
    fulfillable = details.get("fulfillableQuantity", 0) or 0
    reserved_total = reserved.get("totalReservedQuantity", 0) or 0
    inbound_working = details.get("inboundWorkingQuantity", 0) or 0
    inbound_shipped = details.get("inboundShippedQuantity", 0) or 0
    inbound_receiving = details.get("inboundReceivingQuantity", 0) or 0
    unsellable_total = unfulfillable.get("totalUnfulfillableQuantity", 0) or 0
    researching_total = researching.get("totalResearchingQuantity", 0) or 0

    return {
        "sku": summary.get("sellerSku", ""),
        "asin": summary.get("asin"),
        "fnsku": summary.get("fnSku"),
        "product_name": summary.get("productName"),
        "condition": summary.get("condition"),

        # Core inventory metrics
        # Note: total_quantity is a GENERATED column in DB, don't include it
        "fulfillable_quantity": fulfillable,
        "reserved_quantity": reserved_total,
        "inbound_working_quantity": inbound_working,
        "inbound_shipped_quantity": inbound_shipped,
        "inbound_receiving_quantity": inbound_receiving,
        "unsellable_quantity": unsellable_total,

        # Reserved breakdown
        "pending_customer_order_qty": reserved.get("pendingCustomerOrderQuantity", 0) or 0,
        "pending_transshipment_qty": reserved.get("pendingTransshipmentQuantity", 0) or 0,
        "fc_processing_qty": reserved.get("fcProcessingQuantity", 0) or 0,

        # Unfulfillable/damaged breakdown
        "customer_damaged_qty": unfulfillable.get("customerDamagedQuantity", 0) or 0,
        "warehouse_damaged_qty": unfulfillable.get("warehouseDamagedQuantity", 0) or 0,
        "distributor_damaged_qty": unfulfillable.get("distributorDamagedQuantity", 0) or 0,
        "carrier_damaged_qty": unfulfillable.get("carrierDamagedQuantity", 0) or 0,
        "defective_qty": unfulfillable.get("defectiveQuantity", 0) or 0,
        "expired_qty": unfulfillable.get("expiredQuantity", 0) or 0,

        # Researching quantity
        "researching_qty": researching_total,
    }


def pull_fba_inventory(
    access_token: str = None,
    marketplace_code: str = None,
    region: str = "NA",
    client: "SPAPIClient" = None
) -> List[Dict[str, Any]]:
    """
    High-level function to pull FBA inventory for a marketplace.

    Args:
        access_token: Valid SP-API access token (deprecated, use client instead)
        marketplace_code: Marketplace code
        region: API region
        client: SPAPIClient instance (preferred - handles retry and rate limiting)

    Returns:
        List of transformed inventory records ready for DB insertion
    """
    # Get all summaries
    summaries = get_all_inventory_summaries(
        access_token=access_token,
        marketplace_code=marketplace_code,
        region=region,
        client=client
    )

    # Transform to DB format
    records = []
    for summary in summaries:
        record = transform_inventory_summary(summary)
        if record["sku"]:  # Skip records without SKU
            records.append(record)

    return records
