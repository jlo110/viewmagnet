"""Database connection management (sync + async).

- ``get_session()`` — sync ``Session`` for scripts, Streamlit, and most legacy code
- ``get_async_session()`` — SQLAlchemy 2 ``AsyncSession`` for ``async def`` API handlers
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.database.models import Base


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None
_async_engine: Optional[AsyncEngine] = None
_AsyncSessionLocal: Optional[async_sessionmaker] = None


def _async_url(db_url: str) -> str:
    """Convert a sync DB URL to its asyncio dialect equivalent."""
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if db_url.startswith("sqlite://"):
        return db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgresql+psycopg2://"):
        return db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return db_url


def get_engine() -> Engine:
    """Sync engine (lazy, singleton)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = settings.database_url
        if db_url.startswith("sqlite"):
            _engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
            )
        else:
            _engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )
    return _engine


def get_session_factory() -> sessionmaker:
    """Sync session factory (lazy, singleton)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Synchronous DB session context manager (auto-commit on exit, rollback on error)."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_async_engine() -> AsyncEngine:
    """Async engine (lazy, singleton). Required for ``async with get_async_session()``."""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        url = _async_url(settings.database_url)
        if url.startswith("sqlite"):
            _async_engine = create_async_engine(
                url,
                connect_args={"check_same_thread": False},
            )
        else:
            _async_engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )
    return _async_engine


def get_async_session_factory() -> async_sessionmaker:
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _AsyncSessionLocal


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Async DB session for use inside ``async def`` handlers."""
    SessionLocal = get_async_session_factory()
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def init_db() -> None:
    """Create all tables (used in development startup)."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully.")
