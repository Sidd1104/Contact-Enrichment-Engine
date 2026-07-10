"""
src/scraper/page_discovery.py
==============================
Discovers and ranks candidate contact/about URLs from a homepage.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Tuple
from urllib.parse import urlparse
from .html_parser import ParsedHTML
from ..extractor.contact_page_detector import ContactPageDetector

logger = logging.getLogger(__name__)


class PageDiscovery:
    """
    Analyzes parsed HTML page links to extract, deduplicate, and rank potential contact page URLs.
    """

    def __init__(self, max_candidates: int = 5) -> None:
        self.max_candidates = max_candidates

    def discover_pages(self, parsed_html: ParsedHTML, base_url: str) -> List[Tuple[str, float]]:
        """
        Extracts, ranks, and returns candidate pages from the homepage.
        Returns a sorted list of (url, score) tuples.
        """
        candidates: Dict[str, float] = {}

        # 1. Parse links extracted from HTML
        for link in parsed_html.all_links:
            url = link["url"]
            text = link["text"]
            
            score = ContactPageDetector.evaluate_link(url, text, base_url)
            if score > 0.1:  # Only count candidates with positive heuristic scores
                # Keep the highest score if the URL is duplicate
                if url not in candidates or score > candidates[url]:
                    candidates[url] = score

        # 2. Add standard fallbacks if they are not already present in parsed links
        parsed_base = urlparse(base_url)
        scheme = parsed_base.scheme or "http"
        domain = parsed_base.netloc
        base_clean = f"{scheme}://{domain}"

        fallbacks = [
            ("/contact", 0.6),
            ("/contact-us", 0.6),
            ("/about", 0.5),
            ("/about-us", 0.5),
            ("/team", 0.5),
            ("/support", 0.5),
        ]

        for path, default_score in fallbacks:
            fallback_url = f"{base_clean.rstrip('/')}{path}"
            if fallback_url not in candidates:
                # Give standard fallbacks a moderate score if they weren't in the anchor tags
                candidates[fallback_url] = default_score

        # 3. Sort candidates by score descending
        sorted_candidates = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        
        # 4. Limit to max_candidates
        ranked_candidates = sorted_candidates[:self.max_candidates]
        logger.info(f"Discovered contact candidates for {base_url}: {[url for url, score in ranked_candidates]}")
        
        return ranked_candidates
