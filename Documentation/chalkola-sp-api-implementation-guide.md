# Chalkola SP-API Implementation Guide

> **Version:** 1.0  
> **Status:** Ready to Implement  
> **Last Updated:** February 2026  
> **Audience:** Development team implementing SP-API integration

---

## Table of Contents

1. [Prerequisites & Setup](#1-prerequisites--setup)
2. [Authentication System](#2-authentication-system)
3. [Project Structure](#3-project-structure)
4. [Core API Client](#4-core-api-client)
5. [FBA Shipment Automation](#5-fba-shipment-automation)
6. [Brand Analytics SQP Automation](#6-brand-analytics-sqp-automation)
7. [Database Setup](#7-database-setup)
8. [Scheduled Jobs](#8-scheduled-jobs)
9. [Error Handling & Logging](#9-error-handling--logging)
10. [Testing Strategy](#10-testing-strategy)
11. [Deployment Guide](#11-deployment-guide)
12. [Monitoring & Alerts](#12-monitoring--alerts)

---

## 1. Prerequisites & Setup

### 1.1 Required Accounts & Access

| Requirement | Status | Action Needed |
|-------------|--------|---------------|
| Amazon Seller Central Account | ✅ Have | None |
| SP-API Developer Registration | ✅ Approved | None |
| Brand Registry | ✅ Have | Required for SQP |
| AWS Account | ⚠️ Check | Create if needed |
| Supabase Pro | ✅ Have | None |
| Railway Account | ✅ Have | None |

### 1.2 SP-API Registration Steps (If Not Complete)

```
Step 1: Go to Seller Central → Apps & Services → Develop Apps
Step 2: Click "Add new app client"
Step 3: Fill in app details:
        - App name: "Chalkola Internal Tools"
        - API Type: SP-API
        - IAM ARN: (from AWS setup below)
Step 4: Select roles:
        ☑️ Product Listing
        ☑️ Pricing
        ☑️ Amazon Fulfillment
        ☑️ Selling Partner Insights
        ☑️ Finance and Accounting
        ☑️ Inventory and Order Tracking
        ☑️ Amazon Warehousing and Distribution
        ☑️ Brand Analytics
Step 5: Save and note your:
        - LWA Client ID
        - LWA Client Secret
```

### 1.3 AWS IAM Setup

**Create IAM User:**
```
1. Go to AWS Console → IAM → Users → Add User
2. User name: "chalkola-sp-api"
3. Access type: Programmatic access
4. Attach policy: Create custom policy (see below)
5. Save Access Key ID and Secret Access Key
```

**Custom IAM Policy:**
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "execute-api:Invoke",
            "Resource": "arn:aws:execute-api:*:*:*"
        }
    ]
}
```

**Create IAM Role:**
```
1. IAM → Roles → Create Role
2. Trusted entity: Another AWS account
3. Account ID: Your AWS Account ID
4. Attach the same policy
5. Role name: "chalkola-sp-api-role"
6. Note the Role ARN
```

### 1.4 Self-Authorization (Get Refresh Token)

```
Step 1: In Seller Central → Develop Apps → Your App
Step 2: Click "Authorize" button
Step 3: You'll be redirected to consent page
Step 4: Approve the authorization
Step 5: Copy the Refresh Token (SAVE THIS SECURELY!)

Repeat for each region:
- North America (US, CA)
- Europe (UK, DE, FR, UAE)
- Far East (AU)
```

### 1.5 Environment Variables

Create `.env` file (NEVER commit to git):

```env
# ===========================================
# SP-API CREDENTIALS
# ===========================================
SP_API_CLIENT_ID=amzn1.application-oa2-client.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_API_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Refresh Tokens (one per region)
SP_API_REFRESH_TOKEN_NA=Atzr|IwEBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_API_REFRESH_TOKEN_EU=Atzr|IwEBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_API_REFRESH_TOKEN_FE=Atzr|IwEBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# AWS Credentials
AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_ROLE_ARN=arn:aws:iam::123456789012:role/chalkola-sp-api-role

# ===========================================
# SUPABASE
# ===========================================
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SUPABASE_DB_URL=postgresql://postgres:xxxxx@db.xxxxxxxxxxxx.supabase.co:5432/postgres

# ===========================================
# APPLICATION
# ===========================================
ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## 2. Authentication System

### 2.1 Token Management Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    TOKEN FLOW                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Refresh Token (permanent)                                       │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────┐                                            │
│  │ LWA Token       │  POST https://api.amazon.com/auth/o2/token │
│  │ Exchange        │                                            │
│  └─────────────────┘                                            │
│       │                                                          │
│       ▼                                                          │
│  Access Token (1 hour TTL)                                       │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────┐                                            │
│  │ Cache in Redis  │  Or in-memory with 50-min refresh          │
│  │ or Memory       │                                            │
│  └─────────────────┘                                            │
│       │                                                          │
│       ▼                                                          │
│  SP-API Request with Bearer Token                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Token Manager Implementation

```python
# File: src/auth/token_manager.py

import time
import requests
from threading import Lock
from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class TokenInfo:
    access_token: str
    expires_at: float  # Unix timestamp
    
    def is_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or will expire within buffer."""
        return time.time() >= (self.expires_at - buffer_seconds)

class TokenManager:
    """
    Manages SP-API access tokens with automatic refresh.
    Thread-safe for concurrent access.
    """
    
    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    
    # Regional refresh tokens
    REGIONS = {
        'NA': 'SP_API_REFRESH_TOKEN_NA',  # US, CA, MX, BR
        'EU': 'SP_API_REFRESH_TOKEN_EU',  # UK, DE, FR, IT, ES, NL, AE, etc.
        'FE': 'SP_API_REFRESH_TOKEN_FE',  # JP, AU, SG
    }
    
    def __init__(self):
        self.client_id = os.environ['SP_API_CLIENT_ID']
        self.client_secret = os.environ['SP_API_CLIENT_SECRET']
        self._tokens: dict[str, TokenInfo] = {}
        self._locks: dict[str, Lock] = {region: Lock() for region in self.REGIONS}
    
    def get_access_token(self, region: str) -> str:
        """
        Get valid access token for region.
        Automatically refreshes if expired or expiring soon.
        
        Args:
            region: 'NA', 'EU', or 'FE'
            
        Returns:
            Valid access token string
        """
        if region not in self.REGIONS:
            raise ValueError(f"Invalid region: {region}. Must be one of {list(self.REGIONS.keys())}")
        
        with self._locks[region]:
            token_info = self._tokens.get(region)
            
            # Refresh if no token or expired/expiring
            if token_info is None or token_info.is_expired():
                token_info = self._refresh_token(region)
                self._tokens[region] = token_info
            
            return token_info.access_token
    
    def _refresh_token(self, region: str) -> TokenInfo:
        """Exchange refresh token for new access token."""
        refresh_token = os.environ.get(self.REGIONS[region])
        
        if not refresh_token:
            raise ValueError(f"No refresh token found for region {region}")
        
        response = requests.post(
            self.LWA_TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.status_code} - {response.text}")
        
        data = response.json()
        access_token = data['access_token']
        expires_in = data.get('expires_in', 3600)  # Default 1 hour
        
        return TokenInfo(
            access_token=access_token,
            expires_at=time.time() + expires_in
        )
    
    def invalidate(self, region: str):
        """Force token refresh on next request."""
        with self._locks[region]:
            if region in self._tokens:
                del self._tokens[region]


# Global singleton instance
_token_manager: Optional[TokenManager] = None

def get_token_manager() -> TokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
```

### 2.3 Region & Marketplace Mapping

```python
# File: src/config/marketplaces.py

from dataclasses import dataclass
from enum import Enum

class Region(Enum):
    NA = "NA"  # North America
    EU = "EU"  # Europe
    FE = "FE"  # Far East

@dataclass
class Marketplace:
    marketplace_id: str
    country_code: str
    name: str
    region: Region
    endpoint: str
    currency: str

# Chalkola's active marketplaces
MARKETPLACES = {
    # North America
    'US': Marketplace(
        marketplace_id='ATVPDKIKX0DER',
        country_code='US',
        name='United States',
        region=Region.NA,
        endpoint='https://sellingpartnerapi-na.amazon.com',
        currency='USD'
    ),
    'CA': Marketplace(
        marketplace_id='A2EUQ1WTGCTBG2',
        country_code='CA',
        name='Canada',
        region=Region.NA,
        endpoint='https://sellingpartnerapi-na.amazon.com',
        currency='CAD'
    ),
    
    # Europe
    'UK': Marketplace(
        marketplace_id='A1F83G8C2ARO7P',
        country_code='GB',
        name='United Kingdom',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='GBP'
    ),
    'DE': Marketplace(
        marketplace_id='A1PA6795UKMFR9',
        country_code='DE',
        name='Germany',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='EUR'
    ),
    'FR': Marketplace(
        marketplace_id='A13V1IB3VIYZZH',
        country_code='FR',
        name='France',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='EUR'
    ),
    'IT': Marketplace(
        marketplace_id='APJ6JRA9NG5V4',
        country_code='IT',
        name='Italy',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='EUR'
    ),
    'ES': Marketplace(
        marketplace_id='A1RKKUPIHCS9HS',
        country_code='ES',
        name='Spain',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='EUR'
    ),
    'UAE': Marketplace(
        marketplace_id='A2VIGQ35RCS4UG',
        country_code='AE',
        name='United Arab Emirates',
        region=Region.EU,
        endpoint='https://sellingpartnerapi-eu.amazon.com',
        currency='AED'
    ),
    
    # Far East
    'AU': Marketplace(
        marketplace_id='A39IBJ37TRP1C6',
        country_code='AU',
        name='Australia',
        region=Region.FE,
        endpoint='https://sellingpartnerapi-fe.amazon.com',
        currency='AUD'
    ),
    'JP': Marketplace(
        marketplace_id='A1VC38T7YXB528',
        country_code='JP',
        name='Japan',
        region=Region.FE,
        endpoint='https://sellingpartnerapi-fe.amazon.com',
        currency='JPY'
    ),
}

def get_marketplace(country_code: str) -> Marketplace:
    """Get marketplace by country code (US, UK, DE, etc.)"""
    if country_code not in MARKETPLACES:
        raise ValueError(f"Unknown marketplace: {country_code}")
    return MARKETPLACES[country_code]

def get_marketplaces_by_region(region: Region) -> list[Marketplace]:
    """Get all marketplaces in a region."""
    return [m for m in MARKETPLACES.values() if m.region == region]
```

---

## 3. Project Structure

### 3.1 Recommended Directory Structure

```
chalkola-sp-api/
├── .env                          # Environment variables (NEVER COMMIT)
├── .env.example                  # Template for env vars
├── .gitignore
├── requirements.txt
├── pyproject.toml
├── README.md
│
├── src/
│   ├── __init__.py
│   │
│   ├── auth/
│   │   ├── __init__.py
│   │   └── token_manager.py      # LWA token management
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── marketplaces.py       # Marketplace definitions
│   │   └── settings.py           # App configuration
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── base_client.py        # Base SP-API client
│   │   ├── reports_api.py        # Reports API (SQP, etc.)
│   │   ├── fba_inbound_api.py    # Fulfillment Inbound API
│   │   ├── inventory_api.py      # FBA Inventory API
│   │   └── awd_api.py            # AWD API
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── fba_shipment_service.py   # FBA shipment orchestration
│   │   ├── sqp_service.py            # SQP report service
│   │   └── inventory_service.py      # Inventory sync service
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── shipment.py           # Shipment data models
│   │   ├── sqp.py                # SQP data models
│   │   └── inventory.py          # Inventory models
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py         # Supabase connection
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── shipment_repo.py
│   │   │   ├── sqp_repo.py
│   │   │   └── inventory_repo.py
│   │   └── migrations/
│   │       └── 001_initial_schema.sql
│   │
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── sqp_weekly_pull.py    # Weekly SQP job
│   │   ├── sqp_monthly_pull.py   # Monthly SQP job
│   │   └── inventory_sync.py     # Inventory sync job
│   │
│   └── utils/
│       ├── __init__.py
│       ├── retry.py              # Retry with backoff
│       ├── logging.py            # Logging setup
│       └── date_utils.py         # Date alignment helpers
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py               # Pytest fixtures
│   ├── test_auth/
│   ├── test_api/
│   └── test_services/
│
├── scripts/
│   ├── setup_database.py         # Run migrations
│   ├── test_connection.py        # Test SP-API connection
│   └── manual_sqp_pull.py        # Manual SQP trigger
│
└── docker/
    ├── Dockerfile
    └── docker-compose.yml
```

### 3.2 Requirements

```txt
# requirements.txt

# HTTP & API
requests>=2.31.0
httpx>=0.25.0
urllib3>=2.0.0

# AWS (for request signing if needed)
boto3>=1.34.0

# Database
psycopg2-binary>=2.9.9
supabase>=2.3.0

# Data Processing
pandas>=2.1.0
python-calamine>=0.2.0    # Fast Excel reading
xlsxwriter>=3.1.0         # Excel writing

# Scheduling
apscheduler>=3.10.0

# Utilities
python-dotenv>=1.0.0
pydantic>=2.5.0
tenacity>=8.2.0           # Retry library

# Logging & Monitoring
structlog>=23.2.0
sentry-sdk>=1.38.0

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
responses>=0.24.0         # Mock HTTP requests

# Type Checking
mypy>=1.7.0
types-requests>=2.31.0
```

---

## 4. Core API Client

### 4.1 Base Client with Retry Logic

```python
# File: src/api/base_client.py

import time
import gzip
import json
import requests
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum
import structlog

from src.auth.token_manager import get_token_manager
from src.config.marketplaces import Marketplace, Region

logger = structlog.get_logger()

class HttpMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"

@dataclass
class APIResponse:
    status_code: int
    data: Optional[dict | list]
    headers: dict
    raw_content: Optional[bytes] = None

class SPAPIError(Exception):
    """Base exception for SP-API errors."""
    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{status_code}] {error_code}: {message}")

class ThrottlingError(SPAPIError):
    """Rate limit exceeded."""
    pass

class SPAPIClient:
    """
    Base client for SP-API requests.
    Handles authentication, retries, and error handling.
    """
    
    # Rate limit configuration
    MAX_RETRIES = 5
    BASE_DELAY = 1.0
    MAX_DELAY = 60.0
    
    def __init__(self, marketplace: Marketplace):
        self.marketplace = marketplace
        self.base_url = marketplace.endpoint
        self.token_manager = get_token_manager()
    
    def _get_headers(self) -> dict:
        """Build request headers with auth token."""
        region = self.marketplace.region.value
        access_token = self.token_manager.get_access_token(region)
        
        return {
            'Authorization': f'Bearer {access_token}',
            'x-amz-access-token': access_token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
    
    def _calculate_backoff(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """Calculate exponential backoff delay."""
        if retry_after:
            return float(retry_after)
        
        import random
        delay = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
        jitter = random.uniform(0, 1)
        return delay + jitter
    
    def request(
        self,
        method: HttpMethod,
        path: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ) -> APIResponse:
        """
        Make authenticated request to SP-API with retry logic.
        
        Args:
            method: HTTP method
            path: API path (e.g., '/reports/2021-06-30/reports')
            params: Query parameters
            body: Request body (will be JSON serialized)
            extra_headers: Additional headers
            
        Returns:
            APIResponse with status, data, and headers
            
        Raises:
            SPAPIError: For non-retryable errors
            ThrottlingError: If retries exhausted
        """
        url = f"{self.base_url}{path}"
        
        for attempt in range(self.MAX_RETRIES):
            try:
                headers = self._get_headers()
                if extra_headers:
                    headers.update(extra_headers)
                
                logger.debug(
                    "SP-API request",
                    method=method.value,
                    path=path,
                    attempt=attempt + 1,
                    marketplace=self.marketplace.country_code
                )
                
                response = requests.request(
                    method=method.value,
                    url=url,
                    headers=headers,
                    params=params,
                    json=body,
                    timeout=30,
                )
                
                # Success
                if response.status_code in (200, 201, 202):
                    data = None
                    if response.content:
                        try:
                            data = response.json()
                        except json.JSONDecodeError:
                            pass
                    
                    return APIResponse(
                        status_code=response.status_code,
                        data=data,
                        headers=dict(response.headers),
                        raw_content=response.content,
                    )
                
                # Rate limited - retry with backoff
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    delay = self._calculate_backoff(
                        attempt,
                        int(retry_after) if retry_after else None
                    )
                    
                    logger.warning(
                        "Rate limited, retrying",
                        delay=delay,
                        attempt=attempt + 1,
                        path=path
                    )
                    
                    time.sleep(delay)
                    continue
                
                # Server error - retry
                if response.status_code >= 500:
                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        "Server error, retrying",
                        status_code=response.status_code,
                        delay=delay,
                        attempt=attempt + 1
                    )
                    time.sleep(delay)
                    continue
                
                # Client error - don't retry
                error_data = response.json() if response.content else {}
                errors = error_data.get('errors', [{}])
                error = errors[0] if errors else {}
                
                raise SPAPIError(
                    status_code=response.status_code,
                    error_code=error.get('code', 'UNKNOWN'),
                    message=error.get('message', response.text)
                )
                
            except requests.exceptions.Timeout:
                delay = self._calculate_backoff(attempt)
                logger.warning("Request timeout, retrying", delay=delay)
                time.sleep(delay)
                continue
                
            except requests.exceptions.ConnectionError:
                delay = self._calculate_backoff(attempt)
                logger.warning("Connection error, retrying", delay=delay)
                time.sleep(delay)
                continue
        
        raise ThrottlingError(
            status_code=429,
            error_code='THROTTLING',
            message=f'Max retries ({self.MAX_RETRIES}) exceeded'
        )
    
    def get(self, path: str, params: Optional[dict] = None) -> APIResponse:
        return self.request(HttpMethod.GET, path, params=params)
    
    def post(self, path: str, body: Optional[dict] = None) -> APIResponse:
        return self.request(HttpMethod.POST, path, body=body)
    
    def put(self, path: str, body: Optional[dict] = None) -> APIResponse:
        return self.request(HttpMethod.PUT, path, body=body)
    
    def delete(self, path: str) -> APIResponse:
        return self.request(HttpMethod.DELETE, path)
```

### 4.2 Reports API Client

```python
# File: src/api/reports_api.py

import time
import gzip
import json
import requests
from typing import Optional
from datetime import datetime, date
from enum import Enum
import structlog

from src.api.base_client import SPAPIClient, APIResponse
from src.config.marketplaces import Marketplace

logger = structlog.get_logger()

class ReportType(Enum):
    # Brand Analytics
    SQP = "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"
    MARKET_BASKET = "GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT"
    REPEAT_PURCHASE = "GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT"
    
    # Business Reports
    SALES_TRAFFIC = "GET_SALES_AND_TRAFFIC_REPORT"
    
    # Inventory
    FBA_INVENTORY = "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA"
    RESTOCK_INVENTORY = "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT"
    
    # Listings
    ALL_LISTINGS = "GET_MERCHANT_LISTINGS_ALL_DATA"

class ReportStatus(Enum):
    IN_QUEUE = "IN_QUEUE"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    FATAL = "FATAL"

class ReportsAPIClient(SPAPIClient):
    """
    Client for SP-API Reports API.
    Handles async report generation workflow.
    """
    
    REPORTS_PATH = "/reports/2021-06-30"
    
    # Polling configuration
    POLL_INTERVAL = 30  # seconds
    MAX_POLL_TIME = 600  # 10 minutes
    
    def create_report(
        self,
        report_type: ReportType,
        data_start_time: Optional[datetime] = None,
        data_end_time: Optional[datetime] = None,
        report_options: Optional[dict] = None,
    ) -> str:
        """
        Create a new report request.
        
        Args:
            report_type: Type of report to generate
            data_start_time: Start of data range
            data_end_time: End of data range
            report_options: Additional options (e.g., ASINs for SQP)
            
        Returns:
            Report ID string
        """
        body = {
            "reportType": report_type.value,
            "marketplaceIds": [self.marketplace.marketplace_id],
        }
        
        if data_start_time:
            body["dataStartTime"] = data_start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if data_end_time:
            body["dataEndTime"] = data_end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if report_options:
            body["reportOptions"] = report_options
        
        logger.info(
            "Creating report",
            report_type=report_type.value,
            marketplace=self.marketplace.country_code
        )
        
        response = self.post(f"{self.REPORTS_PATH}/reports", body=body)
        return response.data["reportId"]
    
    def get_report(self, report_id: str) -> dict:
        """Get report status and details."""
        response = self.get(f"{self.REPORTS_PATH}/reports/{report_id}")
        return response.data
    
    def get_report_document(self, document_id: str) -> dict:
        """
        Get report document download URL.
        URL expires in 5 minutes!
        """
        response = self.get(f"{self.REPORTS_PATH}/documents/{document_id}")
        return response.data
    
    def download_report(self, document_id: str) -> dict | list:
        """
        Download and decompress report document.
        
        Returns:
            Parsed JSON data from report
        """
        # Get download URL
        doc_info = self.get_report_document(document_id)
        url = doc_info["url"]
        compression = doc_info.get("compressionAlgorithm")
        
        logger.info("Downloading report document", document_id=document_id)
        
        # Download content
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        content = response.content
        
        # Decompress if needed
        if compression == "GZIP":
            content = gzip.decompress(content)
        
        # Parse JSON
        return json.loads(content)
    
    def wait_for_report(self, report_id: str) -> str:
        """
        Poll until report is ready.
        
        Args:
            report_id: Report ID to poll
            
        Returns:
            Report document ID when ready
            
        Raises:
            Exception: If report fails or times out
        """
        start_time = time.time()
        
        while (time.time() - start_time) < self.MAX_POLL_TIME:
            report = self.get_report(report_id)
            status = ReportStatus(report["processingStatus"])
            
            logger.debug(
                "Report status",
                report_id=report_id,
                status=status.value
            )
            
            if status == ReportStatus.DONE:
                return report["reportDocumentId"]
            
            if status in (ReportStatus.CANCELLED, ReportStatus.FATAL):
                raise Exception(f"Report {report_id} failed with status: {status.value}")
            
            time.sleep(self.POLL_INTERVAL)
        
        raise TimeoutError(f"Report {report_id} timed out after {self.MAX_POLL_TIME}s")
    
    def create_and_download_report(
        self,
        report_type: ReportType,
        data_start_time: Optional[datetime] = None,
        data_end_time: Optional[datetime] = None,
        report_options: Optional[dict] = None,
    ) -> dict | list:
        """
        Convenience method: create report, wait, and download.
        
        Returns:
            Parsed report data
        """
        # Create
        report_id = self.create_report(
            report_type=report_type,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            report_options=report_options,
        )
        
        # Wait
        document_id = self.wait_for_report(report_id)
        
        # Download
        return self.download_report(document_id)
```

---

## 5. FBA Shipment Automation

### 5.1 FBA Inbound API Client

```python
# File: src/api/fba_inbound_api.py

from typing import Optional
from dataclasses import dataclass
from enum import Enum
import time
import structlog

from src.api.base_client import SPAPIClient, APIResponse
from src.config.marketplaces import Marketplace

logger = structlog.get_logger()

class OperationStatus(Enum):
    SUCCESS = "SUCCESS"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"

@dataclass
class SourceAddress:
    name: str
    address_line_1: str
    city: str
    state_or_province: str
    postal_code: str
    country_code: str
    address_line_2: Optional[str] = None
    
    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "addressLine1": self.address_line_1,
            "city": self.city,
            "stateOrProvinceCode": self.state_or_province,
            "postalCode": self.postal_code,
            "countryCode": self.country_code,
        }
        if self.address_line_2:
            result["addressLine2"] = self.address_line_2
        return result

@dataclass
class InboundItem:
    msku: str
    quantity: int
    label_owner: str = "SELLER"  # SELLER or AMAZON
    prep_owner: str = "SELLER"   # SELLER or AMAZON
    
    def to_dict(self) -> dict:
        return {
            "msku": self.msku,
            "quantity": self.quantity,
            "labelOwner": self.label_owner,
            "prepOwner": self.prep_owner,
        }

@dataclass
class BoxDimensions:
    length: float
    width: float
    height: float
    unit: str = "IN"  # IN or CM
    
    def to_dict(self) -> dict:
        return {
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "unitOfMeasurement": self.unit,
        }

@dataclass
class BoxWeight:
    value: float
    unit: str = "LB"  # LB or KG
    
    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
        }

@dataclass
class Box:
    dimensions: BoxDimensions
    weight: BoxWeight
    items: list[InboundItem]
    quantity: int = 1
    
    def to_dict(self) -> dict:
        return {
            "contentInformationSource": "BOX_CONTENT_PROVIDED",
            "dimensions": self.dimensions.to_dict(),
            "weight": self.weight.to_dict(),
            "quantity": self.quantity,
            "items": [item.to_dict() for item in self.items],
        }


class FBAInboundAPIClient(SPAPIClient):
    """
    Client for Fulfillment Inbound API v2024-03-20.
    Implements complete 16-step shipment workflow.
    """
    
    BASE_PATH = "/inbound/fba/2024-03-20"
    OPERATIONS_PATH = "/operations"
    V0_PATH = "/fba/inbound/v0"  # For labels
    
    POLL_INTERVAL = 5  # seconds
    MAX_POLL_TIME = 300  # 5 minutes
    
    # ========================================
    # OPERATION POLLING
    # ========================================
    
    def poll_operation(self, operation_id: str) -> dict:
        """
        Poll async operation until complete.
        
        Returns:
            Operation result when SUCCESS
            
        Raises:
            Exception on FAILED status or timeout
        """
        start_time = time.time()
        
        while (time.time() - start_time) < self.MAX_POLL_TIME:
            response = self.get(f"{self.OPERATIONS_PATH}/{operation_id}")
            operation = response.data
            status = OperationStatus(operation["operationStatus"])
            
            logger.debug(
                "Operation status",
                operation_id=operation_id,
                status=status.value
            )
            
            if status == OperationStatus.SUCCESS:
                return operation
            
            if status == OperationStatus.FAILED:
                problems = operation.get("operationProblems", [])
                raise Exception(f"Operation {operation_id} failed: {problems}")
            
            time.sleep(self.POLL_INTERVAL)
        
        raise TimeoutError(f"Operation {operation_id} timed out")
    
    # ========================================
    # PHASE 1: CREATE INBOUND PLAN
    # ========================================
    
    def create_inbound_plan(
        self,
        source_address: SourceAddress,
        items: list[InboundItem],
        name: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Step 1: Create inbound plan.
        
        Args:
            source_address: Ship-from address
            items: List of items with quantities
            name: Optional plan name
            
        Returns:
            Tuple of (inbound_plan_id, operation_id)
        """
        body = {
            "destinationMarketplaces": [self.marketplace.marketplace_id],
            "sourceAddress": source_address.to_dict(),
            "items": [item.to_dict() for item in items],
        }
        
        if name:
            body["name"] = name
        
        logger.info(
            "Creating inbound plan",
            item_count=len(items),
            marketplace=self.marketplace.country_code
        )
        
        response = self.post(f"{self.BASE_PATH}/inboundPlans", body=body)
        
        return (
            response.data["inboundPlanId"],
            response.data["operationId"]
        )
    
    def create_inbound_plan_and_wait(
        self,
        source_address: SourceAddress,
        items: list[InboundItem],
        name: Optional[str] = None,
    ) -> str:
        """
        Steps 1-2: Create plan and wait for completion.
        
        Returns:
            inbound_plan_id
        """
        plan_id, operation_id = self.create_inbound_plan(
            source_address, items, name
        )
        
        self.poll_operation(operation_id)
        
        logger.info("Inbound plan created", plan_id=plan_id)
        return plan_id
    
    # ========================================
    # PHASE 2: PACKING CONFIGURATION
    # ========================================
    
    def generate_packing_options(self, plan_id: str) -> str:
        """Step 3: Generate packing options."""
        response = self.post(f"{self.BASE_PATH}/inboundPlans/{plan_id}/packingOptions")
        return response.data["operationId"]
    
    def list_packing_options(self, plan_id: str) -> list[dict]:
        """Step 4: List available packing options."""
        response = self.get(f"{self.BASE_PATH}/inboundPlans/{plan_id}/packingOptions")
        return response.data.get("packingOptions", [])
    
    def list_packing_group_items(self, plan_id: str, packing_group_id: str) -> list[dict]:
        """Step 5: Get items in a packing group."""
        response = self.get(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/packingGroups/{packing_group_id}/items"
        )
        return response.data.get("items", [])
    
    def confirm_packing_option(self, plan_id: str, packing_option_id: str) -> str:
        """Step 6: Confirm selected packing option."""
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/packingOptions/{packing_option_id}/confirmation"
        )
        return response.data["operationId"]
    
    def set_packing_information(
        self,
        plan_id: str,
        packing_group_id: str,
        boxes: list[Box],
    ) -> str:
        """
        Step 7: Set box contents, dimensions, weights.
        
        Args:
            plan_id: Inbound plan ID
            packing_group_id: Packing group to set info for
            boxes: List of boxes with contents
            
        Returns:
            Operation ID
        """
        body = {
            "packageGroupings": [{
                "packingGroupId": packing_group_id,
                "boxes": [box.to_dict() for box in boxes],
            }]
        }
        
        logger.info(
            "Setting packing information",
            plan_id=plan_id,
            box_count=len(boxes)
        )
        
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/packingInformation",
            body=body
        )
        return response.data["operationId"]
    
    # ========================================
    # PHASE 3: PLACEMENT OPTIONS
    # ========================================
    
    def generate_placement_options(self, plan_id: str) -> str:
        """Step 8: Generate placement options (FC assignments)."""
        response = self.post(f"{self.BASE_PATH}/inboundPlans/{plan_id}/placementOptions")
        return response.data["operationId"]
    
    def list_placement_options(self, plan_id: str) -> list[dict]:
        """
        Step 9: List placement options.
        
        Returns options like:
        - Amazon-optimized (4+ FCs, no fee)
        - Partial splits (2-3 FCs, reduced fee)
        - Minimal splits (~1 FC, highest fee)
        """
        response = self.get(f"{self.BASE_PATH}/inboundPlans/{plan_id}/placementOptions")
        return response.data.get("placementOptions", [])
    
    # ========================================
    # PHASE 4: TRANSPORTATION
    # ========================================
    
    def generate_transportation_options(
        self,
        plan_id: str,
        placement_option_id: str,
        ready_to_ship_date: str,  # ISO format: 2026-02-15T00:00:00Z
    ) -> str:
        """Step 10: Generate transportation options."""
        
        # Get shipment IDs from placement option
        placement_options = self.list_placement_options(plan_id)
        selected = next(
            (p for p in placement_options if p["placementOptionId"] == placement_option_id),
            None
        )
        
        if not selected:
            raise ValueError(f"Placement option {placement_option_id} not found")
        
        shipment_configs = []
        for shipment_id in selected.get("shipmentIds", []):
            shipment_configs.append({
                "shipmentId": shipment_id,
                "readyToShipWindow": {"start": ready_to_ship_date}
            })
        
        body = {
            "placementOptionId": placement_option_id,
            "shipmentTransportationConfigurations": shipment_configs,
        }
        
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/transportationOptions",
            body=body
        )
        return response.data["operationId"]
    
    def list_transportation_options(self, plan_id: str) -> list[dict]:
        """
        Step 11: List transportation options.
        
        Returns carrier quotes (UPS, FedEx, etc.), shipping modes (SPD, LTL).
        """
        response = self.get(f"{self.BASE_PATH}/inboundPlans/{plan_id}/transportationOptions")
        return response.data.get("transportationOptions", [])
    
    def confirm_placement_option(self, plan_id: str, placement_option_id: str) -> str:
        """
        Step 12: Confirm placement option.
        
        After this, shipmentIds are finalized.
        """
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/placementOptions/{placement_option_id}/confirmation"
        )
        return response.data["operationId"]
    
    # ========================================
    # PHASE 5: DELIVERY & CONFIRMATION
    # ========================================
    
    def generate_delivery_window_options(self, plan_id: str, shipment_id: str) -> str:
        """Step 13: Generate delivery window options for a shipment."""
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/shipments/{shipment_id}/deliveryWindowOptions"
        )
        return response.data["operationId"]
    
    def list_delivery_window_options(self, plan_id: str, shipment_id: str) -> list[dict]:
        """List available delivery windows."""
        response = self.get(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/shipments/{shipment_id}/deliveryWindowOptions"
        )
        return response.data.get("deliveryWindowOptions", [])
    
    def confirm_delivery_window(
        self,
        plan_id: str,
        shipment_id: str,
        delivery_window_id: str,
    ) -> str:
        """Step 14: Confirm delivery window."""
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/shipments/{shipment_id}"
            f"/deliveryWindowOptions/{delivery_window_id}/confirmation"
        )
        return response.data["operationId"]
    
    def confirm_transportation_options(
        self,
        plan_id: str,
        transportation_selections: list[dict],  # [{shipmentId, transportationOptionId}]
    ) -> str:
        """
        Step 15: Confirm transportation for all shipments.
        
        Args:
            plan_id: Inbound plan ID
            transportation_selections: List of {shipmentId, transportationOptionId}
            
        Returns:
            Operation ID
        """
        body = {
            "transportationSelections": transportation_selections
        }
        
        response = self.post(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/transportationOptions/confirmation",
            body=body
        )
        return response.data["operationId"]
    
    # ========================================
    # PHASE 6: LABELS (V0 API)
    # ========================================
    
    def get_labels(
        self,
        shipment_id: str,
        page_type: str = "PackageLabel_Letter_4",
        label_type: str = "BARCODE_2D",
    ) -> str:
        """
        Step 16: Get box and shipping labels.
        
        Uses V0 API (not deprecated).
        
        Args:
            shipment_id: Shipment confirmation ID (e.g., FBA1234ABCD)
            page_type: Label format
            label_type: BARCODE_2D or UNIQUE
            
        Returns:
            Download URL for label PDF
        """
        params = {
            "PageType": page_type,
            "LabelType": label_type,
        }
        
        response = self.get(
            f"{self.V0_PATH}/shipments/{shipment_id}/labels",
            params=params
        )
        
        return response.data.get("DownloadURL")
    
    def get_fnsku_labels(
        self,
        msku_quantities: dict[str, int],
        page_type: str = "PackageLabel_Letter_6",
    ) -> str:
        """
        Get FNSKU item labels.
        
        Args:
            msku_quantities: Dict of {msku: quantity}
            page_type: Label format
            
        Returns:
            Download URL for label PDF
        """
        body = {
            "marketplaceId": self.marketplace.marketplace_id,
            "mskuQuantities": [
                {"msku": msku, "quantity": qty}
                for msku, qty in msku_quantities.items()
            ],
            "pageType": page_type,
        }
        
        response = self.post(f"{self.BASE_PATH}/items/labels", body=body)
        return response.data.get("downloadURL")
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    def get_shipment(self, plan_id: str, shipment_id: str) -> dict:
        """Get shipment details including destination FC address."""
        response = self.get(
            f"{self.BASE_PATH}/inboundPlans/{plan_id}/shipments/{shipment_id}"
        )
        return response.data
    
    def list_shipments(self, plan_id: str) -> list[dict]:
        """List all shipments in an inbound plan."""
        response = self.get(f"{self.BASE_PATH}/inboundPlans/{plan_id}/shipments")
        return response.data.get("shipments", [])
```

### 5.2 FBA Shipment Service (Orchestration)

```python
# File: src/services/fba_shipment_service.py

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
import structlog

from src.api.fba_inbound_api import (
    FBAInboundAPIClient,
    SourceAddress,
    InboundItem,
    Box,
    BoxDimensions,
    BoxWeight,
)
from src.config.marketplaces import Marketplace, get_marketplace
from src.db.repositories.shipment_repo import ShipmentRepository

logger = structlog.get_logger()

@dataclass
class ShipmentRequest:
    """Input for creating a shipment."""
    marketplace_code: str  # US, UK, DE, etc.
    source_address: SourceAddress
    items: list[InboundItem]
    boxes: list[Box]
    name: Optional[str] = None
    ready_to_ship_days: int = 7  # Days from now

@dataclass
class PlacementOption:
    """Processed placement option for display."""
    placement_option_id: str
    fc_count: int
    shipment_ids: list[str]
    fee_per_unit: Optional[float]
    fee_currency: Optional[str]
    description: str

@dataclass
class TransportationOption:
    """Processed transportation option for display."""
    transportation_option_id: str
    shipment_id: str
    carrier_name: str
    shipping_mode: str  # GROUND_SMALL_PARCEL, FREIGHT_LTL, etc.
    shipping_solution: str  # AMAZON_PARTNERED_CARRIER, USE_YOUR_OWN_CARRIER
    cost: Optional[float]
    cost_currency: Optional[str]

@dataclass
class CompletedShipment:
    """Result of completed shipment creation."""
    inbound_plan_id: str
    shipments: list[dict]  # Each with shipmentId, destination, labels_url
    total_units: int
    total_boxes: int


class FBAShipmentService:
    """
    Orchestrates the complete FBA shipment creation workflow.
    Integrates with existing FBA Shipment System v5.5.8.
    """
    
    def __init__(self, shipment_repo: ShipmentRepository):
        self.shipment_repo = shipment_repo
        self._clients: dict[str, FBAInboundAPIClient] = {}
    
    def _get_client(self, marketplace_code: str) -> FBAInboundAPIClient:
        """Get or create API client for marketplace."""
        if marketplace_code not in self._clients:
            marketplace = get_marketplace(marketplace_code)
            self._clients[marketplace_code] = FBAInboundAPIClient(marketplace)
        return self._clients[marketplace_code]
    
    # ========================================
    # STEP 1: CREATE PLAN
    # ========================================
    
    async def create_plan(self, request: ShipmentRequest) -> str:
        """
        Phase 1: Create inbound plan and get packing options.
        
        Returns:
            inbound_plan_id
        """
        client = self._get_client(request.marketplace_code)
        
        logger.info(
            "Creating FBA shipment plan",
            marketplace=request.marketplace_code,
            items=len(request.items),
            boxes=len(request.boxes)
        )
        
        # Step 1-2: Create plan and wait
        plan_id = client.create_inbound_plan_and_wait(
            source_address=request.source_address,
            items=request.items,
            name=request.name,
        )
        
        # Save to database
        await self.shipment_repo.create_shipment(
            inbound_plan_id=plan_id,
            marketplace_id=get_marketplace(request.marketplace_code).marketplace_id,
            status="PLAN_CREATED",
            total_units=sum(item.quantity for item in request.items),
            total_boxes=len(request.boxes),
        )
        
        return plan_id
    
    # ========================================
    # STEP 2: CONFIGURE PACKING
    # ========================================
    
    async def configure_packing(
        self,
        marketplace_code: str,
        plan_id: str,
        boxes: list[Box],
    ) -> str:
        """
        Phase 2: Configure packing options.
        
        Returns:
            packing_group_id
        """
        client = self._get_client(marketplace_code)
        
        # Step 3: Generate packing options
        operation_id = client.generate_packing_options(plan_id)
        client.poll_operation(operation_id)
        
        # Step 4: List options
        packing_options = client.list_packing_options(plan_id)
        
        if not packing_options:
            raise Exception("No packing options available")
        
        # Use first option (typically "seller-provided packing")
        selected_option = packing_options[0]
        packing_option_id = selected_option["packingOptionId"]
        packing_groups = selected_option.get("packingGroups", [])
        
        if not packing_groups:
            raise Exception("No packing groups in option")
        
        packing_group_id = packing_groups[0]["packingGroupId"]
        
        # Step 6: Confirm packing option
        operation_id = client.confirm_packing_option(plan_id, packing_option_id)
        client.poll_operation(operation_id)
        
        # Step 7: Set box contents
        operation_id = client.set_packing_information(
            plan_id=plan_id,
            packing_group_id=packing_group_id,
            boxes=boxes,
        )
        client.poll_operation(operation_id)
        
        # Update database
        await self.shipment_repo.update_status(plan_id, "PACKING_CONFIGURED")
        
        return packing_group_id
    
    # ========================================
    # STEP 3: GET PLACEMENT OPTIONS
    # ========================================
    
    async def get_placement_options(
        self,
        marketplace_code: str,
        plan_id: str,
    ) -> list[PlacementOption]:
        """
        Phase 3: Generate and return placement options for user selection.
        
        User must choose based on fee vs. FC split tradeoff.
        """
        client = self._get_client(marketplace_code)
        
        # Step 8: Generate placement options
        operation_id = client.generate_placement_options(plan_id)
        client.poll_operation(operation_id)
        
        # Step 9: List options
        raw_options = client.list_placement_options(plan_id)
        
        # Process for display
        options = []
        for opt in raw_options:
            shipment_ids = opt.get("shipmentIds", [])
            fc_count = len(shipment_ids)
            
            # Parse fees
            fees = opt.get("fees", [])
            fee_per_unit = None
            fee_currency = None
            for fee in fees:
                if fee.get("type") == "PLACEMENT":
                    fee_per_unit = fee.get("perUnitAmount", {}).get("amount")
                    fee_currency = fee.get("perUnitAmount", {}).get("code")
            
            # Generate description
            if fc_count >= 4:
                description = f"Amazon-optimized ({fc_count} FCs) - No placement fee"
            elif fc_count >= 2:
                description = f"Partial split ({fc_count} FCs) - Reduced fee"
            else:
                description = f"Minimal split ({fc_count} FC) - Higher fee"
            
            options.append(PlacementOption(
                placement_option_id=opt["placementOptionId"],
                fc_count=fc_count,
                shipment_ids=shipment_ids,
                fee_per_unit=fee_per_unit,
                fee_currency=fee_currency,
                description=description,
            ))
        
        logger.info(
            "Placement options generated",
            plan_id=plan_id,
            option_count=len(options)
        )
        
        return options
    
    # ========================================
    # STEP 4: CONFIRM PLACEMENT & TRANSPORTATION
    # ========================================
    
    async def confirm_placement_and_transportation(
        self,
        marketplace_code: str,
        plan_id: str,
        placement_option_id: str,
        ready_to_ship_date: datetime,
    ) -> list[TransportationOption]:
        """
        Steps 10-12: Generate transportation options after confirming placement.
        
        Returns transportation options for user to review/confirm.
        """
        client = self._get_client(marketplace_code)
        
        # Step 10: Generate transportation options
        operation_id = client.generate_transportation_options(
            plan_id=plan_id,
            placement_option_id=placement_option_id,
            ready_to_ship_date=ready_to_ship_date.strftime("%Y-%m-%dT00:00:00Z"),
        )
        client.poll_operation(operation_id)
        
        # Step 11: List transportation options
        raw_options = client.list_transportation_options(plan_id)
        
        # Step 12: Confirm placement
        operation_id = client.confirm_placement_option(plan_id, placement_option_id)
        client.poll_operation(operation_id)
        
        # Update database
        await self.shipment_repo.update_placement(
            plan_id, placement_option_id
        )
        
        # Process transportation options for display
        options = []
        for opt in raw_options:
            quote = opt.get("quote", {})
            cost_info = quote.get("cost", {})
            
            options.append(TransportationOption(
                transportation_option_id=opt["transportationOptionId"],
                shipment_id=opt["shipmentId"],
                carrier_name=opt.get("carrier", {}).get("name", "Unknown"),
                shipping_mode=opt.get("shippingMode", "Unknown"),
                shipping_solution=opt.get("shippingSolution", "Unknown"),
                cost=cost_info.get("amount"),
                cost_currency=cost_info.get("code"),
            ))
        
        return options
    
    # ========================================
    # STEP 5: FINALIZE SHIPMENT
    # ========================================
    
    async def finalize_shipment(
        self,
        marketplace_code: str,
        plan_id: str,
        transportation_selections: list[dict],  # [{shipmentId, transportationOptionId}]
    ) -> CompletedShipment:
        """
        Steps 13-16: Confirm delivery windows, transportation, and get labels.
        
        Args:
            marketplace_code: e.g., 'US'
            plan_id: Inbound plan ID
            transportation_selections: Transportation choice per shipment
            
        Returns:
            CompletedShipment with all shipment details and label URLs
        """
        client = self._get_client(marketplace_code)
        
        # Get shipments
        shipments = client.list_shipments(plan_id)
        completed_shipments = []
        
        for shipment in shipments:
            shipment_id = shipment["shipmentId"]
            
            # Step 13: Generate delivery windows
            operation_id = client.generate_delivery_window_options(plan_id, shipment_id)
            client.poll_operation(operation_id)
            
            # Get first available window
            windows = client.list_delivery_window_options(plan_id, shipment_id)
            if windows:
                window_id = windows[0]["deliveryWindowOptionId"]
                
                # Step 14: Confirm delivery window
                operation_id = client.confirm_delivery_window(
                    plan_id, shipment_id, window_id
                )
                client.poll_operation(operation_id)
        
        # Step 15: Confirm all transportation
        operation_id = client.confirm_transportation_options(
            plan_id, transportation_selections
        )
        client.poll_operation(operation_id)
        
        # Step 16: Get labels for each shipment
        for shipment in shipments:
            shipment_id = shipment["shipmentId"]
            shipment_confirmation_id = shipment.get("shipmentConfirmationId")
            
            if shipment_confirmation_id:
                labels_url = client.get_labels(shipment_confirmation_id)
            else:
                labels_url = None
            
            # Get destination details
            shipment_details = client.get_shipment(plan_id, shipment_id)
            
            completed_shipments.append({
                "shipmentId": shipment_id,
                "shipmentConfirmationId": shipment_confirmation_id,
                "destination": shipment_details.get("destination", {}),
                "labels_url": labels_url,
            })
        
        # Update database
        await self.shipment_repo.update_shipments(plan_id, completed_shipments)
        await self.shipment_repo.update_status(plan_id, "COMPLETED")
        
        # Calculate totals
        total_units = sum(s.get("itemQuantity", 0) for s in shipments)
        total_boxes = sum(s.get("boxQuantity", 0) for s in shipments)
        
        logger.info(
            "FBA shipment completed",
            plan_id=plan_id,
            shipment_count=len(completed_shipments)
        )
        
        return CompletedShipment(
            inbound_plan_id=plan_id,
            shipments=completed_shipments,
            total_units=total_units,
            total_boxes=total_boxes,
        )


# ========================================
# EXAMPLE USAGE
# ========================================

async def create_shipment_example():
    """Example: Create a complete FBA shipment."""
    from src.db.repositories.shipment_repo import ShipmentRepository
    from src.db.connection import get_db_connection
    
    # Initialize
    db = get_db_connection()
    repo = ShipmentRepository(db)
    service = FBAShipmentService(repo)
    
    # 1. Define shipment request
    request = ShipmentRequest(
        marketplace_code="US",
        source_address=SourceAddress(
            name="Chalkola Warehouse",
            address_line_1="123 Industrial Blvd",
            city="Los Angeles",
            state_or_province="CA",
            postal_code="90001",
            country_code="US",
        ),
        items=[
            InboundItem(msku="CHALK-MARKER-12PK", quantity=100),
            InboundItem(msku="CHALK-MARKER-24PK", quantity=50),
        ],
        boxes=[
            Box(
                dimensions=BoxDimensions(length=15, width=12, height=10),
                weight=BoxWeight(value=8.5),
                items=[
                    InboundItem(msku="CHALK-MARKER-12PK", quantity=50),
                ],
            ),
            Box(
                dimensions=BoxDimensions(length=15, width=12, height=10),
                weight=BoxWeight(value=8.5),
                items=[
                    InboundItem(msku="CHALK-MARKER-12PK", quantity=50),
                ],
            ),
            Box(
                dimensions=BoxDimensions(length=18, width=14, height=12),
                weight=BoxWeight(value=12.0),
                items=[
                    InboundItem(msku="CHALK-MARKER-24PK", quantity=50),
                ],
            ),
        ],
        name="February 2026 Restock",
    )
    
    # 2. Create plan
    plan_id = await service.create_plan(request)
    print(f"Plan created: {plan_id}")
    
    # 3. Configure packing
    await service.configure_packing(
        marketplace_code="US",
        plan_id=plan_id,
        boxes=request.boxes,
    )
    
    # 4. Get placement options (show to user)
    placement_options = await service.get_placement_options("US", plan_id)
    
    print("\nPlacement Options:")
    for opt in placement_options:
        print(f"  - {opt.description}")
        print(f"    Fee: {opt.fee_per_unit} {opt.fee_currency}/unit")
        print(f"    Shipments: {len(opt.shipment_ids)}")
    
    # 5. User selects option (e.g., lowest fee)
    selected_placement = placement_options[0].placement_option_id
    
    # 6. Confirm placement and get transportation options
    from datetime import datetime, timedelta
    ready_date = datetime.now() + timedelta(days=7)
    
    transport_options = await service.confirm_placement_and_transportation(
        marketplace_code="US",
        plan_id=plan_id,
        placement_option_id=selected_placement,
        ready_to_ship_date=ready_date,
    )
    
    print("\nTransportation Options:")
    for opt in transport_options:
        print(f"  - {opt.carrier_name} ({opt.shipping_mode})")
        print(f"    Cost: {opt.cost} {opt.cost_currency}")
    
    # 7. User selects transportation
    transport_selections = [
        {
            "shipmentId": opt.shipment_id,
            "transportationOptionId": opt.transportation_option_id,
        }
        for opt in transport_options
    ]
    
    # 8. Finalize and get labels
    result = await service.finalize_shipment(
        marketplace_code="US",
        plan_id=plan_id,
        transportation_selections=transport_selections,
    )
    
    print(f"\n✅ Shipment Complete!")
    print(f"Plan ID: {result.inbound_plan_id}")
    print(f"Total Units: {result.total_units}")
    print(f"Total Boxes: {result.total_boxes}")
    
    for shipment in result.shipments:
        print(f"\nShipment: {shipment['shipmentConfirmationId']}")
        print(f"  Destination: {shipment['destination']}")
        print(f"  Labels: {shipment['labels_url']}")
```

---

## 6. Brand Analytics SQP Automation

### 6.1 SQP Service Implementation

```python
# File: src/services/sqp_service.py

from datetime import datetime, date, timedelta
from typing import Optional
import structlog

from src.api.reports_api import ReportsAPIClient, ReportType
from src.config.marketplaces import Marketplace, get_marketplace, MARKETPLACES
from src.db.repositories.sqp_repo import SQPRepository
from src.utils.date_utils import (
    get_previous_week_range,
    get_previous_month_range,
    align_to_sunday,
)

logger = structlog.get_logger()

class SQPService:
    """
    Service for automating Brand Analytics SQP data pulls.
    
    Key Constraints:
    - ASIN-level only (no brand-level view via API)
    - 200 char limit for ASIN list (~15 ASINs per request)
    - Weekly dates must be Sunday-Saturday
    - Monthly dates must be 1st to last day
    """
    
    MAX_ASINS_PER_REQUEST = 15  # ~200 chars / ~13 chars per ASIN
    
    def __init__(self, sqp_repo: SQPRepository):
        self.sqp_repo = sqp_repo
        self._clients: dict[str, ReportsAPIClient] = {}
    
    def _get_client(self, marketplace_code: str) -> ReportsAPIClient:
        """Get or create API client for marketplace."""
        if marketplace_code not in self._clients:
            marketplace = get_marketplace(marketplace_code)
            self._clients[marketplace_code] = ReportsAPIClient(marketplace)
        return self._clients[marketplace_code]
    
    def _batch_asins(self, asins: list[str]) -> list[list[str]]:
        """Split ASINs into batches of MAX_ASINS_PER_REQUEST."""
        return [
            asins[i:i + self.MAX_ASINS_PER_REQUEST]
            for i in range(0, len(asins), self.MAX_ASINS_PER_REQUEST)
        ]
    
    async def pull_weekly_sqp(
        self,
        marketplace_code: str,
        asins: list[str],
        week_start: Optional[date] = None,
    ) -> int:
        """
        Pull weekly SQP data for specified ASINs.
        
        Args:
            marketplace_code: e.g., 'US', 'UK'
            asins: List of ASINs to pull data for
            week_start: Sunday of the week (defaults to previous week)
            
        Returns:
            Number of records inserted
        """
        client = self._get_client(marketplace_code)
        marketplace = get_marketplace(marketplace_code)
        
        # Default to previous complete week
        if week_start is None:
            week_start, week_end = get_previous_week_range()
        else:
            # Ensure it's a Sunday
            week_start = align_to_sunday(week_start)
            week_end = week_start + timedelta(days=6)
        
        logger.info(
            "Pulling weekly SQP",
            marketplace=marketplace_code,
            asin_count=len(asins),
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
        )
        
        # Batch ASINs
        batches = self._batch_asins(asins)
        total_records = 0
        
        for batch_num, asin_batch in enumerate(batches, 1):
            logger.debug(
                "Processing ASIN batch",
                batch=batch_num,
                total_batches=len(batches),
                asins=len(asin_batch)
            )
            
            # Create report
            data = client.create_and_download_report(
                report_type=ReportType.SQP,
                data_start_time=datetime.combine(week_start, datetime.min.time()),
                data_end_time=datetime.combine(week_end, datetime.max.time()),
                report_options={
                    "asin": " ".join(asin_batch),
                    "reportPeriod": "WEEK",
                },
            )
            
            # Process and insert records
            records = self._parse_sqp_data(
                data=data,
                marketplace_id=marketplace.marketplace_id,
                report_period="WEEK",
                period_start=week_start,
                period_end=week_end,
            )
            
            if records:
                await self.sqp_repo.bulk_insert(records)
                total_records += len(records)
            
            # Rate limit: ~1 request per minute
            if batch_num < len(batches):
                import time
                time.sleep(60)
        
        logger.info(
            "Weekly SQP pull complete",
            marketplace=marketplace_code,
            records=total_records
        )
        
        return total_records
    
    async def pull_monthly_sqp(
        self,
        marketplace_code: str,
        asins: list[str],
        month: Optional[date] = None,
    ) -> int:
        """
        Pull monthly SQP data for specified ASINs.
        
        Args:
            marketplace_code: e.g., 'US', 'UK'
            asins: List of ASINs
            month: Any date in the target month (defaults to previous month)
            
        Returns:
            Number of records inserted
        """
        client = self._get_client(marketplace_code)
        marketplace = get_marketplace(marketplace_code)
        
        # Default to previous complete month
        if month is None:
            month_start, month_end = get_previous_month_range()
        else:
            month_start, month_end = get_previous_month_range(month)
        
        logger.info(
            "Pulling monthly SQP",
            marketplace=marketplace_code,
            asin_count=len(asins),
            month_start=month_start.isoformat(),
            month_end=month_end.isoformat(),
        )
        
        # Batch ASINs
        batches = self._batch_asins(asins)
        total_records = 0
        
        for batch_num, asin_batch in enumerate(batches, 1):
            # Create report
            data = client.create_and_download_report(
                report_type=ReportType.SQP,
                data_start_time=datetime.combine(month_start, datetime.min.time()),
                data_end_time=datetime.combine(month_end, datetime.max.time()),
                report_options={
                    "asin": " ".join(asin_batch),
                    "reportPeriod": "MONTH",
                },
            )
            
            # Process and insert records
            records = self._parse_sqp_data(
                data=data,
                marketplace_id=marketplace.marketplace_id,
                report_period="MONTH",
                period_start=month_start,
                period_end=month_end,
            )
            
            if records:
                await self.sqp_repo.bulk_insert(records)
                total_records += len(records)
            
            # Rate limit
            if batch_num < len(batches):
                import time
                time.sleep(60)
        
        logger.info(
            "Monthly SQP pull complete",
            marketplace=marketplace_code,
            records=total_records
        )
        
        return total_records
    
    def _parse_sqp_data(
        self,
        data: dict | list,
        marketplace_id: str,
        report_period: str,
        period_start: date,
        period_end: date,
    ) -> list[dict]:
        """
        Parse SQP report JSON into database records.
        
        SQP JSON structure:
        {
            "dataByDepartment": [
                {
                    "departmentName": "...",
                    "dataByAsin": [
                        {
                            "asin": "B00ABC1234",
                            "dataBySearchQuery": [
                                {
                                    "searchQuery": "chalk markers",
                                    "searchQueryScore": 85000,
                                    ...
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        """
        records = []
        
        # Handle different response structures
        if isinstance(data, dict):
            departments = data.get("dataByDepartment", [])
        else:
            departments = data
        
        for dept in departments:
            for asin_data in dept.get("dataByAsin", []):
                asin = asin_data.get("asin")
                
                for query_data in asin_data.get("dataBySearchQuery", []):
                    record = {
                        "marketplace_id": marketplace_id,
                        "report_period": report_period,
                        "period_start": period_start,
                        "period_end": period_end,
                        "asin": asin,
                        "search_query": query_data.get("searchQuery"),
                        "search_query_score": query_data.get("searchQueryScore"),
                        "search_query_volume": query_data.get("searchQueryVolume"),
                        "total_impressions": query_data.get("totalQueryImpressionCount"),
                        "asin_impressions": query_data.get("asinImpressionCount"),
                        "asin_impression_share": query_data.get("asinImpressionShare"),
                        "total_clicks": query_data.get("totalClickCount"),
                        "asin_clicks": query_data.get("asinClickCount"),
                        "asin_click_share": query_data.get("asinClickShare"),
                        "total_cart_adds": query_data.get("totalCartAddCount"),
                        "asin_cart_adds": query_data.get("asinCartAddCount"),
                        "asin_cart_add_share": query_data.get("asinCartAddShare"),
                        "total_purchases": query_data.get("totalPurchaseCount"),
                        "asin_purchases": query_data.get("asinPurchaseCount"),
                        "asin_purchase_share": query_data.get("asinPurchaseShare"),
                        "total_purchase_rate": query_data.get("totalPurchaseRate"),
                    }
                    records.append(record)
        
        return records
    
    async def pull_all_marketplaces_weekly(self, asins_by_marketplace: dict[str, list[str]]) -> dict[str, int]:
        """
        Pull weekly SQP for all configured marketplaces.
        
        Args:
            asins_by_marketplace: Dict of {marketplace_code: [asins]}
            
        Returns:
            Dict of {marketplace_code: record_count}
        """
        results = {}
        
        for marketplace_code, asins in asins_by_marketplace.items():
            try:
                count = await self.pull_weekly_sqp(marketplace_code, asins)
                results[marketplace_code] = count
            except Exception as e:
                logger.error(
                    "Failed to pull SQP",
                    marketplace=marketplace_code,
                    error=str(e)
                )
                results[marketplace_code] = -1
        
        return results


# ========================================
# DATE UTILITIES
# ========================================

# File: src/utils/date_utils.py

from datetime import date, datetime, timedelta
from calendar import monthrange

def get_previous_week_range(reference_date: date = None) -> tuple[date, date]:
    """
    Get the previous complete week (Sunday to Saturday).
    
    Args:
        reference_date: Date to calculate from (default: today)
        
    Returns:
        Tuple of (sunday_start, saturday_end)
    """
    if reference_date is None:
        reference_date = date.today()
    
    # Find last Saturday
    days_since_saturday = (reference_date.weekday() + 2) % 7
    last_saturday = reference_date - timedelta(days=days_since_saturday)
    
    # Week is Sunday to Saturday
    week_start = last_saturday - timedelta(days=6)  # Sunday
    week_end = last_saturday  # Saturday
    
    return week_start, week_end

def get_previous_month_range(reference_date: date = None) -> tuple[date, date]:
    """
    Get the previous complete month.
    
    Args:
        reference_date: Date to calculate from (default: today)
        
    Returns:
        Tuple of (first_day, last_day)
    """
    if reference_date is None:
        reference_date = date.today()
    
    # First day of current month
    first_of_current = reference_date.replace(day=1)
    
    # Last day of previous month
    last_of_previous = first_of_current - timedelta(days=1)
    
    # First day of previous month
    first_of_previous = last_of_previous.replace(day=1)
    
    return first_of_previous, last_of_previous

def align_to_sunday(d: date) -> date:
    """
    Align a date to the previous Sunday (or same day if already Sunday).
    Sunday = weekday 6 in Python.
    """
    days_to_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_to_sunday)
```

### 6.2 SQP Scheduled Jobs

```python
# File: src/jobs/sqp_weekly_pull.py

import asyncio
from datetime import date
import structlog

from src.services.sqp_service import SQPService
from src.db.repositories.sqp_repo import SQPRepository
from src.db.connection import get_db_connection

logger = structlog.get_logger()

# Chalkola's ASINs by marketplace
# In production, this would come from a database or config
CHALKOLA_ASINS = {
    "US": [
        "B08ABC1234", "B08DEF5678", "B08GHI9012",
        # ... add all US ASINs
    ],
    "UK": [
        "B08UK00001", "B08UK00002",
        # ... add all UK ASINs
    ],
    "DE": [
        "B08DE00001", "B08DE00002",
        # ... add all DE ASINs
    ],
    "CA": [],
    "FR": [],
    "UAE": [],
    "AU": [],
}

async def run_weekly_sqp_pull():
    """
    Scheduled job: Pull weekly SQP data for all marketplaces.
    
    Schedule: Every Tuesday at 8:00 AM UTC
    (Data available ~48-72 hours after week ends on Saturday)
    """
    logger.info("Starting weekly SQP pull job")
    
    try:
        db = get_db_connection()
        repo = SQPRepository(db)
        service = SQPService(repo)
        
        # Filter to marketplaces with ASINs
        active_marketplaces = {
            k: v for k, v in CHALKOLA_ASINS.items() if v
        }
        
        results = await service.pull_all_marketplaces_weekly(active_marketplaces)
        
        # Log results
        total_records = sum(v for v in results.values() if v > 0)
        failed = [k for k, v in results.items() if v < 0]
        
        logger.info(
            "Weekly SQP pull complete",
            total_records=total_records,
            marketplaces=len(results),
            failed=failed
        )
        
        return results
        
    except Exception as e:
        logger.error("Weekly SQP pull failed", error=str(e))
        raise


# File: src/jobs/sqp_monthly_pull.py

async def run_monthly_sqp_pull():
    """
    Scheduled job: Pull monthly SQP data for all marketplaces.
    
    Schedule: 5th of each month at 8:00 AM UTC
    """
    logger.info("Starting monthly SQP pull job")
    
    try:
        db = get_db_connection()
        repo = SQPRepository(db)
        service = SQPService(repo)
        
        active_marketplaces = {
            k: v for k, v in CHALKOLA_ASINS.items() if v
        }
        
        results = {}
        for marketplace_code, asins in active_marketplaces.items():
            try:
                count = await service.pull_monthly_sqp(marketplace_code, asins)
                results[marketplace_code] = count
            except Exception as e:
                logger.error(
                    "Monthly SQP pull failed",
                    marketplace=marketplace_code,
                    error=str(e)
                )
                results[marketplace_code] = -1
        
        total_records = sum(v for v in results.values() if v > 0)
        
        logger.info(
            "Monthly SQP pull complete",
            total_records=total_records,
            results=results
        )
        
        return results
        
    except Exception as e:
        logger.error("Monthly SQP pull failed", error=str(e))
        raise


if __name__ == "__main__":
    # Manual trigger for testing
    asyncio.run(run_weekly_sqp_pull())
```

---

## 7. Database Setup

### 7.1 Supabase Schema Migration

```sql
-- File: src/db/migrations/001_initial_schema.sql

-- ============================================
-- SQP DATA TABLE (Partitioned)
-- ============================================

CREATE TABLE IF NOT EXISTS sqp_data (
    id BIGSERIAL,
    marketplace_id VARCHAR(20) NOT NULL,
    report_period VARCHAR(10) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    asin VARCHAR(20) NOT NULL,
    search_query TEXT NOT NULL,
    search_query_score INTEGER,
    search_query_volume VARCHAR(20),
    total_impressions INTEGER,
    asin_impressions INTEGER,
    asin_impression_share DECIMAL(8,6),
    total_clicks INTEGER,
    asin_clicks INTEGER,
    asin_click_share DECIMAL(8,6),
    total_cart_adds INTEGER,
    asin_cart_adds INTEGER,
    asin_cart_add_share DECIMAL(8,6),
    total_purchases INTEGER,
    asin_purchases INTEGER,
    asin_purchase_share DECIMAL(8,6),
    total_purchase_rate DECIMAL(8,6),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, marketplace_id)
) PARTITION BY LIST (marketplace_id);

-- Create partitions for each marketplace
CREATE TABLE sqp_data_us PARTITION OF sqp_data 
    FOR VALUES IN ('ATVPDKIKX0DER');
CREATE TABLE sqp_data_ca PARTITION OF sqp_data 
    FOR VALUES IN ('A2EUQ1WTGCTBG2');
CREATE TABLE sqp_data_uk PARTITION OF sqp_data 
    FOR VALUES IN ('A1F83G8C2ARO7P');
CREATE TABLE sqp_data_de PARTITION OF sqp_data 
    FOR VALUES IN ('A1PA6795UKMFR9');
CREATE TABLE sqp_data_fr PARTITION OF sqp_data 
    FOR VALUES IN ('A13V1IB3VIYZZH');
CREATE TABLE sqp_data_uae PARTITION OF sqp_data 
    FOR VALUES IN ('A2VIGQ35RCS4UG');
CREATE TABLE sqp_data_au PARTITION OF sqp_data 
    FOR VALUES IN ('A39IBJ37TRP1C6');

-- Indexes for common queries
CREATE INDEX idx_sqp_data_period ON sqp_data (period_start, period_end);
CREATE INDEX idx_sqp_data_asin ON sqp_data (asin);
CREATE INDEX idx_sqp_data_query ON sqp_data USING gin (to_tsvector('english', search_query));

-- ============================================
-- FBA SHIPMENTS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fba_shipments (
    id BIGSERIAL PRIMARY KEY,
    inbound_plan_id VARCHAR(50) NOT NULL UNIQUE,
    marketplace_id VARCHAR(20) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'CREATED',
    
    -- Plan details
    plan_name VARCHAR(255),
    source_address JSONB,
    
    -- Placement
    placement_option_id VARCHAR(50),
    placement_fee_per_unit DECIMAL(10,4),
    placement_fee_currency VARCHAR(3),
    
    -- Transportation
    transportation_option_id VARCHAR(50),
    carrier_name VARCHAR(50),
    shipping_mode VARCHAR(50),
    
    -- Totals
    total_units INTEGER,
    total_boxes INTEGER,
    total_weight DECIMAL(10,2),
    
    -- Labels
    labels_downloaded BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    estimated_ship_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fba_shipments_marketplace ON fba_shipments (marketplace_id);
CREATE INDEX idx_fba_shipments_status ON fba_shipments (status);
CREATE INDEX idx_fba_shipments_created ON fba_shipments (created_at DESC);

-- ============================================
-- FBA SHIPMENT ITEMS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fba_shipment_items (
    id BIGSERIAL PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES fba_shipments(id) ON DELETE CASCADE,
    msku VARCHAR(50) NOT NULL,
    fnsku VARCHAR(50),
    quantity INTEGER NOT NULL,
    box_id VARCHAR(50),
    prep_owner VARCHAR(20) DEFAULT 'SELLER',
    label_owner VARCHAR(20) DEFAULT 'SELLER'
);

CREATE INDEX idx_fba_shipment_items_shipment ON fba_shipment_items (shipment_id);
CREATE INDEX idx_fba_shipment_items_msku ON fba_shipment_items (msku);

-- ============================================
-- FBA SHIPMENT DESTINATIONS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS fba_shipment_destinations (
    id BIGSERIAL PRIMARY KEY,
    shipment_id BIGINT NOT NULL REFERENCES fba_shipments(id) ON DELETE CASCADE,
    shipment_confirmation_id VARCHAR(50),  -- FBA1234ABCD
    destination_fc VARCHAR(10),
    destination_address JSONB,
    labels_url TEXT,
    tracking_numbers JSONB,  -- Array of tracking numbers
    status VARCHAR(50) DEFAULT 'PENDING'
);

CREATE INDEX idx_fba_destinations_shipment ON fba_shipment_destinations (shipment_id);
CREATE INDEX idx_fba_destinations_confirmation ON fba_shipment_destinations (shipment_confirmation_id);

-- ============================================
-- INVENTORY LEVELS TABLE
-- ============================================

CREATE TABLE IF NOT EXISTS inventory_levels (
    id BIGSERIAL PRIMARY KEY,
    marketplace_id VARCHAR(20) NOT NULL,
    asin VARCHAR(20) NOT NULL,
    fnsku VARCHAR(20),
    msku VARCHAR(50) NOT NULL,
    
    -- Quantities
    total_quantity INTEGER DEFAULT 0,
    fulfillable_quantity INTEGER DEFAULT 0,
    inbound_working_quantity INTEGER DEFAULT 0,
    inbound_shipped_quantity INTEGER DEFAULT 0,
    inbound_receiving_quantity INTEGER DEFAULT 0,
    reserved_quantity INTEGER DEFAULT 0,
    unfulfillable_quantity INTEGER DEFAULT 0,
    
    -- Last sync
    last_synced_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (marketplace_id, msku)
);

CREATE INDEX idx_inventory_marketplace ON inventory_levels (marketplace_id);
CREATE INDEX idx_inventory_msku ON inventory_levels (msku);
CREATE INDEX idx_inventory_asin ON inventory_levels (asin);

-- ============================================
-- API REQUEST LOG (for debugging)
-- ============================================

CREATE TABLE IF NOT EXISTS api_request_log (
    id BIGSERIAL PRIMARY KEY,
    request_time TIMESTAMPTZ DEFAULT NOW(),
    api_type VARCHAR(20) NOT NULL,  -- SP_API, ADS_API
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    marketplace_id VARCHAR(20),
    status_code INTEGER,
    duration_ms INTEGER,
    error_code VARCHAR(50),
    error_message TEXT,
    request_id VARCHAR(100)
);

CREATE INDEX idx_api_log_time ON api_request_log (request_time DESC);
CREATE INDEX idx_api_log_endpoint ON api_request_log (endpoint);
CREATE INDEX idx_api_log_errors ON api_request_log (error_code) WHERE error_code IS NOT NULL;

-- ============================================
-- SCHEDULED JOB STATUS
-- ============================================

CREATE TABLE IF NOT EXISTS job_runs (
    id BIGSERIAL PRIMARY KEY,
    job_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'RUNNING',  -- RUNNING, SUCCESS, FAILED
    records_processed INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB
);

CREATE INDEX idx_job_runs_name ON job_runs (job_name);
CREATE INDEX idx_job_runs_status ON job_runs (status);
CREATE INDEX idx_job_runs_started ON job_runs (started_at DESC);

-- ============================================
-- ROW LEVEL SECURITY (Optional)
-- ============================================

-- Enable RLS on tables if needed for multi-tenant scenarios
-- ALTER TABLE sqp_data ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE fba_shipments ENABLE ROW LEVEL SECURITY;

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for fba_shipments
CREATE TRIGGER update_fba_shipments_updated_at
    BEFORE UPDATE ON fba_shipments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### 7.2 Repository Implementation

```python
# File: src/db/repositories/sqp_repo.py

from typing import Optional
from datetime import date
import structlog

logger = structlog.get_logger()

class SQPRepository:
    """Repository for SQP data operations."""
    
    def __init__(self, db_connection):
        self.db = db_connection
    
    async def bulk_insert(self, records: list[dict]) -> int:
        """
        Insert multiple SQP records efficiently.
        Uses ON CONFLICT to handle duplicates.
        """
        if not records:
            return 0
        
        # Build INSERT statement
        columns = list(records[0].keys())
        placeholders = ", ".join([f"${i+1}" for i in range(len(columns))])
        column_names = ", ".join(columns)
        
        query = f"""
            INSERT INTO sqp_data ({column_names})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
        """
        
        # Execute batch
        async with self.db.transaction():
            for record in records:
                values = [record[col] for col in columns]
                await self.db.execute(query, *values)
        
        logger.debug("Inserted SQP records", count=len(records))
        return len(records)
    
    async def get_by_asin(
        self,
        asin: str,
        marketplace_id: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> list[dict]:
        """Get SQP data for a specific ASIN."""
        query = """
            SELECT * FROM sqp_data
            WHERE asin = $1 AND marketplace_id = $2
        """
        params = [asin, marketplace_id]
        
        if period_start:
            query += " AND period_start >= $3"
            params.append(period_start)
        
        if period_end:
            query += f" AND period_end <= ${len(params) + 1}"
            params.append(period_end)
        
        query += " ORDER BY period_start DESC"
        
        return await self.db.fetch(query, *params)
    
    async def search_queries(
        self,
        search_term: str,
        marketplace_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """Search for queries containing a term."""
        query = """
            SELECT DISTINCT search_query, search_query_score
            FROM sqp_data
            WHERE marketplace_id = $1
            AND search_query ILIKE $2
            ORDER BY search_query_score DESC NULLS LAST
            LIMIT $3
        """
        
        return await self.db.fetch(query, marketplace_id, f"%{search_term}%", limit)


# File: src/db/repositories/shipment_repo.py

class ShipmentRepository:
    """Repository for FBA shipment operations."""
    
    def __init__(self, db_connection):
        self.db = db_connection
    
    async def create_shipment(
        self,
        inbound_plan_id: str,
        marketplace_id: str,
        status: str,
        total_units: int,
        total_boxes: int,
        source_address: Optional[dict] = None,
        plan_name: Optional[str] = None,
    ) -> int:
        """Create a new shipment record."""
        query = """
            INSERT INTO fba_shipments (
                inbound_plan_id, marketplace_id, status,
                total_units, total_boxes, source_address, plan_name
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """
        
        result = await self.db.fetchrow(
            query,
            inbound_plan_id, marketplace_id, status,
            total_units, total_boxes, source_address, plan_name
        )
        
        return result["id"]
    
    async def update_status(self, inbound_plan_id: str, status: str):
        """Update shipment status."""
        query = """
            UPDATE fba_shipments
            SET status = $1, updated_at = NOW()
            WHERE inbound_plan_id = $2
        """
        await self.db.execute(query, status, inbound_plan_id)
    
    async def update_placement(
        self,
        inbound_plan_id: str,
        placement_option_id: str,
        fee_per_unit: Optional[float] = None,
        fee_currency: Optional[str] = None,
    ):
        """Update placement selection."""
        query = """
            UPDATE fba_shipments
            SET placement_option_id = $1,
                placement_fee_per_unit = $2,
                placement_fee_currency = $3,
                updated_at = NOW()
            WHERE inbound_plan_id = $4
        """
        await self.db.execute(
            query, placement_option_id, fee_per_unit, fee_currency, inbound_plan_id
        )
    
    async def update_shipments(self, inbound_plan_id: str, shipments: list[dict]):
        """Update shipment destinations after finalization."""
        # Get shipment ID
        shipment = await self.db.fetchrow(
            "SELECT id FROM fba_shipments WHERE inbound_plan_id = $1",
            inbound_plan_id
        )
        
        if not shipment:
            raise ValueError(f"Shipment not found: {inbound_plan_id}")
        
        shipment_id = shipment["id"]
        
        # Insert destinations
        for dest in shipments:
            await self.db.execute("""
                INSERT INTO fba_shipment_destinations (
                    shipment_id, shipment_confirmation_id,
                    destination_fc, destination_address, labels_url
                )
                VALUES ($1, $2, $3, $4, $5)
            """,
                shipment_id,
                dest.get("shipmentConfirmationId"),
                dest.get("destination", {}).get("warehouseId"),
                dest.get("destination"),
                dest.get("labels_url"),
            )
    
    async def get_by_plan_id(self, inbound_plan_id: str) -> Optional[dict]:
        """Get shipment by plan ID with destinations."""
        shipment = await self.db.fetchrow(
            "SELECT * FROM fba_shipments WHERE inbound_plan_id = $1",
            inbound_plan_id
        )
        
        if not shipment:
            return None
        
        destinations = await self.db.fetch(
            "SELECT * FROM fba_shipment_destinations WHERE shipment_id = $1",
            shipment["id"]
        )
        
        return {
            **dict(shipment),
            "destinations": [dict(d) for d in destinations],
        }
```

---

## 8. Scheduled Jobs

### 8.1 Job Scheduler Setup

```python
# File: src/jobs/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog

from src.jobs.sqp_weekly_pull import run_weekly_sqp_pull
from src.jobs.sqp_monthly_pull import run_monthly_sqp_pull
from src.jobs.inventory_sync import run_inventory_sync

logger = structlog.get_logger()

def create_scheduler() -> AsyncIOScheduler:
    """
    Create and configure the job scheduler.
    
    Schedule Summary:
    - SQP Weekly:    Tuesday 8:00 AM UTC
    - SQP Monthly:   5th of month 8:00 AM UTC
    - Inventory:     Every 4 hours
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # Weekly SQP pull - Tuesday 8:00 AM UTC
    # Data available ~48-72 hours after week ends Saturday
    scheduler.add_job(
        run_weekly_sqp_pull,
        CronTrigger(day_of_week="tue", hour=8, minute=0),
        id="sqp_weekly",
        name="Weekly SQP Pull",
        replace_existing=True,
    )
    
    # Monthly SQP pull - 5th of each month 8:00 AM UTC
    scheduler.add_job(
        run_monthly_sqp_pull,
        CronTrigger(day=5, hour=8, minute=0),
        id="sqp_monthly",
        name="Monthly SQP Pull",
        replace_existing=True,
    )
    
    # Inventory sync - Every 4 hours
    scheduler.add_job(
        run_inventory_sync,
        CronTrigger(hour="*/4", minute=0),
        id="inventory_sync",
        name="Inventory Sync",
        replace_existing=True,
    )
    
    logger.info("Scheduler configured", jobs=len(scheduler.get_jobs()))
    
    return scheduler


# File: src/main.py

import asyncio
from src.jobs.scheduler import create_scheduler
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()

async def main():
    logger.info("Starting Chalkola SP-API service")
    
    scheduler = create_scheduler()
    scheduler.start()
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down")
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### 8.2 Alternative: Railway Cron Jobs

If using Railway instead of in-process scheduler:

```toml
# railway.toml

[deploy]
startCommand = "python -m src.main"

# Define cron jobs
[[cron]]
schedule = "0 8 * * 2"  # Tuesday 8:00 AM UTC
command = "python -m src.jobs.sqp_weekly_pull"

[[cron]]
schedule = "0 8 5 * *"  # 5th of month 8:00 AM UTC
command = "python -m src.jobs.sqp_monthly_pull"

[[cron]]
schedule = "0 */4 * * *"  # Every 4 hours
command = "python -m src.jobs.inventory_sync"
```

---

## 9. Error Handling & Logging

### 9.1 Structured Logging Setup

```python
# File: src/utils/logging.py

import structlog
import logging
import sys
from typing import Optional
import os

def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    log_file: Optional[str] = None,
):
    """
    Configure structured logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use JSON format (True for production)
        log_file: Optional file path for log output
    """
    # Set root logger level
    logging.root.setLevel(getattr(logging, level.upper()))
    
    # Configure processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        logging.root.addHandler(file_handler)
    
    # Add stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(getattr(logging, level.upper()))
    logging.root.addHandler(stdout_handler)


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Get a logger instance."""
    return structlog.get_logger(name)
```

### 9.2 Custom Exception Classes

```python
# File: src/utils/exceptions.py

from typing import Optional

class SPAPIException(Exception):
    """Base exception for SP-API errors."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)
    
    def __str__(self):
        parts = [self.message]
        if self.error_code:
            parts.insert(0, f"[{self.error_code}]")
        if self.status_code:
            parts.insert(0, f"HTTP {self.status_code}")
        return " ".join(parts)


class AuthenticationError(SPAPIException):
    """Authentication/authorization failed."""
    pass


class RateLimitError(SPAPIException):
    """Rate limit exceeded."""
    
    def __init__(self, retry_after: Optional[int] = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(**kwargs)


class ValidationError(SPAPIException):
    """Request validation failed."""
    pass


class ResourceNotFoundError(SPAPIException):
    """Requested resource not found."""
    pass


class OperationFailedError(SPAPIException):
    """Async operation failed."""
    
    def __init__(self, operation_id: str, problems: list[dict], **kwargs):
        self.operation_id = operation_id
        self.problems = problems
        super().__init__(**kwargs)


class ReportGenerationError(SPAPIException):
    """Report generation failed."""
    
    def __init__(self, report_id: str, status: str, **kwargs):
        self.report_id = report_id
        self.status = status
        super().__init__(**kwargs)
```

### 9.3 Retry Decorator with Backoff

```python
# File: src/utils/retry.py

import time
import random
from functools import wraps
from typing import Callable, Type, Tuple
import structlog

logger = structlog.get_logger()

def retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential calculation
        jitter: Add random jitter to delay
        retryable_exceptions: Exception types to retry
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                    
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            "Max retries exceeded",
                            function=func.__name__,
                            attempts=attempt + 1,
                            error=str(e)
                        )
                        raise
                    
                    # Calculate delay
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    
                    if jitter:
                        delay += random.uniform(0, 1)
                    
                    logger.warning(
                        "Retrying after error",
                        function=func.__name__,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e)
                    )
                    
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


# Async version
def async_retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Async version of retry decorator."""
    import asyncio
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        raise
                    
                    delay = min(
                        base_delay * (exponential_base ** attempt),
                        max_delay
                    )
                    
                    if jitter:
                        delay += random.uniform(0, 1)
                    
                    logger.warning(
                        "Retrying after error",
                        function=func.__name__,
                        attempt=attempt + 1,
                        delay=delay,
                        error=str(e)
                    )
                    
                    await asyncio.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator
```

---

## 10. Testing Strategy

### 10.1 Test Configuration

```python
# File: tests/conftest.py

import pytest
import os
from unittest.mock import MagicMock, patch

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["SP_API_CLIENT_ID"] = "test-client-id"
os.environ["SP_API_CLIENT_SECRET"] = "test-client-secret"
os.environ["SP_API_REFRESH_TOKEN_NA"] = "test-refresh-token"

@pytest.fixture
def mock_token_manager():
    """Mock token manager to avoid real API calls."""
    with patch("src.auth.token_manager.TokenManager") as mock:
        instance = mock.return_value
        instance.get_access_token.return_value = "test-access-token"
        yield instance

@pytest.fixture
def mock_db():
    """Mock database connection."""
    db = MagicMock()
    db.execute = MagicMock(return_value=None)
    db.fetch = MagicMock(return_value=[])
    db.fetchrow = MagicMock(return_value={"id": 1})
    return db

@pytest.fixture
def us_marketplace():
    """US marketplace for testing."""
    from src.config.marketplaces import get_marketplace
    return get_marketplace("US")

@pytest.fixture
def sample_sqp_response():
    """Sample SQP API response."""
    return {
        "dataByDepartment": [
            {
                "departmentName": "Arts, Crafts & Sewing",
                "dataByAsin": [
                    {
                        "asin": "B08TEST001",
                        "dataBySearchQuery": [
                            {
                                "searchQuery": "chalk markers",
                                "searchQueryScore": 85000,
                                "totalQueryImpressionCount": 50000,
                                "asinImpressionCount": 5000,
                                "asinImpressionShare": 0.10,
                                "totalClickCount": 2500,
                                "asinClickCount": 400,
                                "asinClickShare": 0.16,
                                "totalCartAddCount": 500,
                                "asinCartAddCount": 80,
                                "asinCartAddShare": 0.16,
                                "totalPurchaseCount": 200,
                                "asinPurchaseCount": 35,
                                "asinPurchaseShare": 0.175,
                                "totalPurchaseRate": 0.08,
                            }
                        ]
                    }
                ]
            }
        ]
    }
```

### 10.2 Unit Tests

```python
# File: tests/test_services/test_sqp_service.py

import pytest
from datetime import date
from unittest.mock import MagicMock, patch, AsyncMock

from src.services.sqp_service import SQPService
from src.utils.date_utils import get_previous_week_range, align_to_sunday

class TestSQPService:
    
    @pytest.fixture
    def sqp_service(self, mock_db):
        from src.db.repositories.sqp_repo import SQPRepository
        repo = SQPRepository(mock_db)
        return SQPService(repo)
    
    def test_batch_asins(self, sqp_service):
        """Test ASIN batching respects 15 ASIN limit."""
        asins = [f"B{i:09d}" for i in range(50)]
        batches = sqp_service._batch_asins(asins)
        
        assert len(batches) == 4  # 50 / 15 = 3.33 → 4 batches
        assert len(batches[0]) == 15
        assert len(batches[1]) == 15
        assert len(batches[2]) == 15
        assert len(batches[3]) == 5
    
    def test_parse_sqp_data(self, sqp_service, sample_sqp_response):
        """Test SQP response parsing."""
        records = sqp_service._parse_sqp_data(
            data=sample_sqp_response,
            marketplace_id="ATVPDKIKX0DER",
            report_period="WEEK",
            period_start=date(2026, 1, 26),
            period_end=date(2026, 2, 1),
        )
        
        assert len(records) == 1
        record = records[0]
        
        assert record["asin"] == "B08TEST001"
        assert record["search_query"] == "chalk markers"
        assert record["search_query_score"] == 85000
        assert record["asin_impression_share"] == 0.10


class TestDateUtils:
    
    def test_get_previous_week_range(self):
        """Test previous week calculation."""
        # If today is Wednesday Feb 5, 2026
        reference = date(2026, 2, 5)
        start, end = get_previous_week_range(reference)
        
        # Previous week: Jan 26 (Sun) - Feb 1 (Sat)
        assert start == date(2026, 1, 26)
        assert end == date(2026, 2, 1)
        assert start.weekday() == 6  # Sunday
        assert end.weekday() == 5    # Saturday
    
    def test_align_to_sunday(self):
        """Test Sunday alignment."""
        # Wednesday should align to previous Sunday
        wed = date(2026, 2, 4)  # Wednesday
        aligned = align_to_sunday(wed)
        
        assert aligned == date(2026, 2, 1)  # Sunday
        assert aligned.weekday() == 6
        
        # Sunday should stay as Sunday
        sun = date(2026, 2, 1)
        assert align_to_sunday(sun) == sun
```

### 10.3 Integration Tests

```python
# File: tests/test_integration/test_sp_api_connection.py

import pytest
import os

# Skip if no real credentials
pytestmark = pytest.mark.skipif(
    os.environ.get("ENVIRONMENT") == "test",
    reason="Integration tests require real credentials"
)

class TestSPAPIConnection:
    
    def test_token_refresh(self):
        """Test real token refresh."""
        from src.auth.token_manager import get_token_manager
        
        manager = get_token_manager()
        token = manager.get_access_token("NA")
        
        assert token is not None
        assert len(token) > 0
    
    def test_get_inventory(self):
        """Test real inventory API call."""
        from src.api.inventory_api import InventoryAPIClient
        from src.config.marketplaces import get_marketplace
        
        client = InventoryAPIClient(get_marketplace("US"))
        response = client.get_inventory_summaries(
            granularity_type="Marketplace",
            granularity_id="ATVPDKIKX0DER",
        )
        
        assert "inventorySummaries" in response.data
```

---

## 11. Deployment Guide

### 11.1 Railway Deployment

**Step 1: Create Railway Project**
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Create project
railway init
```

**Step 2: Configure Environment Variables**

In Railway dashboard → Project → Variables:
```
SP_API_CLIENT_ID=amzn1.application-oa2-client.xxx
SP_API_CLIENT_SECRET=xxx
SP_API_REFRESH_TOKEN_NA=Atzr|xxx
SP_API_REFRESH_TOKEN_EU=Atzr|xxx
SP_API_REFRESH_TOKEN_FE=Atzr|xxx
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=xxx
ENVIRONMENT=production
LOG_LEVEL=INFO
```

**Step 3: Configure Dockerfile**

```dockerfile
# Dockerfile

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ src/

# Run
CMD ["python", "-m", "src.main"]
```

**Step 4: Deploy**
```bash
railway up
```

### 11.2 Docker Compose (Local Development)

```yaml
# docker-compose.yml

version: "3.8"

services:
  sp-api-service:
    build: .
    env_file:
      - .env
    volumes:
      - ./src:/app/src
    depends_on:
      - postgres
    restart: unless-stopped
  
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: chalkola
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

### 11.3 Health Check Endpoint

```python
# File: src/api/health.py

from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

@app.route("/health")
def health_check():
    """Health check endpoint for Railway/monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    })

@app.route("/ready")
def readiness_check():
    """Readiness check - verify dependencies."""
    checks = {
        "database": check_database(),
        "sp_api": check_sp_api_auth(),
    }
    
    all_ready = all(checks.values())
    status_code = 200 if all_ready else 503
    
    return jsonify({
        "ready": all_ready,
        "checks": checks,
    }), status_code

def check_database():
    try:
        from src.db.connection import get_db_connection
        db = get_db_connection()
        db.execute("SELECT 1")
        return True
    except:
        return False

def check_sp_api_auth():
    try:
        from src.auth.token_manager import get_token_manager
        manager = get_token_manager()
        token = manager.get_access_token("NA")
        return bool(token)
    except:
        return False
```

---

## 12. Monitoring & Alerts

### 12.1 Sentry Integration

```python
# File: src/utils/monitoring.py

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
import os

def setup_monitoring():
    """Initialize Sentry for error tracking."""
    sentry_dsn = os.environ.get("SENTRY_DSN")
    
    if not sentry_dsn:
        return
    
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=os.environ.get("ENVIRONMENT", "development"),
        traces_sample_rate=0.1,
        integrations=[
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
    )

def capture_exception(exception: Exception, **context):
    """Capture exception with context."""
    with sentry_sdk.push_scope() as scope:
        for key, value in context.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_exception(exception)
```

### 12.2 Job Monitoring

```python
# File: src/jobs/base_job.py

from datetime import datetime
from typing import Optional
import structlog

from src.db.connection import get_db_connection
from src.utils.monitoring import capture_exception

logger = structlog.get_logger()

class JobRunner:
    """Base class for tracked jobs."""
    
    def __init__(self, job_name: str):
        self.job_name = job_name
        self.db = get_db_connection()
        self.run_id: Optional[int] = None
    
    async def start(self):
        """Record job start."""
        result = await self.db.fetchrow("""
            INSERT INTO job_runs (job_name, started_at, status)
            VALUES ($1, $2, 'RUNNING')
            RETURNING id
        """, self.job_name, datetime.utcnow())
        
        self.run_id = result["id"]
        logger.info("Job started", job=self.job_name, run_id=self.run_id)
    
    async def complete(self, records_processed: int = 0, metadata: dict = None):
        """Record job completion."""
        await self.db.execute("""
            UPDATE job_runs
            SET completed_at = $1, status = 'SUCCESS',
                records_processed = $2, metadata = $3
            WHERE id = $4
        """, datetime.utcnow(), records_processed, metadata, self.run_id)
        
        logger.info(
            "Job completed",
            job=self.job_name,
            run_id=self.run_id,
            records=records_processed
        )
    
    async def fail(self, error: Exception):
        """Record job failure."""
        await self.db.execute("""
            UPDATE job_runs
            SET completed_at = $1, status = 'FAILED',
                error_message = $2
            WHERE id = $3
        """, datetime.utcnow(), str(error), self.run_id)
        
        logger.error(
            "Job failed",
            job=self.job_name,
            run_id=self.run_id,
            error=str(error)
        )
        
        capture_exception(error, job_name=self.job_name, run_id=self.run_id)
```

---

## Quick Reference

### Key Endpoints

```
SP-API Base URLs:
  NA: https://sellingpartnerapi-na.amazon.com
  EU: https://sellingpartnerapi-eu.amazon.com
  FE: https://sellingpartnerapi-fe.amazon.com

Reports API:
  POST /reports/2021-06-30/reports
  GET  /reports/2021-06-30/reports/{id}
  GET  /reports/2021-06-30/documents/{id}

FBA Inbound API (v2024-03-20):
  POST /inbound/fba/2024-03-20/inboundPlans
  GET  /operations/{operationId}
  POST /inboundPlans/{id}/packingOptions
  POST /inboundPlans/{id}/placementOptions
  GET  /fba/inbound/v0/shipments/{id}/labels

FBA Inventory API:
  GET /fba/inventory/v1/summaries
```

### Rate Limits

```
createReport:      ~1/minute (burst: 15)
getReport:         2/second (burst: 15)
getReportDocument: ~1/minute (burst: 15)
FBA Inbound:       2/second (burst: 6)
Inventory:         2/second (burst: 2)
```

### SQP Date Rules

```
Weekly:  Start = Sunday, End = Saturday
Monthly: Start = 1st, End = Last day
```

---

*Document Version: 1.0 | February 2026*
