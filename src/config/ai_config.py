"""
src/config/ai_config.py
========================
AI Provider Configuration.

Loads all AI-related settings from environment variables using Pydantic.
Never hardcodes API keys or sensitive credentials.
"""

from __future__ import annotations

import os
import json
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv()


class AIConfig(BaseModel):
    """
    Configuration for the AI provider layer.

    All values are read from environment variables. Defaults are provided
    for non-sensitive settings. API keys MUST be set in environment / .env.
    """

    # --- Gemini Configuration ---
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key."
    )
    gemini_model: str = Field(
        default="gemini-flash-lite-latest",
        description="Gemini model identifier to use."
    )
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        description="Gemini REST API base URL."
    )

    # --- OpenAI Configuration (placeholder for future) ---
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key (for future use)."
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model identifier."
    )

    # --- DeepSeek Configuration (placeholder for future) ---
    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API key (for future use)."
    )

    # --- Groq Configuration (placeholder for future) ---
    groq_api_key: str = Field(
        default="",
        description="Groq API key (for future use)."
    )

    # --- General AI Settings ---
    ai_timeout: float = Field(
        default=30.0,
        description="Maximum seconds to wait for an AI response."
    )
    ai_max_retries: int = Field(
        default=3,
        description="Number of retry attempts on transient failure."
    )
    ai_retry_base_delay: float = Field(
        default=1.0,
        description="Base delay in seconds for exponential backoff."
    )
    ai_retry_max_delay: float = Field(
        default=30.0,
        description="Maximum delay in seconds for exponential backoff."
    )
    ai_provider_order: List[str] = Field(
        default=["gemini"],
        description="Ordered list of preferred AI providers."
    )

    # --- Tavily Search Configuration ---
    tavily_api_key: str = Field(
        default="",
        description="Tavily search API key."
    )

    # --- Bing Search Configuration ---
    bing_api_key: str = Field(
        default="",
        description="Bing Search API key."
    )

    # --- Search Engine Configurations ---
    search_provider_order: List[str] = Field(
        default=["tavily", "bing"],
        description="Ordered list of preferred search providers."
    )
    search_concurrency: int = Field(
        default=5,
        description="Number of concurrent search requests allowed."
    )
    search_timeout: float = Field(
        default=15.0,
        description="Timeout in seconds for search requests."
    )
    search_max_retries: int = Field(
        default=3,
        description="Max retries for transient search errors."
    )
    search_cache_enabled: bool = Field(
        default=True,
        description="Enable search result caching."
    )
    search_cache_directory: str = Field(
        default="data/temp",
        description="Directory for local search cache file."
    )
    search_rate_limit: int = Field(
        default=60,
        description="Search requests allowed per minute."
    )

    # --- Worker Pool Configurations ---
    worker_count: int = Field(
        default=4,
        description="Number of active async worker loops."
    )
    max_queue_size: int = Field(
        default=1000,
        description="Maximum size of task queue."
    )
    heartbeat_interval: float = Field(
        default=2.0,
        description="Interval in seconds for worker heartbeats."
    )
    resource_monitor_interval: float = Field(
        default=5.0,
        description="Interval in seconds for CPU/RAM checks."
    )
    worker_metrics_file: str = Field(
        default="logs/worker_metrics.json",
        description="Path where worker metrics are saved."
    )
    queue_state_file: str = Field(
        default="data/temp/worker_queue_state.json",
        description="Path where task queue states are serialized."
    )

    @field_validator("ai_provider_order", "search_provider_order", mode="before")
    @classmethod
    def parse_list_settings(cls, v):
        """Parse list settings from JSON string or comma-separated string."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @classmethod
    def from_env(cls) -> "AIConfig":
        """
        Construct AIConfig from environment variables.
        """
        # Load environment values
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
            gemini_base_url=os.getenv(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta"
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            ai_timeout=float(os.getenv("AI_TIMEOUT", "30.0")),
            ai_max_retries=int(os.getenv("AI_MAX_RETRIES", "3")),
            ai_retry_base_delay=float(os.getenv("AI_RETRY_BASE_DELAY", "1.0")),
            ai_retry_max_delay=float(os.getenv("AI_RETRY_MAX_DELAY", "30.0")),
            ai_provider_order=os.getenv("AI_PROVIDER_ORDER", "gemini"),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            bing_api_key=os.getenv("BING_API_KEY", ""),
            search_provider_order=os.getenv("SEARCH_PROVIDER_ORDER", "tavily,bing"),
            search_concurrency=int(os.getenv("SEARCH_CONCURRENCY", "5")),
            search_timeout=float(os.getenv("SEARCH_TIMEOUT", "15.0")),
            search_max_retries=int(os.getenv("SEARCH_MAX_RETRIES", "3")),
            search_cache_enabled=os.getenv("SEARCH_CACHE_ENABLED", "true").lower() == "true",
            search_cache_directory=os.getenv("SEARCH_CACHE_DIRECTORY", "data/temp"),
            search_rate_limit=int(os.getenv("SEARCH_RATE_LIMIT", "60")),
            worker_count=int(os.getenv("WORKER_COUNT", "4")),
            max_queue_size=int(os.getenv("MAX_QUEUE_SIZE", "1000")),
            heartbeat_interval=float(os.getenv("HEARTBEAT_INTERVAL", "2.0")),
            resource_monitor_interval=float(os.getenv("RESOURCE_MONITOR_INTERVAL", "5.0")),
            worker_metrics_file=os.getenv("WORKER_METRICS_FILE", "logs/worker_metrics.json"),
            queue_state_file=os.getenv("QUEUE_STATE_FILE", "data/temp/worker_queue_state.json"),
        )

    def has_provider_key(self, provider_name: str) -> bool:
        """Check if the API key for a given provider is configured."""
        key_map = {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "groq": self.groq_api_key,
            "tavily": self.tavily_api_key,
            "bing": self.bing_api_key,
        }
        key = key_map.get(provider_name, "")
        return bool(key and key.strip())


# Singleton instance — import this across the application
ai_config = AIConfig.from_env()
