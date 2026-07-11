"""
src/pipeline/pipeline_events.py
==============================
Implements an event-driven mechanism for pipeline progress tracking.
Allows decoupled subscribers (e.g. loggers, dashboard, stats collectors) to listen to state events.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)


class PipelineEventType(str, Enum):
    """
    Standard events triggered during pipeline execution.
    """
    PIPELINE_STARTED = "pipeline_started"
    BATCH_STARTED = "batch_started"
    BATCH_COMPLETED = "batch_completed"
    SEARCH_COMPLETED = "search_completed"
    SCRAPING_COMPLETED = "scraping_completed"
    VALIDATION_COMPLETED = "validation_completed"
    DATABASE_SAVED = "database_saved"
    EXPORT_FINISHED = "export_finished"
    PIPELINE_FINISHED = "pipeline_finished"
    PIPELINE_FAILED = "pipeline_failed"


class PipelineEventBus:
    """
    Lightweight, synchronous event broker for registration and publication of events.
    """

    def __init__(self) -> None:
        self._listeners: Dict[PipelineEventType, List[Callable[..., Any]]] = {
            event_type: [] for event_type in PipelineEventType
        }

    def subscribe(self, event_type: PipelineEventType, callback: Callable[..., Any]) -> None:
        """Subscribes a callback to the specified event type."""
        if event_type in self._listeners:
            if callback not in self._listeners[event_type]:
                self._listeners[event_type].append(callback)
        else:
            logger.warning(f"[EventBus] Attempted to subscribe to invalid event: {event_type}")

    def unsubscribe(self, event_type: PipelineEventType, callback: Callable[..., Any]) -> None:
        """Unsubscribes a callback from the specified event type."""
        if event_type in self._listeners and callback in self._listeners[event_type]:
            self._listeners[event_type].remove(callback)

    def publish(self, event_type: PipelineEventType, *args: Any, **kwargs: Any) -> None:
        """Publishes an event, executing all registered callback listeners."""
        if event_type not in self._listeners:
            logger.error(f"[EventBus] Cannot publish unregistered event type: {event_type}")
            return

        for callback in self._listeners[event_type]:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"[EventBus] Error executing subscriber for event '{event_type}': {e}", exc_info=True)
