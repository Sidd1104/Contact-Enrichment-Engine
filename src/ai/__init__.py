"""
src/ai/__init__.py
===================
AI Module — Contact Enrichment Engine.

This package provides the AI provider abstraction layer:
  - base/       : Abstract interface, exceptions, health tracking.
  - providers/  : Concrete provider implementations (Gemini, OpenAI, etc.).
  - router/     : Intelligent provider routing and failover.
  - prompts/    : Dynamic prompt template management.
  - models/     : Structured Pydantic response schemas.
"""

from .base import (
    AIProvider,
    AIResponse,
    ProviderHealth,
    AIError,
    TransientAIError,
    RateLimitError,
    FatalAIError,
)
from .providers import GeminiProvider
from .router import AIRouter, NoProvidersAvailableError
from .prompts import prompt_manager
from .models import EnrichedContact, SearchResult, ExtractionResult
from .enrichment_result import AIEnrichmentResult, AIEnrichmentResponseModel
from .enrichment_prompts import EnrichmentPrompts
from .enrichment_router import AIEnrichmentRouter
from .merge_engine import MergeEngine
from .ai_metrics import AIMetrics
from .enrichment_manager import AIEnrichmentManager

__all__ = [
    # Base
    "AIProvider",
    "AIResponse",
    "ProviderHealth",
    "AIError",
    "TransientAIError",
    "RateLimitError",
    "FatalAIError",
    # Providers
    "GeminiProvider",
    # Router
    "AIRouter",
    "NoProvidersAvailableError",
    # Prompts
    "prompt_manager",
    # Models
    "EnrichedContact",
    "SearchResult",
    "ExtractionResult",
    # Enrichment
    "AIEnrichmentResult",
    "AIEnrichmentResponseModel",
    "EnrichmentPrompts",
    "AIEnrichmentRouter",
    "MergeEngine",
    "AIMetrics",
    "AIEnrichmentManager",
]
