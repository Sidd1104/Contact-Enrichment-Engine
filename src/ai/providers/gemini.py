"""
src/ai/providers/gemini.py
============================
Google Gemini API Provider.

Implements the AIProvider interface using httpx async HTTP client to
communicate directly with the Gemini REST API (generateContent endpoint).

Features:
  - Async HTTP with configurable timeouts.
  - Exponential backoff retry via tenacity for transient errors.
  - Structured JSON output using Gemini's native response_schema.
  - Comprehensive logging (never logs API keys).
  - Clean resource management with explicit close().
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Type

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

from ..base.provider import (
    AIProvider,
    AIResponse,
    TransientAIError,
    RateLimitError,
    FatalAIError,
)
from ...config.ai_config import ai_config

logger = logging.getLogger(__name__)


def _pydantic_to_gemini_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """
    Convert a Pydantic model's JSON schema into the format Gemini expects
    for its response_schema parameter.
    
    Gemini uses a subset of OpenAPI 3.0 schema. We strip unsupported keys
    and ensure the format is compatible.
    """
    schema = model_class.model_json_schema()

    def _clean(obj: Any) -> Any:
        """Recursively clean schema for Gemini compatibility."""
        if isinstance(obj, dict):
            cleaned = {}
            for key, value in obj.items():
                # Gemini doesn't support these OpenAPI extensions
                if key in ("title", "$defs", "definitions", "default", "examples"):
                    continue
                cleaned[key] = _clean(value)
            return cleaned
        elif isinstance(obj, list):
            return [_clean(item) for item in obj]
        return obj

    return _clean(schema)


class GeminiProvider(AIProvider):
    """
    Google Gemini API provider using direct REST calls via httpx.
    
    This implementation:
    - Uses the generateContent endpoint for text generation.
    - Supports structured JSON output via response_schema parameter.
    - Handles rate limiting (HTTP 429) with automatic retry.
    - Handles transient errors (5xx) with exponential backoff.
    - Never logs or exposes API keys.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self._api_key = api_key or ai_config.gemini_api_key
        self._model = model or ai_config.gemini_model
        self._base_url = (base_url or ai_config.gemini_base_url).rstrip("/")
        self._timeout = timeout or ai_config.ai_timeout
        self._max_retries = max_retries or ai_config.ai_max_retries
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "gemini"

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def _build_url(self) -> str:
        """Build the generateContent API endpoint URL."""
        return (
            f"{self._base_url}/models/{self._model}"
            f":generateContent?key={self._api_key}"
        )

    def _build_payload(
        self,
        prompt: str,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the request payload for the Gemini generateContent API.
        
        Args:
            prompt:          The user prompt text.
            response_schema: Optional Gemini-compatible JSON schema for structured output.
        """
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
            },
        }

        if response_schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = response_schema

        return payload

    async def _make_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the HTTP POST to Gemini and handle error responses.
        
        This method is wrapped with tenacity retry logic for transient errors.
        
        Raises:
            RateLimitError:    On HTTP 429.
            TransientAIError:  On HTTP 5xx or network errors.
            FatalAIError:      On HTTP 4xx (except 429).
        """
        client = self._get_client()
        url = self._build_url()

        # Log request start (never log the API key or full URL)
        logger.info(
            f"[Gemini] Sending request to model={self._model}, "
            f"payload_size={len(json.dumps(payload))} bytes"
        )

        try:
            response = await client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise TransientAIError(f"Gemini request timed out: {e}")
        except httpx.ConnectError as e:
            raise TransientAIError(f"Gemini connection error: {e}")
        except httpx.HTTPError as e:
            raise TransientAIError(f"Gemini HTTP error: {e}")

        status = response.status_code

        if status == 200:
            return response.json()
        elif status == 429:
            # Parse retry-after header if available
            retry_after = float(response.headers.get("Retry-After", "60"))
            raise RateLimitError(
                f"Gemini rate limited (429). Retry after {retry_after}s.",
                retry_after=retry_after,
            )
        elif status >= 500:
            raise TransientAIError(
                f"Gemini server error ({status}): {response.text[:300]}"
            )
        elif status == 401 or status == 403:
            raise FatalAIError(
                f"Gemini authentication failed ({status}). "
                f"Check your GEMINI_API_KEY. Response: {response.text[:300]}"
            )
        else:
            raise FatalAIError(
                f"Gemini request failed ({status}): {response.text[:500]}"
            )

    def _extract_text(self, response_data: Dict[str, Any]) -> str:
        """Extract the generated text from the Gemini API response."""
        try:
            candidates = response_data.get("candidates", [])
            if not candidates:
                raise FatalAIError("Gemini returned no candidates in the response.")

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                raise FatalAIError("Gemini returned empty parts in the response.")

            return parts[0].get("text", "")
        except (KeyError, IndexError) as e:
            raise FatalAIError(f"Failed to extract text from Gemini response: {e}")

    async def query(self, prompt: str, timeout: float = 30.0) -> AIResponse:
        """
        Send a prompt to Gemini and return a standardized AIResponse.
        
        Includes retry logic with exponential backoff for transient errors.
        """
        if not self._api_key:
            raise FatalAIError(
                "Gemini API key not configured. Set GEMINI_API_KEY in your .env file."
            )

        payload = self._build_payload(prompt)
        start_time = time.monotonic()
        retry_count = 0

        # Build retry-wrapped function
        @retry(
            retry=retry_if_exception_type(TransientAIError),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(
                multiplier=ai_config.ai_retry_base_delay,
                max=ai_config.ai_retry_max_delay,
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _execute():
            nonlocal retry_count
            retry_count += 1
            return await self._make_request(payload)

        try:
            retry_count = 0
            response_data = await asyncio.wait_for(
                _execute(), timeout=timeout
            )
        except RetryError as e:
            latency = time.monotonic() - start_time
            logger.error(
                f"[Gemini] All {self._max_retries} retries exhausted "
                f"after {latency:.2f}s. Last error: {e.last_attempt.exception()}"
            )
            raise TransientAIError(
                f"Gemini failed after {self._max_retries} retries: "
                f"{e.last_attempt.exception()}"
            )
        except asyncio.TimeoutError:
            latency = time.monotonic() - start_time
            logger.error(
                f"[Gemini] Request timed out after {latency:.2f}s "
                f"(limit: {timeout}s)"
            )
            raise

        latency = time.monotonic() - start_time
        text = self._extract_text(response_data)

        logger.info(
            f"[Gemini] Response received: "
            f"model={self._model}, latency={latency:.2f}s, "
            f"retries={max(0, retry_count - 1)}, "
            f"response_length={len(text)} chars"
        )

        return AIResponse(
            text=text,
            provider_name=self.name,
            model=self._model,
            latency=latency,
            retry_count=max(0, retry_count - 1),
            metadata={
                "usage": response_data.get("usageMetadata", {}),
            },
        )

    async def query_structured(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        timeout: float = 30.0,
    ) -> BaseModel:
        """
        Send a prompt to Gemini with a JSON schema constraint,
        ensuring the response adheres to the Pydantic model's structure.
        
        This uses Gemini's native response_schema feature for guaranteed
        structured output — no post-processing regex needed.
        """
        if not self._api_key:
            raise FatalAIError(
                "Gemini API key not configured. Set GEMINI_API_KEY in your .env file."
            )

        gemini_schema = _pydantic_to_gemini_schema(response_model)
        payload = self._build_payload(prompt, response_schema=gemini_schema)
        start_time = time.monotonic()
        retry_count = 0

        @retry(
            retry=retry_if_exception_type(TransientAIError),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(
                multiplier=ai_config.ai_retry_base_delay,
                max=ai_config.ai_retry_max_delay,
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _execute():
            nonlocal retry_count
            retry_count += 1
            return await self._make_request(payload)

        try:
            retry_count = 0
            response_data = await asyncio.wait_for(
                _execute(), timeout=timeout
            )
        except RetryError as e:
            raise TransientAIError(
                f"Gemini structured query failed after {self._max_retries} retries"
            )

        latency = time.monotonic() - start_time
        text = self._extract_text(response_data)

        logger.info(
            f"[Gemini] Structured response: model={self._model}, "
            f"latency={latency:.2f}s, retries={max(0, retry_count - 1)}"
        )

        try:
            parsed = json.loads(text)
            return response_model.model_validate(parsed)
        except (json.JSONDecodeError, Exception) as e:
            raise FatalAIError(
                f"Failed to parse Gemini structured response into "
                f"{response_model.__name__}: {e}\n"
                f"Raw response: {text[:500]}"
            )

    async def health_check(self) -> bool:
        """
        Verify Gemini API connectivity with a minimal test prompt.
        """
        try:
            response = await self.query(
                "Reply with exactly: OK",
                timeout=10.0,
            )
            return bool(response.text.strip())
        except Exception as e:
            logger.warning(f"[Gemini] Health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close the httpx client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("[Gemini] HTTP client closed.")
        self._client = None
