"""
src/search/provider_router.py
==============================
Search Provider Router.

Selects the best available search provider based on configured priority order
and current health/cooldown status.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from .search_provider import SearchProvider

logger = logging.getLogger(__name__)


class ProviderRouter:
    """
    Routes search queries to the first available healthy search provider.
    """

    def __init__(self, provider_list: List[SearchProvider], priority_order: List[str]) -> None:
        self.providers: Dict[str, SearchProvider] = {p.name: p for p in provider_list}
        self.priority_order = priority_order

    def select_provider(self) -> Optional[SearchProvider]:
        """
        Select the highest priority healthy search provider.
        """
        for name in self.priority_order:
            provider = self.providers.get(name)
            if provider and provider.is_healthy:
                logger.debug(f"[ProviderRouter] Selected active provider: '{name}'")
                return provider

        # Fallback: check if ANY provider is registered even if unhealthy (last resort)
        for name in self.priority_order:
            provider = self.providers.get(name)
            if provider:
                logger.warning(f"[ProviderRouter] All providers unhealthy. Falling back to key: '{name}'")
                return provider

        return None

    def get_providers(self) -> List[SearchProvider]:
        """Get list of registered providers."""
        return list(self.providers.values())
