"""
src/ai/base/__init__.py
========================
Public API for the AI base module.
"""

from .provider import (
    AIProvider,
    AIResponse,
    ProviderHealth,
    AIError,
    TransientAIError,
    RateLimitError,
    FatalAIError,
)

__all__ = [
    "AIProvider",
    "AIResponse",
    "ProviderHealth",
    "AIError",
    "TransientAIError",
    "RateLimitError",
    "FatalAIError",
]
