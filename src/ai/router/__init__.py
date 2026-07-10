"""
src/ai/router/__init__.py
===========================
Public API for the AI Router module.
"""

from .router import AIRouter, NoProvidersAvailableError

__all__ = [
    "AIRouter",
    "NoProvidersAvailableError",
]
