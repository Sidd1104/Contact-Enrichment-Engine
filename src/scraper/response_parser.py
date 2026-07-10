"""
src/scraper/response_parser.py
===============================
Standardization utility to convert client responses into ScrapedPage instances.
"""

from __future__ import annotations

from typing import Dict, Any
import httpx
from .scraper_result import ScrapedPage


def parse_httpx_response(response: httpx.Response, latency: float) -> ScrapedPage:
    """
    Parses a standard httpx.Response into ScrapedPage.
    """
    headers = {k.lower(): v for k, v in response.headers.items()}
    return ScrapedPage(
        url=str(response.url),
        status_code=response.status_code,
        html=response.text,
        headers=headers,
        latency=latency,
        method="HTTP"
    )


def parse_playwright_response(
    url: str,
    status_code: int,
    html: str,
    headers: Dict[str, str],
    latency: float,
    error_message: str | None = None
) -> ScrapedPage:
    """
    Parses browser automation parameters into ScrapedPage.
    """
    lower_headers = {k.lower(): v for k, v in headers.items()}
    return ScrapedPage(
        url=url,
        status_code=status_code,
        html=html,
        headers=lower_headers,
        latency=latency,
        error_message=error_message,
        method="Browser"
    )
