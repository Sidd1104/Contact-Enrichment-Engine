"""
src/database/transaction_manager.py
===================================
Orchestrates transactions context management, ensuring atomicity and thread-safety.
"""

from __future__ import annotations

import logging
from typing import Optional, Any
from sqlalchemy.orm import Session
from .connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class TransactionManager:
    """
    Handles connection transactions, performing rollback on exceptions and commit on success.
    
    Usage:
        with TransactionManager(conn_mgr) as session:
            session.add(model_instance)
    """

    def __init__(self, connection_manager: ConnectionManager, session: Optional[Session] = None) -> None:
        self.conn_mgr = connection_manager
        self.session = session
        self._owns_session = session is None

    def __enter__(self) -> Session:
        if self._owns_session:
            self.session = self.conn_mgr.get_session()
        assert self.session is not None
        return self.session

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if self.session and self._owns_session:
            try:
                if exc_type is not None:
                    logger.warning(f"[TransactionManager] Exception raised: {exc_val}. Rolling back transaction.")
                    self.session.rollback()
                else:
                    self.session.commit()
            except Exception as e:
                logger.error(f"[TransactionManager] Error finalizing transaction: {e}. Performing safety rollback.")
                self.session.rollback()
                raise e
            finally:
                self.session.close()
        return False  # Propagate exception
