"""
src/ai/models/__init__.py
==========================
Public API for structured AI response models.
"""

from .response import EnrichedContact, SearchResult, ExtractionResult

__all__ = [
    "EnrichedContact",
    "SearchResult",
    "ExtractionResult",
]
