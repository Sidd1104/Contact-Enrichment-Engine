"""
src/scraper/http_scraper.py
============================
High-performance asynchronous HTTP client for website HTML acquisition.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
import httpx
from .scraper_result import ScrapedPage
from .response_parser import parse_httpx_response

logger = logging.getLogger(__name__)


class HTTPScraper:
    """
    Asynchronous scraper that handles connection pooling, retries, redirects, and timeouts.
    """

    def __init__(
        self,
        timeout: float = 10.0,
        retries: int = 3,
        backoff_factor: float = 1.0,
        max_connections: int = 50,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        
        # Setup modern default headers (User-Agent, Accept, Accept-Encoding)
        default_headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.5",
        }
        if headers:
            default_headers.update({k.lower(): v for k, v in headers.items()})

        # Connection pooling and keep-alive configuration
        limits = httpx.Limits(max_keepalive_connections=max_connections, max_connections=max_connections)
        self.client = httpx.AsyncClient(
            headers=default_headers,
            timeout=httpx.Timeout(timeout),
            limits=limits,
            follow_redirects=True
        )

    async def close(self) -> None:
        """Close the underlying client connections."""
        await self.client.aclose()

    async def __aenter__(self) -> HTTPScraper:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def scrape_page(self, url: str) -> ScrapedPage:
        """
        Scrapes a single URL asynchronously with exponential backoff retries.
        """
        last_error = None
        attempt = 0
        
        while attempt <= self.retries:
            start_time = time.perf_counter()
            try:
                logger.info(f"[HTTP] Ingesting {url} (Attempt {attempt + 1}/{self.retries + 1})")
                response = await self.client.get(url)
                latency = time.perf_counter() - start_time
                
                # Check for server side HTTP failures that warrant a retry
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Server error: {response.status_code}",
                        request=response.request,
                        response=response
                    )
                
                # Success!
                return parse_httpx_response(response, latency)

            except (httpx.HTTPError, asyncio.TimeoutError) as e:
                latency = time.perf_counter() - start_time
                last_error = str(e)
                attempt += 1
                logger.warning(f"[HTTP] Failed to retrieve {url} on attempt {attempt}: {e}")
                
                if attempt <= self.retries:
                    # Exponential backoff: backoff_factor * (2^attempt)
                    sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                    logger.info(f"[HTTP] Backing off for {sleep_time:.2f}s before retrying {url}")
                    await asyncio.sleep(sleep_time)
            except Exception as e:
                # Fatal unexpected error
                latency = time.perf_counter() - start_time
                last_error = f"Unexpected error: {str(e)}"
                logger.error(f"[HTTP] Fatal error scraping {url}: {e}")
                break

        # All attempts failed
        return ScrapedPage(
            url=url,
            status_code=0,
            html="",
            headers={},
            error_message=f"Failed after {attempt} attempts. Last error: {last_error}",
            latency=latency,
            method="HTTP"
        )
