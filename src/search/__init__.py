"""
src/search/__init__.py
=======================
Search Engine & Website Discovery Layer.

Exposes interfaces for dynamic website discovery, provider routing,
caching, domain validation, and metrics logging.
"""

from .search_engine import SearchEngine
from .search_manager import SearchManager
from .search_result import SearchResolution
from .search_provider import SearchProvider, GeminiSearchProvider, BingSearchProvider
from .provider_router import ProviderRouter
from .domain_ranker import DomainRanker
from .search_validator import SearchValidator
from .cache_manager import SearchCache, FileSearchCache
from .metrics import SearchMetrics

__all__ = [
    "SearchEngine",
    "SearchManager",
    "SearchResolution",
    "SearchProvider",
    "GeminiSearchProvider",
    "BingSearchProvider",
    "ProviderRouter",
    "DomainRanker",
    "SearchValidator",
    "SearchCache",
    "FileSearchCache",
    "SearchMetrics",
]
