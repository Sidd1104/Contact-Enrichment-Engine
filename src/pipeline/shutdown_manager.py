"""
src/pipeline/shutdown_manager.py
================================
Manages graceful shutdowns on system interruption signals (SIGINT, SIGTERM).
Ensures database checkpoints are written and browser driver processes are disposed safely.
"""

from __future__ import annotations

import sys
import signal
import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ShutdownManager:
    """
    Handles intercepting OS signals and triggering orchestrator cleanup hooks.
    """

    def __init__(self) -> None:
        self._shutdown_callback: Optional[Callable[[], Any]] = None
        self._is_shutting_down = False

    def register_signal_handlers(self, shutdown_callback: Callable[[], Any]) -> None:
        """
        Binds signal handlers to intercept Ctrl+C and exit commands.
        
        Args:
            shutdown_callback: A function (can be sync or async) to clean resources.
        """
        self._shutdown_callback = shutdown_callback
        
        # Connect signals (skip on Windows if thread issues arise, but standard signals work)
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
            logger.info("[ShutdownManager] Signal handlers registered successfully.")
        except ValueError as e:
            # Signal only works in main thread
            logger.debug(f"[ShutdownManager] Could not register signal handlers (not in main thread): {e}")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Signal listener intercepting SIGINT/SIGTERM."""
        if self._is_shutting_down:
            logger.warning("[ShutdownManager] Force termination requested. Exiting immediately.")
            sys.exit(1)

        self._is_shutting_down = True
        sig_name = signal.Signals(signum).name
        logger.warning(f"\n[ShutdownManager] Interruption intercepted: {sig_name}. Triggering graceful shutdown...")

        if self._shutdown_callback:
            # Execute callback. If async, schedule it in the active event loop
            try:
                if asyncio.iscoroutinefunction(self._shutdown_callback):
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create task on loop
                        asyncio.run_coroutine_threadsafe(self._shutdown_callback(), loop)
                    else:
                        loop.run_until_complete(self._shutdown_callback())
                else:
                    self._shutdown_callback()
            except Exception as e:
                logger.critical(f"[ShutdownManager] Critical error during shutdown cleanup: {e}", exc_info=True)
                sys.exit(1)

        logger.info("[ShutdownManager] Shutdown actions completed. Exiting process.")
        sys.exit(0)
