"""
SP-API Client Module
Centralized HTTP client with automatic retry, rate limiting, and error handling.

Features:
- Automatic retry with exponential backoff
- Rate limit header parsing (x-amzn-RateLimit-*)
- Transient error detection (429, 500, 502, 503, 504)
- Retry-After header support
- Configurable via environment variables
"""

import os
import time
import random
import logging
import requests
from typing import Optional, Dict, Any
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================

class SPAPIError(Exception):
    """Base exception for SP-API errors."""
    def __init__(self, message: str, status_code: int = None, response_body: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class SPAPIRateLimitError(SPAPIError):
    """Rate limit exceeded (429)."""
    pass


class SPAPITransientError(SPAPIError):
    """Transient error that may succeed on retry (500, 502, 503, 504)."""
    pass


class SPAPIFatalError(SPAPIError):
    """Fatal error that should not be retried (4xx except 429)."""
    pass


# =============================================================================
# Rate Limit Handler
# =============================================================================

class RateLimitHandler:
    """
    Handles SP-API rate limits per API type.

    SP-API Rate Limits (from Amazon docs):
    - Reports API: 0.0167 req/sec (1 per minute) for createReport
    - Reports API: 2 req/sec for getReport, getReportDocument
    - FBA Inventory API: 2 req/sec burst
    - AWD API: Similar to inventory

    Headers parsed:
    - x-amzn-RateLimit-Limit: Max requests per second
    """

    # Default rate limits by API type (requests per second)
    DEFAULT_LIMITS = {
        "reports_create": 0.0167,  # 1 per minute
        "reports_get": 2.0,
        "inventory": 2.0,
        "awd": 2.0,
        "auth": 1.0,
        "default": 1.0
    }

    def __init__(self):
        self.last_request_time: Dict[str, float] = {}
        self.current_limits: Dict[str, float] = {}

    def get_min_interval(self, api_type: str) -> float:
        """Get minimum interval between requests for this API type."""
        limit = self.current_limits.get(api_type) or self.DEFAULT_LIMITS.get(api_type, 1.0)
        return 1.0 / limit if limit > 0 else 1.0

    def wait_if_needed(self, api_type: str):
        """Block until safe to make next request."""
        min_interval = self.get_min_interval(api_type)
        last_time = self.last_request_time.get(api_type, 0)

        elapsed = time.time() - last_time
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s for {api_type}")
            time.sleep(wait_time)

    def record_request(self, api_type: str):
        """Record that a request was made."""
        self.last_request_time[api_type] = time.time()

    def update_from_response(self, api_type: str, response: requests.Response):
        """Update limits based on response headers."""
        # Parse x-amzn-RateLimit-Limit header
        limit_header = response.headers.get("x-amzn-RateLimit-Limit")
        if limit_header:
            try:
                limit = float(limit_header)
                if limit > 0:
                    self.current_limits[api_type] = limit
                    logger.debug(f"Updated rate limit for {api_type}: {limit}/sec")
            except (ValueError, TypeError):
                pass


# =============================================================================
# Retry Strategy
# =============================================================================

class RetryStrategy:
    """
    Implements exponential backoff with jitter.

    Strategy:
    - Connection errors: Immediate retry (up to 3 times), then backoff
    - 429 (Too Many Requests): Use Retry-After header if present, else backoff
    - 500, 502, 503, 504: Exponential backoff
    - Timeout: Retry with same timeout

    Backoff formula: delay = min(base_delay * 2^attempt + jitter, max_delay)
    """

    TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
    TRANSIENT_EXCEPTIONS = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )

    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def should_retry(
        self,
        exception: Optional[Exception],
        response: Optional[requests.Response],
        attempt: int
    ) -> bool:
        """Determine if request should be retried."""
        if attempt >= self.max_retries:
            return False

        # Retry on connection/timeout errors
        if exception and isinstance(exception, self.TRANSIENT_EXCEPTIONS):
            return True

        # Retry on transient HTTP status codes
        if response is not None and response.status_code in self.TRANSIENT_STATUS_CODES:
            return True

        return False

    def get_delay(
        self,
        attempt: int,
        response: Optional[requests.Response] = None
    ) -> float:
        """Calculate delay before next retry."""
        # Check Retry-After header first
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass

        # Exponential backoff with jitter
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = random.uniform(0, delay * 0.1)  # 10% jitter
        return delay + jitter


# =============================================================================
# SP-API Client
# =============================================================================

class SPAPIClient:
    """
    Centralized SP-API HTTP client with retry, rate limiting, and logging.

    Usage:
        client = SPAPIClient(access_token, region="NA")
        response = client.get(url, api_type="inventory")
        response = client.post(url, json=payload, api_type="reports_create")

    Configuration via environment variables:
        SP_API_MAX_RETRIES: Max retry attempts (default: 5)
        SP_API_BASE_DELAY: Initial backoff delay in seconds (default: 1.0)
        SP_API_MAX_DELAY: Max backoff delay in seconds (default: 60.0)
        SP_API_TIMEOUT: Request timeout in seconds (default: 30)
    """

    def __init__(
        self,
        access_token: str,
        region: str = "NA",
        max_retries: int = None,
        base_delay: float = None,
        max_delay: float = None,
        timeout: int = None
    ):
        self.access_token = access_token
        self.region = region

        # Load from env vars with defaults
        self.max_retries = max_retries or int(os.environ.get("SP_API_MAX_RETRIES", 5))
        self.base_delay = base_delay or float(os.environ.get("SP_API_BASE_DELAY", 1.0))
        self.max_delay = max_delay or float(os.environ.get("SP_API_MAX_DELAY", 60.0))
        self.timeout = timeout or int(os.environ.get("SP_API_TIMEOUT", 30))

        # Initialize helpers
        self.rate_limiter = RateLimitHandler()
        self.retry_strategy = RetryStrategy(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            max_delay=self.max_delay
        )

        # Request session for connection pooling
        self.session = requests.Session()

        # Statistics
        self.stats = {
            "requests": 0,
            "retries": 0,
            "rate_limit_waits": 0,
            "errors": 0
        }

    def _add_auth_header(self, headers: dict) -> dict:
        """Add access token to headers if not present."""
        if "x-amz-access-token" not in headers:
            headers["x-amz-access-token"] = self.access_token
        return headers

    def request(
        self,
        method: str,
        url: str,
        api_type: str = "default",
        **kwargs
    ) -> requests.Response:
        """
        Make an HTTP request with retry and rate limiting.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL
            api_type: API type for rate limit handling
            **kwargs: Passed to requests (json, params, headers, etc.)

        Returns:
            Response object

        Raises:
            SPAPIError: After max retries exhausted or fatal error
        """
        # Ensure headers dict exists
        kwargs.setdefault("headers", {})
        kwargs["headers"] = self._add_auth_header(kwargs["headers"])

        # Set timeout
        kwargs.setdefault("timeout", self.timeout)

        attempt = 0
        last_exception = None
        last_response = None

        while True:
            # Rate limiting
            self.rate_limiter.wait_if_needed(api_type)

            try:
                self.stats["requests"] += 1
                logger.debug(f"Request {method} {url} (attempt {attempt + 1})")

                response = self.session.request(method, url, **kwargs)

                # Record request time and update rate limits
                self.rate_limiter.record_request(api_type)
                self.rate_limiter.update_from_response(api_type, response)

                # Success
                if response.status_code < 400:
                    return response

                # Check if we should retry
                if self.retry_strategy.should_retry(None, response, attempt):
                    delay = self.retry_strategy.get_delay(attempt, response)
                    self.stats["retries"] += 1

                    status_msg = f"HTTP {response.status_code}"
                    if response.status_code == 429:
                        self.stats["rate_limit_waits"] += 1
                        status_msg = "Rate limited (429)"

                    logger.warning(
                        f"{status_msg} on {method} {url}. "
                        f"Retry {attempt + 1}/{self.max_retries} in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    attempt += 1
                    last_response = response
                    continue

                # Non-retryable error
                self.stats["errors"] += 1
                error_body = None
                try:
                    error_body = response.json()
                except:
                    pass

                if response.status_code == 429:
                    raise SPAPIRateLimitError(
                        f"Rate limit exceeded after {self.max_retries} retries",
                        status_code=response.status_code,
                        response_body=error_body
                    )
                elif response.status_code >= 500:
                    raise SPAPITransientError(
                        f"Server error: HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=error_body
                    )
                else:
                    raise SPAPIFatalError(
                        f"Request failed: HTTP {response.status_code}",
                        status_code=response.status_code,
                        response_body=error_body
                    )

            except self.retry_strategy.TRANSIENT_EXCEPTIONS as e:
                if self.retry_strategy.should_retry(e, None, attempt):
                    delay = self.retry_strategy.get_delay(attempt)
                    self.stats["retries"] += 1

                    logger.warning(
                        f"Connection error on {method} {url}: {type(e).__name__}. "
                        f"Retry {attempt + 1}/{self.max_retries} in {delay:.1f}s"
                    )
                    time.sleep(delay)
                    attempt += 1
                    last_exception = e
                    continue

                # Max retries exhausted
                self.stats["errors"] += 1
                raise SPAPITransientError(
                    f"Connection failed after {self.max_retries} retries: {str(e)}"
                )

    def get(self, url: str, api_type: str = "default", **kwargs) -> requests.Response:
        """Make a GET request."""
        return self.request("GET", url, api_type=api_type, **kwargs)

    def post(self, url: str, api_type: str = "default", **kwargs) -> requests.Response:
        """Make a POST request."""
        return self.request("POST", url, api_type=api_type, **kwargs)

    def get_stats(self) -> dict:
        """Get request statistics."""
        return self.stats.copy()

    def reset_stats(self):
        """Reset request statistics."""
        self.stats = {
            "requests": 0,
            "retries": 0,
            "rate_limit_waits": 0,
            "errors": 0
        }


# =============================================================================
# Convenience function for backward compatibility
# =============================================================================

def make_request_with_retry(
    method: str,
    url: str,
    access_token: str = None,
    api_type: str = "default",
    max_retries: int = 5,
    **kwargs
) -> requests.Response:
    """
    Convenience function for making a single request with retry.

    For use in places where creating a full SPAPIClient is overkill
    (e.g., token refresh).
    """
    client = SPAPIClient(
        access_token=access_token or "",
        max_retries=max_retries
    )
    return client.request(method, url, api_type=api_type, **kwargs)
