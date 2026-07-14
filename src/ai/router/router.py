"""
src/ai/router/router.py
=========================
AI Provider Router.

Dynamically selects the best AI provider based on configured priority order,
health status, and availability. Falls back through the provider chain if the
primary provider fails.

Features:
  - Priority-based provider selection from AI_PROVIDER_ORDER.
  - Automatic fallback on provider failure.
  - Health tracking per provider (consecutive failures, rate limits).
  - Background health recovery checks.
  - Comprehensive logging of routing decisions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional, Type

from pydantic import BaseModel

from ..base.provider import (
    AIProvider,
    AIResponse,
    ProviderHealth,
    AIError,
    TransientAIError,
    RateLimitError,
    FatalAIError,
)
from ...config.ai_config import ai_config

logger = logging.getLogger(__name__)


class NoProvidersAvailableError(AIError):
    """Raised when no providers are healthy and available for routing."""
    pass


class AIRouter:
    """
    Intelligent router that selects the best available AI provider.
    
    The router maintains a priority-ordered list of providers and routes
    requests to the highest-priority healthy provider. If a provider fails,
    the router marks it and falls back to the next available provider.
    
    Usage:
        router = AIRouter()
        router.register_provider(gemini_provider)
        router.register_provider(openai_provider)
        
        response = await router.query("Extract contacts from...")
    """

    MAX_CONSECUTIVE_FAILURES = 5
    HEALTH_CHECK_INTERVAL = 30.0  # seconds

    def __init__(self) -> None:
        self._providers: Dict[str, AIProvider] = {}
        self._health: Dict[str, ProviderHealth] = {}
        self._priority_order: List[str] = list(ai_config.ai_provider_order)
        self._health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def register_provider(self, provider: AIProvider) -> None:
        """
        Register an AI provider with the router.
        
        Providers not in the AI_PROVIDER_ORDER config will be appended
        at the end of the priority list.
        """
        name = provider.name
        self._providers[name] = provider
        self._health[name] = ProviderHealth()

        if name not in self._priority_order:
            self._priority_order.append(name)

        logger.info(
            f"[Router] Registered provider '{name}'. "
            f"Priority order: {self._priority_order}"
        )

    @property
    def registered_providers(self) -> List[str]:
        """List of registered provider names in priority order."""
        return [p for p in self._priority_order if p in self._providers]

    def start_health_checks(self) -> None:
        """Start the background health recovery loop."""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(
                self._health_check_loop(),
                name="ai_router_health_checker",
            )
            logger.info("[Router] Background health checks started.")

    async def stop(self) -> None:
        """Stop health checks and close all provider resources."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

        for name, provider in self._providers.items():
            try:
                await provider.close()
                logger.info(f"[Router] Provider '{name}' closed.")
            except Exception as e:
                logger.warning(f"[Router] Error closing provider '{name}': {e}")

    async def query(self, prompt: str, timeout: float = 0.0) -> AIResponse:
        """
        Route a prompt to the best available provider.
        
        Tries providers in priority order, skipping unhealthy or rate-limited
        providers. Falls back through the chain on failure.
        
        Args:
            prompt:  The prompt text to send.
            timeout: Override timeout (0 = use config default).
            
        Returns:
            AIResponse from the first successful provider.
            
        Raises:
            NoProvidersAvailableError: All providers are unavailable.
        """
        if timeout <= 0:
            timeout = ai_config.ai_timeout

        available = await self._get_available_providers()

        if not available:
            raise NoProvidersAvailableError(
                "No AI providers are available. All are unhealthy or rate-limited. "
                f"Registered: {list(self._providers.keys())}"
            )

        last_error: Optional[Exception] = None

        for provider in available:
            health = self._health[provider.name]
            start = time.monotonic()

            try:
                logger.info(
                    f"[Router] Routing to provider '{provider.name}' "
                    f"(priority position: {self._priority_order.index(provider.name) + 1})"
                )
                response = await provider.query(prompt, timeout=timeout)

                # Record success
                latency = time.monotonic() - start
                health.record_success(latency)

                logger.info(
                    f"[Router] Success from '{provider.name}': "
                    f"latency={latency:.2f}s, retries={response.retry_count}"
                )
                return response

            except RateLimitError as e:
                latency = time.monotonic() - start
                health.record_failure(latency)
                health.mark_rate_limited(e.retry_after)
                logger.warning(
                    f"[Router] Provider '{provider.name}' rate limited. "
                    f"Retry after {e.retry_after}s. Falling back..."
                )
                last_error = e
                continue

            except TransientAIError as e:
                latency = time.monotonic() - start
                health.record_failure(latency)
                if health.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    health.is_healthy = False
                    logger.error(
                        f"[Router] Provider '{provider.name}' marked unhealthy "
                        f"after {health.consecutive_failures} consecutive failures."
                    )
                else:
                    logger.warning(
                        f"[Router] Transient error from '{provider.name}': {e}. "
                        f"Falling back..."
                    )
                last_error = e
                continue

            except FatalAIError as e:
                latency = time.monotonic() - start
                health.record_failure(latency)
                health.is_healthy = False
                logger.error(
                    f"[Router] Fatal error from '{provider.name}': {e}. "
                    f"Provider marked unhealthy."
                )
                last_error = e
                continue

            except asyncio.TimeoutError as e:
                latency = time.monotonic() - start
                health.record_failure(latency)
                logger.warning(
                    f"[Router] Provider '{provider.name}' timed out "
                    f"after {latency:.2f}s. Falling back..."
                )
                last_error = e
                continue

        raise NoProvidersAvailableError(
            f"All {len(available)} providers failed. Last error: {last_error}"
        )

    async def query_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        timeout: float = 0.0,
        **kwargs: Any,
    ) -> BaseModel:
        """
        Route a structured query to the best available provider.
        
        Uses the provider's query_structured method for native schema support
        where available, otherwise falls back to query + JSON parsing.
        """
        if timeout <= 0:
            timeout = ai_config.ai_timeout

        available = await self._get_available_providers()

        if not available:
            raise NoProvidersAvailableError(
                "No AI providers available for structured query."
            )

        last_error: Optional[Exception] = None

        for provider in available:
            health = self._health[provider.name]
            start = time.monotonic()

            try:
                logger.info(
                    f"[Router] Structured query routed to '{provider.name}'"
                )
                result = await provider.query_structured(
                    prompt, response_model, timeout=timeout, **kwargs
                )

                latency = time.monotonic() - start
                health.record_success(latency)

                logger.info(
                    f"[Router] Structured response from '{provider.name}': "
                    f"latency={latency:.2f}s"
                )
                return result

            except (RateLimitError, TransientAIError, FatalAIError, asyncio.TimeoutError) as e:
                latency = time.monotonic() - start
                health.record_failure(latency)
                if isinstance(e, RateLimitError):
                    health.mark_rate_limited(e.retry_after)
                elif isinstance(e, FatalAIError) or (
                    isinstance(e, TransientAIError) and
                    health.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES
                ):
                    health.is_healthy = False
                logger.warning(
                    f"[Router] Error from '{provider.name}' during structured query: {e}"
                )
                last_error = e
                continue

        raise NoProvidersAvailableError(
            f"All providers failed for structured query. Last error: {last_error}"
        )

    async def _get_available_providers(self) -> List[AIProvider]:
        """
        Return a list of healthy, non-rate-limited providers
        sorted by priority order.
        """
        async with self._lock:
            now = time.time()

            # Auto-clear expired rate limits
            for name, health in self._health.items():
                if health.is_rate_limited and now >= health.rate_limit_reset_at:
                    health.is_rate_limited = False
                    logger.info(
                        f"[Router] Rate limit expired for '{name}'. "
                        f"Provider available again."
                    )

            available = []
            for name in self._priority_order:
                if name not in self._providers:
                    continue
                health = self._health[name]
                if health.is_healthy and not health.is_rate_limited:
                    available.append(self._providers[name])

            return available

    async def _health_check_loop(self) -> None:
        """Background loop to recover unhealthy providers."""
        try:
            while True:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                for name, health in self._health.items():
                    if not health.is_healthy and name in self._providers:
                        try:
                            provider = self._providers[name]
                            is_ok = await provider.health_check()
                            if is_ok:
                                health.is_healthy = True
                                health.consecutive_failures = 0
                                logger.info(
                                    f"[Router] Provider '{name}' recovered "
                                    f"and marked healthy."
                                )
                        except Exception:
                            pass  # Still unhealthy
        except asyncio.CancelledError:
            pass

    def reset_all_health(self) -> None:
        """Reset all provider health metrics to clean state."""
        for name, health in self._health.items():
            health.reset()
        logger.info("[Router] All provider health metrics reset.")

    def provider_stats(self) -> Dict[str, dict]:
        """Get health statistics for all registered providers."""
        return {
            name: {
                "total_calls": h.total_calls,
                "total_failures": h.total_failures,
                "failure_rate": round(h.failure_rate, 4),
                "success_rate": round(h.success_rate, 4),
                "avg_latency": round(h.avg_latency, 3),
                "consecutive_failures": h.consecutive_failures,
                "is_healthy": h.is_healthy,
                "is_rate_limited": h.is_rate_limited,
            }
            for name, h in self._health.items()
        }
