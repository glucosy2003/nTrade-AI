"""
Database connection management for nTrade AI.

Provides SQLAlchemy engine and session management with proper
connection pooling, error handling, and lifecycle management.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from backend.core.settings import settings


logger = logging.getLogger(__name__)


class DatabaseConnection:
    """
    Manages database connection lifecycle and session creation.
    
    Features:
    - Connection pooling for performance
    - Automatic reconnection on failure
    - Proper resource cleanup
    """

    def __init__(self):
        """Initialize database connection manager."""
        self.engine = None
        self.SessionLocal = None
        self._is_connected = False

    def _normalize_database_url(self) -> str:
        """Ensure SQLAlchemy uses the psycopg 3 driver when a plain PostgreSQL URL is provided."""
        database_url = settings.database_url
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if database_url.startswith("postgresql://") and "+psycopg" not in database_url and "+psycopg2" not in database_url:
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return database_url

    def initialize(self) -> None:
        """
        Initialize database engine and session factory.
        
        Raises:
            SQLAlchemyError: If connection fails
        """
        try:
            database_url = self._normalize_database_url()
            logger.info(
                "Connecting to database %s at %s:%s",
                settings.database_name,
                settings.database_host,
                settings.database_port,
            )
            
            # Create engine with connection pooling
            self.engine = create_engine(
                database_url,
                poolclass=pool.QueuePool,
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_pre_ping=True,  # Verify connection is alive before using
                echo=settings.app_debug,  # Log SQL queries in debug mode
            )
            
            # Create session factory
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine,
                expire_on_commit=False,
            )
            
            # Test connection
            self._test_connection()
            self._is_connected = True
            logger.info("✓ Database connection established")
            
        except SQLAlchemyError as e:
            logger.error(f"✗ Failed to connect to database: {str(e)}", exc_info=True)
            raise

    def _test_connection(self) -> None:
        """
        Test database connection by executing a simple query.
        
        Raises:
            SQLAlchemyError: If connection test fails
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.debug("✓ Database connection test successful")
        except Exception as e:
            logger.error(f"✗ Database connection test failed: {str(e)}")
            raise

    def get_session(self) -> Session:
        """
        Get a new database session.
        
        Returns:
            SQLAlchemy session instance
            
        Raises:
            RuntimeError: If database not initialized
        """
        if not self._is_connected or self.SessionLocal is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self.SessionLocal()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Context manager for database sessions.
        
        Automatically handles commit/rollback and cleanup.
        
        Example:
            with db.session_scope() as session:
                user = session.query(User).first()
        
        Yields:
            SQLAlchemy session instance
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Close database connection and cleanup resources."""
        if self.engine:
            self.engine.dispose()
            self._is_connected = False
            logger.info("✓ Database connection closed")

    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._is_connected

    def create_all_tables(self) -> None:
        """
        Create all database tables from ORM models.
        
        CAUTION: This is for initial setup only. For schema migrations,
        use Alembic migration scripts instead.
        """
        try:
            if not self._is_connected:
                raise RuntimeError("Database not initialized")
            
            # Import all models to register them with Base
            from database.models import Base  # noqa: F401
            
            Base.metadata.create_all(bind=self.engine)
            logger.info("✓ Database tables created")
        except Exception as e:
            logger.error(f"✗ Failed to create tables: {str(e)}", exc_info=True)
            raise

    def drop_all_tables(self) -> None:
        """
        Drop all database tables.
        
        CAUTION: This is destructive and should only be used in development!
        """
        if not settings.is_development():
            raise RuntimeError("Cannot drop tables in non-development environment")
        
        try:
            from database.models import Base  # noqa: F401
            
            Base.metadata.drop_all(bind=self.engine)
            logger.warning("⚠ All database tables dropped")
        except Exception as e:
            logger.error(f"✗ Failed to drop tables: {str(e)}", exc_info=True)
            raise


# Global database connection instance
db = DatabaseConnection()
