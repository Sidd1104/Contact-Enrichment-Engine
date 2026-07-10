"""
src/workers/graceful_shutdown.py
=================================
Graceful Shutdown System.

Intercepts system interrupt signals (SIGINT/SIGTERM) to shut down worker
threads safely, finalize tasks, and serialize queue state to disk.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Callable, Coroutine, List

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """
    Manages process termination signals and cleanups.
    """

    def __init__(self) -> None:
        self._cleanup_callbacks: List[Callable[[], Coroutine[Any, Any, None]]] = []
        self._shutdown_in_progress = False

    def register_cleanup(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register async callback to run during shutdown cleanup."""
        self._cleanup_callbacks.append(callback)

    def register_signals(self) -> None:
        """Hook SIGINT and SIGTERM OS signals."""
        loop = asyncio.get_event_loop()
        
        # Windows compatibility: SIGBREAK or keyboard interrupts might not map to signals cleanly,
        # but we register them where supported by the OS.
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.trigger_shutdown(s)))
            except NotImplementedError:
                # add_signal_handler is not implemented in Windows asyncio SelectorEventLoop,
                # we handle it via explicit exceptions / try-catches in orchestrator loops instead.
                pass

    async def trigger_shutdown(self, sig: Optional[signal.Signals] = None) -> None:
        """
        Main execution sequence running cleanups and exiting.
        """
        if self._shutdown_in_progress:
            return
        self._shutdown_in_progress = True

        sig_name = sig.name if sig else "Explicit/Interrupt"
        logger.warning(f"[ShutdownHandler] Interrupted by {sig_name}! Starting graceful shutdown...")

        # Execute registered cleanups
        for callback in self._cleanup_callbacks:
            try:
                await callback()
            except Exception as e:
                logger.error(f"[ShutdownHandler] Error during cleanup callback: {e}")

        logger.info("[ShutdownHandler] Shutdown complete. Terminating process.")
        
        # Stop loop or exit
        # If in a script run, sys.exit
        sys.exit(0)
