"""
tests/test_ai_layer.py
========================
Unit tests for the AI Provider Layer (Phase 2A).

Tests cover:
  - Configuration loading and validation.
  - Base provider interface contracts.
  - Prompt manager template loading and rendering.
  - Gemini provider payload construction.
  - Router provider selection and fallback logic.
  - Structured response model validation.
  - Exception hierarchy.
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.base.provider import (
    AIProvider,
    AIResponse,
    ProviderHealth,
    AIError,
    TransientAIError,
    RateLimitError,
    FatalAIError,
)
from src.ai.models.response import EnrichedContact, SearchResult, ExtractionResult
from src.ai.prompts.prompt_manager import PromptManager
from src.ai.router.router import AIRouter, NoProvidersAvailableError


# =============================================================================
# Fixtures
# =============================================================================

class MockProvider(AIProvider):
    """A mock AI provider for testing router behavior."""

    def __init__(self, name: str = "mock", response_text: str = "mock response"):
        self._name = name
        self._response_text = response_text
        self._should_fail = False
        self._fail_error = None
        self._closed = False

    @property
    def name(self) -> str:
        return self._name

    async def query(self, prompt: str, timeout: float = 30.0) -> AIResponse:
        if self._should_fail and self._fail_error:
            raise self._fail_error
        return AIResponse(
            text=self._response_text,
            provider_name=self._name,
            model="mock-model",
            latency=0.1,
        )

    async def health_check(self) -> bool:
        return not self._should_fail

    async def close(self) -> None:
        self._closed = True

    def set_fail(self, error: Exception) -> None:
        self._should_fail = True
        self._fail_error = error

    def set_success(self, text: str = "mock response") -> None:
        self._should_fail = False
        self._fail_error = None
        self._response_text = text


# =============================================================================
# Test: Exception Hierarchy
# =============================================================================

class TestExceptionHierarchy:
    """Test that the exception hierarchy is correctly structured."""

    def test_transient_is_ai_error(self):
        assert issubclass(TransientAIError, AIError)

    def test_rate_limit_is_transient(self):
        assert issubclass(RateLimitError, TransientAIError)

    def test_fatal_is_ai_error(self):
        assert issubclass(FatalAIError, AIError)

    def test_rate_limit_has_retry_after(self):
        err = RateLimitError("rate limited", retry_after=120.0)
        assert err.retry_after == 120.0

    def test_transient_default_retry_after(self):
        err = TransientAIError("network error")
        assert err.retry_after == 0.0


# =============================================================================
# Test: ProviderHealth
# =============================================================================

class TestProviderHealth:
    """Test health tracking dataclass."""

    def test_initial_state(self):
        h = ProviderHealth()
        assert h.total_calls == 0
        assert h.is_healthy is True
        assert h.failure_rate == 0.0
        assert h.avg_latency == 999.0

    def test_record_success(self):
        h = ProviderHealth()
        h.record_success(0.5)
        assert h.total_calls == 1
        assert h.total_failures == 0
        assert h.consecutive_failures == 0
        assert h.avg_latency == 0.5

    def test_record_failure(self):
        h = ProviderHealth()
        h.record_failure(1.0)
        assert h.total_calls == 1
        assert h.total_failures == 1
        assert h.consecutive_failures == 1

    def test_success_resets_consecutive_failures(self):
        h = ProviderHealth()
        h.record_failure(1.0)
        h.record_failure(1.0)
        assert h.consecutive_failures == 2
        h.record_success(0.5)
        assert h.consecutive_failures == 0

    def test_reset(self):
        h = ProviderHealth()
        h.record_failure(1.0)
        h.is_healthy = False
        h.reset()
        assert h.total_calls == 0
        assert h.is_healthy is True


# =============================================================================
# Test: AIResponse
# =============================================================================

class TestAIResponse:
    """Test the standardized response wrapper."""

    def test_response_fields(self):
        resp = AIResponse(
            text="Hello world",
            provider_name="test",
            model="test-model",
            latency=1.5,
            retry_count=2,
        )
        assert resp.text == "Hello world"
        assert resp.provider_name == "test"
        assert resp.model == "test-model"
        assert resp.latency == 1.5
        assert resp.retry_count == 2


# =============================================================================
# Test: Structured Response Models
# =============================================================================

class TestEnrichedContact:
    """Test Pydantic response models."""

    def test_default_values(self):
        contact = EnrichedContact()
        assert contact.email == ""
        assert contact.phone == ""
        assert contact.confidence_score == 0.0

    def test_from_dict(self):
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "(555) 123-4567",
            "city": "New York",
            "state": "NY",
            "confidence_score": 0.85,
        }
        contact = EnrichedContact.model_validate(data)
        assert contact.first_name == "John"
        assert contact.email == "john@example.com"
        assert contact.confidence_score == 0.85

    def test_json_schema_generation(self):
        schema = EnrichedContact.model_json_schema()
        assert "properties" in schema
        assert "email" in schema["properties"]
        assert "phone" in schema["properties"]

    def test_extraction_result_wrapper(self):
        result = ExtractionResult(
            contact=EnrichedContact(email="test@test.com"),
            provider_used="gemini",
            model_used="gemini-2.5-flash",
            extraction_latency=2.5,
        )
        assert result.contact.email == "test@test.com"
        assert result.provider_used == "gemini"


# =============================================================================
# Test: Prompt Manager
# =============================================================================

class TestPromptManager:
    """Test prompt template loading and rendering."""

    def test_list_templates(self):
        pm = PromptManager()
        templates = pm.list_templates()
        assert "contact_extraction" in templates
        assert "web_discovery" in templates

    def test_load_contact_extraction(self):
        pm = PromptManager()
        template = pm.get_template("contact_extraction")
        assert "{first_name}" in template
        assert "{last_name}" in template
        assert "{npi}" in template

    def test_render_with_variables(self):
        pm = PromptManager()
        rendered = pm.render(
            "contact_extraction",
            first_name="Jane",
            last_name="Smith",
            npi="1234567890",
            address="123 Main St",
            city="Chicago",
            state="IL",
            country="US",
        )
        assert "Jane" in rendered
        assert "Smith" in rendered
        assert "1234567890" in rendered
        assert "Chicago" in rendered

    def test_render_missing_variable_defaults_empty(self):
        pm = PromptManager()
        rendered = pm.render(
            "contact_extraction",
            first_name="Test",
            last_name="User",
        )
        # Missing variables should render as empty string, not raise
        assert "Test" in rendered
        assert "{first_name}" not in rendered

    def test_render_raw(self):
        pm = PromptManager()
        result = pm.render_raw("Hello {name}, you have {count} items.", name="World")
        assert "Hello World" in result

    def test_missing_template_raises(self):
        pm = PromptManager()
        with pytest.raises(FileNotFoundError):
            pm.get_template("nonexistent_template_xyz")

    def test_cache_reload(self):
        pm = PromptManager()
        pm.get_template("contact_extraction")
        assert "contact_extraction" in pm._cache
        pm.reload("contact_extraction")
        assert "contact_extraction" not in pm._cache


# =============================================================================
# Test: Router
# =============================================================================

class TestAIRouter:
    """Test router provider selection and fallback."""

    def test_register_provider(self):
        router = AIRouter()
        mock = MockProvider("test_provider")
        router.register_provider(mock)
        assert "test_provider" in router.registered_providers

    @pytest.mark.asyncio
    async def test_query_routes_to_provider(self):
        router = AIRouter()
        mock = MockProvider("mock", response_text="success")
        router.register_provider(mock)

        response = await router.query("Hello", timeout=5.0)
        assert response.text == "success"
        assert response.provider_name == "mock"

    @pytest.mark.asyncio
    async def test_fallback_on_transient_error(self):
        router = AIRouter()

        primary = MockProvider("primary", response_text="primary response")
        primary.set_fail(TransientAIError("temporary failure"))

        fallback = MockProvider("fallback", response_text="fallback response")

        # Manually set priority order
        router._priority_order = ["primary", "fallback"]
        router.register_provider(primary)
        router.register_provider(fallback)

        response = await router.query("Hello", timeout=5.0)
        assert response.text == "fallback response"
        assert response.provider_name == "fallback"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self):
        router = AIRouter()
        mock = MockProvider("mock")
        mock.set_fail(TransientAIError("fail"))
        router.register_provider(mock)

        with pytest.raises(NoProvidersAvailableError):
            await router.query("Hello", timeout=5.0)

    @pytest.mark.asyncio
    async def test_rate_limited_provider_skipped(self):
        router = AIRouter()

        limited = MockProvider("limited")
        limited.set_fail(RateLimitError("rate limited", retry_after=300.0))

        healthy = MockProvider("healthy", response_text="ok")

        router._priority_order = ["limited", "healthy"]
        router.register_provider(limited)
        router.register_provider(healthy)

        response = await router.query("Hello", timeout=5.0)
        # First call should hit limited, get rate limited, then fall back to healthy
        assert response.provider_name == "healthy"

    def test_provider_stats(self):
        router = AIRouter()
        mock = MockProvider("test")
        router.register_provider(mock)
        stats = router.provider_stats()
        assert "test" in stats
        assert stats["test"]["total_calls"] == 0
        assert stats["test"]["is_healthy"] is True

    def test_reset_all_health(self):
        router = AIRouter()
        mock = MockProvider("test")
        router.register_provider(mock)
        router._health["test"].is_healthy = False
        router._health["test"].consecutive_failures = 10
        router.reset_all_health()
        assert router._health["test"].is_healthy is True
        assert router._health["test"].consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_stop_closes_providers(self):
        router = AIRouter()
        mock = MockProvider("test")
        router.register_provider(mock)
        await router.stop()
        assert mock._closed is True


# =============================================================================
# Test: Gemini Provider (unit tests with mocked HTTP)
# =============================================================================

class TestGeminiProvider:
    """Test Gemini provider payload construction and response parsing."""

    def test_pydantic_to_gemini_schema(self):
        from src.ai.providers.gemini import _pydantic_to_gemini_schema
        schema = _pydantic_to_gemini_schema(EnrichedContact)
        assert "properties" in schema
        assert "email" in schema["properties"]
        # Should not contain 'title' (Gemini doesn't support it)
        assert "title" not in schema

    def test_build_payload_basic(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")
        payload = provider._build_payload("Hello world")
        assert "contents" in payload
        assert payload["contents"][0]["parts"][0]["text"] == "Hello world"
        assert "generationConfig" in payload

    def test_build_payload_with_schema(self):
        from src.ai.providers.gemini import GeminiProvider, _pydantic_to_gemini_schema
        provider = GeminiProvider(api_key="test-key")
        schema = _pydantic_to_gemini_schema(EnrichedContact)
        payload = provider._build_payload("Extract contacts", response_schema=schema)
        gen_config = payload["generationConfig"]
        assert gen_config["responseMimeType"] == "application/json"
        assert "responseSchema" in gen_config

    def test_extract_text_valid(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")
        response_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello from Gemini"}]
                    }
                }
            ]
        }
        text = provider._extract_text(response_data)
        assert text == "Hello from Gemini"

    def test_extract_text_empty_candidates_raises(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")
        with pytest.raises(FatalAIError):
            provider._extract_text({"candidates": []})

    def test_name_property(self):
        from src.ai.providers.gemini import GeminiProvider
        provider = GeminiProvider(api_key="test-key")
        assert provider.name == "gemini"


# =============================================================================
# Test: Configuration
# =============================================================================

class TestAIConfig:
    """Test configuration loading."""

    def test_config_loads(self):
        from src.config.ai_config import AIConfig
        config = AIConfig(
            gemini_api_key="test-key",
            ai_timeout=45.0,
            ai_max_retries=5,
        )
        assert config.gemini_api_key == "test-key"
        assert config.ai_timeout == 45.0
        assert config.ai_max_retries == 5

    def test_parse_provider_order_from_string(self):
        from src.config.ai_config import AIConfig
        config = AIConfig(ai_provider_order="gemini,openai,deepseek")
        assert config.ai_provider_order == ["gemini", "openai", "deepseek"]

    def test_parse_provider_order_from_json_string(self):
        from src.config.ai_config import AIConfig
        config = AIConfig(ai_provider_order='["gemini", "openai"]')
        assert config.ai_provider_order == ["gemini", "openai"]

    def test_has_provider_key(self):
        from src.config.ai_config import AIConfig
        config = AIConfig(gemini_api_key="real-key", openai_api_key="")
        assert config.has_provider_key("gemini") is True
        assert config.has_provider_key("openai") is False
        assert config.has_provider_key("unknown") is False

    def test_default_model(self):
        from src.config.ai_config import AIConfig
        config = AIConfig()
        assert config.gemini_model == "gemini-flash-lite-latest"
