"""
SP-API Authentication Module
Handles OAuth 2.0 token refresh via Login With Amazon (LWA)
"""

import os
import requests
from typing import Optional
from datetime import datetime, timedelta

# LWA Token endpoint
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# Cache for access token
_token_cache = {
    "access_token": None,
    "expires_at": None
}


def get_access_token(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None
) -> str:
    """
    Get a valid access token, refreshing if necessary.

    Uses cached token if still valid, otherwise refreshes.

    Args:
        client_id: LWA Client ID (defaults to SP_LWA_CLIENT_ID env var)
        client_secret: LWA Client Secret (defaults to SP_LWA_CLIENT_SECRET env var)
        refresh_token: SP-API Refresh Token (defaults to SP_REFRESH_TOKEN_NA env var)

    Returns:
        Valid access token string

    Raises:
        ValueError: If credentials are missing
        requests.HTTPError: If token refresh fails
    """
    # Check if we have a valid cached token
    if _token_cache["access_token"] and _token_cache["expires_at"]:
        if datetime.now() < _token_cache["expires_at"] - timedelta(minutes=5):
            return _token_cache["access_token"]

    # Need to refresh
    return refresh_access_token(client_id, client_secret, refresh_token)


def refresh_access_token(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    refresh_token: Optional[str] = None
) -> str:
    """
    Refresh the access token using LWA OAuth 2.0.

    Args:
        client_id: LWA Client ID (defaults to SP_LWA_CLIENT_ID env var)
        client_secret: LWA Client Secret (defaults to SP_LWA_CLIENT_SECRET env var)
        refresh_token: SP-API Refresh Token (defaults to SP_REFRESH_TOKEN_NA env var)

    Returns:
        New access token string

    Raises:
        ValueError: If credentials are missing
        requests.HTTPError: If token refresh fails
    """
    # Get credentials from environment if not provided
    client_id = client_id or os.environ.get("SP_LWA_CLIENT_ID")
    client_secret = client_secret or os.environ.get("SP_LWA_CLIENT_SECRET")
    refresh_token = refresh_token or os.environ.get("SP_REFRESH_TOKEN_NA")

    # Validate credentials
    if not all([client_id, client_secret, refresh_token]):
        missing = []
        if not client_id:
            missing.append("SP_LWA_CLIENT_ID")
        if not client_secret:
            missing.append("SP_LWA_CLIENT_SECRET")
        if not refresh_token:
            missing.append("SP_REFRESH_TOKEN_NA")
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    # Make token refresh request
    response = requests.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )

    response.raise_for_status()
    data = response.json()

    # Cache the new token
    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)  # Default 1 hour

    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = datetime.now() + timedelta(seconds=expires_in)

    print(f"✓ Access token refreshed, expires in {expires_in} seconds")

    return access_token


def get_refresh_token_for_region(region: str) -> str:
    """
    Get the refresh token for a specific region.

    Args:
        region: One of 'NA', 'EU', 'FE'

    Returns:
        Refresh token for the specified region

    Raises:
        ValueError: If region is invalid or token not found
    """
    region = region.upper()
    env_var_map = {
        "NA": "SP_REFRESH_TOKEN_NA",
        "EU": "SP_REFRESH_TOKEN_EU",
        "FE": "SP_REFRESH_TOKEN_FE"
    }

    if region not in env_var_map:
        raise ValueError(f"Invalid region: {region}. Must be one of: NA, EU, FE")

    token = os.environ.get(env_var_map[region])
    if not token:
        raise ValueError(f"No refresh token found for region {region}. Set {env_var_map[region]} environment variable.")

    return token
