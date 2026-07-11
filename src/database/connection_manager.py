"""
src/database/connection_manager.py
==================================
Manages database configurations, engine initialization, and session creation.
Supports SQLite (development) and PostgreSQL (production).
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Optional
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session, declarative_base
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Base declarative class for models
Base = declarative_base()


class ConnectionManager:
    """
    Handles database engine creation and Session management.
    """

    def __init__(self, db_engine_type: Optional[str] = None, custom_uri: Optional[str] = None) -> None:
        """
        Initializes connection settings.
        
        Args:
            db_engine_type: 'sqlite' or 'postgres'. If None, reads DB_ENGINE from env,
                            falling back to 'sqlite'.
            custom_uri: If provided, directly overrides connection parameters (useful for tests).
        """
        self.engine_type = db_engine_type or os.getenv("DB_ENGINE", "sqlite").lower()
        self.custom_uri = custom_uri
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker[Session]] = None
        
        self._init_connection()

    def _init_connection(self) -> None:
        """Configures connection strings and creates SQLAlchemy engines."""
        if self.custom_uri:
            uri = self.custom_uri
            logger.info(f"[ConnectionManager] Using custom database URI: {uri}")
        elif self.engine_type == "postgres":
            host = os.getenv("DB_HOST", "localhost")
            port = os.getenv("DB_PORT", "5432")
            name = os.getenv("DB_NAME", "contact_enrichment")
            user = os.getenv("DB_USER", "postgres")
            password = os.getenv("DB_PASSWORD", "")
            
            # Support passwords with special characters (standard URL safety)
            import urllib.parse
            safe_password = urllib.parse.quote_plus(password) if password else ""
            
            if safe_password:
                uri = f"postgresql://{user}:{safe_password}@{host}:{port}/{name}"
            else:
                uri = f"postgresql://{user}@{host}:{port}/{name}"
                
            logger.info(f"[ConnectionManager] Configured PostgreSQL: host={host}, db={name}, user={user}")
        else:
            # SQLite fallback
            sqlite_path = os.getenv("SQLITE_DB_PATH", "data/contact_enrichment.db")
            # Ensure path directory exists
            parent = Path(sqlite_path).parent
            if parent:
                parent.mkdir(parents=True, exist_ok=True)
                
            uri = f"sqlite:///{sqlite_path}"
            logger.info(f"[ConnectionManager] Configured SQLite path: {sqlite_path}")

        # Engine setup. For SQLite, enable check_same_thread=False to allow multi-threaded access (e.g. worker pool)
        connect_args: dict[str, Any] = {}
        if uri.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self._engine = create_engine(
            uri,
            connect_args=connect_args,
            pool_pre_ping=True,  # Automatically tests connection health
            echo=False           # Set to True for verbose SQL logging (optional)
        )
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)

    @property
    def engine(self) -> Engine:
        if not self._engine:
            raise RuntimeError("Database engine has not been initialized.")
        return self._engine

    def get_session(self) -> Session:
        """Returns a new database session."""
        if not self._session_factory:
            raise RuntimeError("Database session factory has not been initialized.")
        return self._session_factory()

    def get_scoped_session(self) -> scoped_session[Session]:
        """Returns a thread-safe scoped session."""
        if not self._session_factory:
            raise RuntimeError("Database session factory has not been initialized.")
        return scoped_session(self._session_factory)

    def close(self) -> None:
        """Closes connection pool resources."""
        if self._engine:
            self._engine.dispose()
            logger.info("[ConnectionManager] Database engine disposed.")
