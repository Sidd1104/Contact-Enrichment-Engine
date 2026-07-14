"""
src/ai/base/provider.py
========================
Abstract AI Provider Interface & Custom Exceptions.

All AI providers (Gemini, OpenAI, DeepSeek, Groq, Claude) implement this
interface. The Router only depends on this contract — never on a concrete
provider — enabling clean provider swapping and multi-provider fallback.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections import deque
from typing import Any, Deque, Dict, Optional, Type

from pydantic import BaseModel


# =============================================================================
# Custom Exception Hierarchy
# =============================================================================

class AIError(Exception):
    """Base exception for all AI provider errors."""
    pass


class TransientAIError(AIError):
    """
    Retryable error — the request might succeed if retried.
    
    Examples: Rate limiting (HTTP 429), temporary server errors (5xx),
    network timeouts, connection resets.
    """
    def __init__(self, message: str = "", retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after  # Seconds to wait before retry


class RateLimitError(TransientAIError):
    """Specific case of TransientAIError for HTTP 429 rate limits."""
    def __init__(self, message: str = "", retry_after: float = 60.0):
        super().__init__(message, retry_after=retry_after)


class FatalAIError(AIError):
    """
    Non-retryable error — retrying will not help.
    
    Examples: Authentication failure (HTTP 401/403), malformed request (400),
    model not found, invalid API key.
    """
    pass


# =============================================================================
# Provider Health Tracking
# =============================================================================

@dataclass
class ProviderHealth:
    """
    Runtime health statistics for a single provider.
    Updated by the Router after each call to track reliability and performance.
    """
    total_calls: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    is_healthy: bool = True
    is_rate_limited: bool = False
    rate_limit_reset_at: float = 0.0  # Unix timestamp
    latency_window: Deque[float] = field(
        default_factory=lambda: deque(maxlen=100)
    )

    @property
    def failure_rate(self) -> float:
        """Percentage of calls that failed."""
        return (self.total_failures / self.total_calls) if self.total_calls else 0.0

    @property
    def success_rate(self) -> float:
        """Percentage of calls that succeeded."""
        return 1.0 - self.failure_rate

    @property
    def avg_latency(self) -> float:
        """Average response time in seconds over the recent window."""
        return (
            sum(self.latency_window) / len(self.latency_window)
            if self.latency_window
            else 999.0
        )

    def record_success(self, latency: float) -> None:
        """Record a successful call."""
        self.total_calls += 1
        self.consecutive_failures = 0
        self.latency_window.append(latency)

    def record_failure(self, latency: float) -> None:
        """Record a failed call."""
        self.total_calls += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.latency_window.append(latency)

    def mark_rate_limited(self, retry_after: float) -> None:
        """Flag this provider as rate-limited until a given time."""
        import time
        self.is_rate_limited = True
        self.rate_limit_reset_at = time.time() + retry_after

    def reset(self) -> None:
        """Reset all health metrics to clean state."""
        self.total_calls = 0
        self.total_failures = 0
        self.consecutive_failures = 0
        self.is_healthy = True
        self.is_rate_limited = False
        self.rate_limit_reset_at = 0.0
        self.latency_window.clear()


# =============================================================================
# AI Response Wrapper
# =============================================================================

@dataclass
class AIResponse:
    """
    Standardized response envelope returned by every AI provider call.
    
    Attributes:
        text:          Raw text response from the AI.
        provider_name: Which provider generated this response.
        model:         The specific model used (e.g. "gemini-2.5-flash").
        latency:       Time taken in seconds.
        retry_count:   Number of retries before success.
        metadata:      Any additional provider-specific metadata.
    """
    text: str
    provider_name: str
    model: str = ""
    latency: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Abstract AI Provider
# =============================================================================

class AIProvider(ABC):
    """
    Abstract base class for all AI providers.
    
    Implementations must be async-safe and must not hold mutable state
    that would be corrupted by concurrent coroutine calls.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this provider.
        Examples: 'gemini', 'openai', 'deepseek', 'groq', 'claude'
        """
        ...

    @abstractmethod
    async def query(self, prompt: str, timeout: float = 30.0) -> AIResponse:
        """
        Send a prompt to the AI and return a standardized response.
        
        Args:
            prompt:  The full prompt string to send.
            timeout: Maximum seconds to wait for a response.
            
        Returns:
            AIResponse with raw text and metadata.
            
        Raises:
            asyncio.TimeoutError: Response exceeded timeout.
            RateLimitError:       Provider returned HTTP 429.
            TransientAIError:     Temporary failure (network, 5xx).
            FatalAIError:         Non-retryable failure (auth, 4xx).
        """
        ...

    async def query_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> BaseModel:
        """
        Send a prompt and parse the response into a Pydantic model.
        
        Default implementation calls query() and parses JSON from the text.
        Providers can override this to use native structured output features
        (e.g. Gemini's response_schema).
        
        Args:
            prompt:         The prompt to send.
            response_model: Pydantic model class to parse the response into.
            timeout:        Maximum seconds to wait.
            
        Returns:
            Parsed Pydantic model instance.
            
        Raises:
            FatalAIError: If the response cannot be parsed into the model.
        """
        import json as json_mod

        response = await self.query(prompt, timeout=timeout)
        try:
            # Try to extract JSON from the response text
            text = response.text.strip()
            # Handle markdown-wrapped JSON
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last lines (```json and ```)
                json_lines = []
                in_block = False
                for line in lines:
                    if line.strip().startswith("```") and not in_block:
                        in_block = True
                        continue
                    elif line.strip() == "```" and in_block:
                        break
                    elif in_block:
                        json_lines.append(line)
                text = "\n".join(json_lines)
            
            parsed = json_mod.loads(text)
            return response_model.model_validate(parsed)
        except (json_mod.JSONDecodeError, Exception) as e:
            raise FatalAIError(
                f"Failed to parse AI response into {response_model.__name__}: {e}\n"
                f"Raw response: {response.text[:500]}"
            )

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify that the provider is reachable and accepting requests.
        
        Returns:
            True if healthy, False if unavailable.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by this provider (HTTP clients, etc.)."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}'>"
