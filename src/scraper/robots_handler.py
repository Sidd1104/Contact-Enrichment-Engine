"""
src/scraper/robots_handler.py
==============================
Asynchronous handler for downloading and parsing robots.txt rules.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx

logger = logging.getLogger(__name__)


class RobotsHandler:
    """
    Asynchronously checks crawling permissions via robots.txt with local caching.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._parsers: dict[str, RobotFileParser] = {}

    async def get_parser(self, base_url: str) -> RobotFileParser:
        """
        Retrieves or creates a RobotFileParser for a given domain/base_url.
        """
        parsed_url = urlparse(base_url)
        domain = parsed_url.netloc
        scheme = parsed_url.scheme or "http"
        robots_url = f"{scheme}://{domain}/robots.txt"

        if domain in self._parsers:
            return self._parsers[domain]

        parser = RobotFileParser()
        try:
            logger.info(f"Fetching robots.txt from: {robots_url}")
            response = await self._client.get(robots_url, follow_redirects=True)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                # If 404 or other error, parser defaults to allow all
                parser.parse([])
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt for {domain}: {e}. Defaulting to allow all.")
            parser.parse([])

        self._parsers[domain] = parser
        return parser

    async def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """
        Checks if the crawler is allowed to access the specified URL.
        """
        try:
            parser = await self.get_parser(url)
            return parser.can_fetch(user_agent, url)
        except Exception as e:
            logger.error(f"Error checking robots.txt for {url}: {e}. Defaulting to True.")
            return True
