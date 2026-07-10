"""
src/search/domain_ranker.py
============================
Domain Ranking and Scoring Logic.

Calculates confidence scores for search result URLs based on keyword matching,
domain structures, and filters directory/social media directories.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)


class DomainRanker:
    """
    Ranks search results to find the most probable official homepage.
    """

    # Unwanted domain keywords that are rejected unless configured otherwise
    BLACKLISTED_DOMAINS = {
        "facebook.com", "linkedin.com", "yelp.com", "yellowpages.com",
        "zoominfo.com", "crunchbase.com", "wikipedia.org", "twitter.com",
        "instagram.com", "youtube.com", "pinterest.com", "doximity.com",
        "healthgrades.com", "vitals.com", "sharecare.com", "webmd.com",
        "groupon.com", "mapquest.com", "bbb.org", "local.yahoo.com",
        "whitepages.com", "spokeo.com", "radaris.com", "anywho.com"
    }

    def __init__(self, blacklisted_domains: Optional[List[str]] = None) -> None:
        self.blacklist = set(blacklisted_domains) if blacklisted_domains is not None else self.BLACKLISTED_DOMAINS

    def extract_domain(self, url: str) -> str:
        """Extract root domain (e.g. 'company.com' from 'https://www.company.com/about')."""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            # Remove 'www.' prefix
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ""

    def is_blacklisted(self, url: str) -> bool:
        """Check if domain is a known social media network or directory aggregator."""
        domain = self.extract_domain(url)
        if not domain:
            return True
            
        # Match exact domain or subdomains
        for black in self.blacklist:
            if domain == black or domain.endswith("." + black):
                return True
        return False

    def calculate_score(
        self,
        candidate_url: str,
        title: str,
        snippet: str,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> float:
        """
        Evaluate candidate search result and return confidence score between 0.0 and 1.0.
        """
        if self.is_blacklisted(candidate_url):
            return 0.0

        score = 0.1  # base score for any non-blacklisted URL
        domain = self.extract_domain(candidate_url)
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        biz_lower = business_name.lower()

        # Tokenize business name
        biz_tokens = [t for t in re.split(r'[^a-zA-Z0-9]', biz_lower) if len(t) > 2]
        
        # 1. Match business name in root domain (high weight)
        domain_no_ext = domain.split(".")[0]
        if biz_tokens:
            matches_in_domain = sum(1 for token in biz_tokens if token in domain_no_ext)
            match_ratio = matches_in_domain / len(biz_tokens)
            score += 0.4 * match_ratio

        # 2. Match business name in title (medium weight)
        if biz_tokens:
            matches_in_title = sum(1 for token in biz_tokens if token in title_lower)
            score += 0.2 * (matches_in_title / len(biz_tokens))

        # 3. Match business name in snippet (low weight)
        if biz_tokens:
            matches_in_snippet = sum(1 for token in biz_tokens if token in snippet_lower)
            score += 0.1 * (matches_in_snippet / len(biz_tokens))

        # 4. Clean domain penalty: give higher score to root homepages
        # URLs with long paths are penalized slightly
        parsed = urlparse(candidate_url)
        path = parsed.path.strip("/")
        if not path:
            score += 0.15  # clean homepage bonus
        else:
            # Check if path contains typical official landing indicators
            path_lower = path.lower()
            if any(k in path_lower for k in ("about", "contact", "home", "index")):
                score += 0.05
            # Penalize deep folders
            folders_count = len([f for f in path.split("/") if f])
            score -= min(0.1, folders_count * 0.03)

        # 5. City and State Matches (if provided)
        if city and city.lower() in snippet_lower:
            score += 0.05
        if state and state.lower() in snippet_lower:
            score += 0.05

        # Bound score between 0.0 and 1.0
        return max(0.0, min(1.0, round(score, 3)))

    def rank_candidates(
        self,
        candidates: List[Tuple[str, str, str]],
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """
        Sort list of candidate tuples (url, title, snippet) by score.
        
        Returns:
            Sorted list of tuples (url, confidence_score) descending.
        """
        scored_urls = []
        for url, title, snippet in candidates:
            score = self.calculate_score(url, title, snippet, business_name, city, state)
            if score > 0.15:  # filter out extremely low confidence noise
                scored_urls.append((url, score))
        
        # Sort by score descending
        scored_urls.sort(key=lambda x: x[1], reverse=True)
        return scored_urls
