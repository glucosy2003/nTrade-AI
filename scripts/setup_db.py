#!/usr/bin/env python3
"""
Database setup and initialization script.

Usage:
    python scripts/setup_db.py --init         # Create tables
    python scripts/setup_db.py --drop         # Drop all tables (dev only)
    python scripts/setup_db.py --test         # Test database connection
    python scripts/setup_db.py --stats        # Show database statistics
"""

import os
import sys
import logging
from pathlib import Path
from argparse import ArgumentParser

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logger import setup_logger
from backend.core.settings import settings
from database.connection import db
from database.database_manager import db_manager


logger = setup_logger(__name__)


def get_alembic_config() -> Config:
    """Return a configured Alembic config object."""
    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "alembic.ini"
    if not alembic_ini.exists():
        raise FileNotFoundError(f"Alembic config not found: {alembic_ini}")

    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def ensure_database_exists() -> None:
    """Create the target PostgreSQL database if it does not exist yet."""
    database_name = settings.database_name
    admin_user = settings.database_admin_user or settings.database_user
    admin_password = settings.database_admin_password or settings.database_password

    connection_kwargs = {
        "dbname": "postgres",
        "host": settings.database_host,
        "port": settings.database_port,
    }
    if admin_user:
        connection_kwargs["user"] = admin_user
    if admin_password:
        connection_kwargs["password"] = admin_password

    logger.info(
        "Checking PostgreSQL database '%s' on %s:%s using account '%s'...",
        database_name,
        settings.database_host,
        settings.database_port,
        admin_user or "(default auth)",
    )
    with psycopg.connect(**connection_kwargs) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            exists = cur.fetchone()
            if exists:
                logger.info(f"Database '{database_name}' already exists")
                return

            logger.info(f"Creating database '{database_name}'...")
            cur.execute(sql.SQL("CREATE DATABASE {}" ).format(sql.Identifier(database_name)))


def run_migrations() -> None:
    """Apply Alembic migrations to the target database."""
    logger.info("Applying Alembic migrations...")
    alembic_config = get_alembic_config()
    command.upgrade(alembic_config, "head")
    logger.info("✓ Database migrations applied successfully")


def main():
    """Main entry point for database setup."""
    parser = ArgumentParser(description="Database setup and management utility")
    parser.add_argument("--init", action="store_true", help="Initialize database tables")
    parser.add_argument("--drop", action="store_true", help="Drop all tables (development only)")
    parser.add_argument("--test", action="store_true", help="Test database connection")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--migrate", action="store_true", help="Apply Alembic migrations")
    
    args = parser.parse_args()
    
    # Show help if no arguments
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    try:
        # Initialize database connection
        logger.info("Database host: %s", settings.database_host)
        logger.info("Database port: %s", settings.database_port)
        logger.info("Database name: %s", settings.database_name)
        logger.info("Database user: %s", settings.database_user or "(unset)")
        logger.info("Admin user: %s", settings.database_admin_user or "(unset)")
        logger.info(f"Database URL: {settings.database_url}")
        ensure_database_exists()
        db.initialize()
        
        if args.init:
            logger.info("Creating database tables...")
            db.create_all_tables()
            logger.info("✓ Database tables created successfully")
            
        elif args.drop:
            if not settings.is_development():
                logger.error("✗ Can only drop tables in development environment")
                return
            logger.warning("Dropping all database tables...")
            db.drop_all_tables()
            logger.warning("✓ All tables dropped")

        elif args.migrate:
            logger.info("Running database migrations...")
            run_migrations()
            
        elif args.test:
            logger.info("Testing database connection...")
            stats = db_manager.get_database_stats()
            logger.info("✓ Database connection successful")
            logger.info(f"Current database statistics:")
            for key, value in stats.items():
                logger.info(f"  {key}: {value}")
            
        elif args.stats:
            logger.info("Retrieving database statistics...")
            stats = db_manager.get_database_stats()
            logger.info("Database Statistics:")
            for key, value in stats.items():
                logger.info(f"  {key}: {value}")
        
        # Cleanup
        db.close()
        
    except Exception as e:
        logger.error(f"✗ Database operation failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
