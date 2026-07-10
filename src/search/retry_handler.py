"""
src/search/retry_handler.py
============================
Search Retry System.

Wraps async operations with Tenacity retry policies using exponential backoff.
Filters out fatal authentication/input client errors and only retries transient issues.
"""

from __future__ import annotations

import logging
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class TransientSearchError(Exception):
    """Exception for transient issues (network timeouts, 5xx server issues, rate limits)."""
    pass


class FatalSearchError(Exception):
    """Exception for fatal issues (authentication, quota depletion, 400 Bad Request)."""
    pass


def get_retry_decorator(max_attempts: Optional[int] = None):
    """
    Build a tenacity retry decorator configured for transient search errors.
    """
    attempts = max_attempts or ai_config.search_max_retries
    
    return retry(
        retry=retry_if_exception_type(TransientSearchError),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1.0, min=2.0, max=15.0),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def check_httpx_status(response: httpx.Response) -> None:
    """
    Evaluate HTTP response and raise clean exceptions.
    """
    status = response.status_code
    if status == 200:
        return
        
    if status == 429:
        raise TransientSearchError(f"Rate limited (HTTP 429): {response.text[:200]}")
    elif status >= 500:
        raise TransientSearchError(f"Remote server error (HTTP {status}): {response.text[:200]}")
    elif status in (401, 403):
        raise FatalSearchError(f"Authentication failure (HTTP {status}): {response.text[:200]}")
    else:
        raise FatalSearchError(f"Request failed (HTTP {status}): {response.text[:200]}")
