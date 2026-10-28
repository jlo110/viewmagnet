"""
Pytest fixtures for ViewMagnet tests.
"""
import os
import tempfile
import pytest
from typing import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Use a named temp-file SQLite DB so the sync engine (sqlite3) and the
# async engine (aiosqlite) can both open the same file and therefore
# share the same schema + data.  A pure :memory: URL gives each driver
# its own empty database, which causes "no such table" errors in any
# route that uses get_async_session().
_TEST_DB_FILE = tempfile.mktemp(suffix="_smartvid_test.db")
os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"


@pytest.fixture(scope="session")
def test_engine():
    """Create test database engine and schema."""
    from src.database.models import Base

    engine = create_engine(
        f"sqlite:///{_TEST_DB_FILE}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    # Clean up the temp DB file after the entire test session.
    try:
        os.unlink(_TEST_DB_FILE)
    except FileNotFoundError:
        pass


@pytest.fixture(scope="session")
def TestingSessionLocal(test_engine):
    """Create session factory bound to test engine."""
    return sessionmaker(
        autocommit=False, 
        autoflush=False, 
        bind=test_engine
    )


@pytest.fixture(scope="function")
def db_session(test_engine, TestingSessionLocal) -> Generator[Session, None, None]:
    """Create a fresh database session for each test."""
    from src.database.models import Base
    
    # Clear all data before each test
    connection = test_engine.connect()
    transaction = connection.begin()
    
    # Delete all data from all tables
    for table in reversed(Base.metadata.sorted_tables):
        connection.execute(table.delete())
    transaction.commit()
    connection.close()
    
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(test_engine, TestingSessionLocal, db_session) -> Generator[TestClient, None, None]:
    """Create a test client with database session override.

    Patches both the sync *and* async DB engines so routes that call
    ``get_async_session()`` (e.g. /analyses/history) hit the same SQLite
    file as the sync test engine and see the tables created by the
    session-scoped ``test_engine`` fixture.
    """
    import src.database.connection as db_module
    from src.api.main import app

    # ---- sync engine override ----
    original_engine = db_module._engine
    original_session_local = db_module._SessionLocal
    db_module._engine = test_engine
    db_module._SessionLocal = TestingSessionLocal

    # ---- async engine override ----
    # Re-use the same file-based SQLite URL so aiosqlite and sqlite3
    # open the same file.  We reset the cached singletons so
    # get_async_engine() rebuilds them against the test URL on first use.
    original_async_engine = db_module._async_engine
    original_async_session_local = db_module._AsyncSessionLocal
    db_module._async_engine = None
    db_module._AsyncSessionLocal = None

    with TestClient(app) as test_client:
        yield test_client

    # Restore all originals
    db_module._engine = original_engine
    db_module._SessionLocal = original_session_local
    db_module._async_engine = original_async_engine
    db_module._AsyncSessionLocal = original_async_session_local


@pytest.fixture
def test_user(db_session) -> dict:
    """Create a test user in the database."""
    from src.database.models import User
    from src.auth.password import hash_password
    
    user = User(
        email="test@example.com",
        password_hash=hash_password("testpassword123"),
        name="Test User",
        plan="free",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "plan": user.plan,
        "password": "testpassword123",
    }


@pytest.fixture
def auth_headers(test_user) -> dict:
    """Create auth headers with valid JWT token."""
    from src.auth.jwt import create_access_token
    
    token = create_access_token(test_user["id"], test_user["email"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_youtube_api():
    """Mock YouTube API responses."""
    with patch("src.youtube.client.YouTubeClient") as mock:
        mock_instance = MagicMock()
        mock_instance.get_video_info.return_value = {
            "id": "test_video_id",
            "title": "Test Video Title",
            "description": "Test description",
            "channel_id": "test_channel_id",
            "channel_title": "Test Channel",
            "view_count": 10000,
            "like_count": 500,
            "comment_count": 100,
            "published_at": "2024-01-01T00:00:00Z",
            "duration": "PT10M30S",
            "thumbnail_url": "https://i.ytimg.com/vi/test_video_id/maxresdefault.jpg",
        }
        mock_instance.get_channel_info.return_value = {
            "id": "test_channel_id",
            "title": "Test Channel",
            "subscriber_count": 10000,
            "video_count": 100,
            "view_count": 1000000,
        }
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def sample_video_analysis() -> dict:
    """Sample video analysis response."""
    return {
        "video_id": "test_video_id",
        "title": "Test Video Title",
        "prediction_score": 75.5,
        "prediction_tier": "high",
        "title_score": 78.0,
        "thumbnail_score": 72.0,
        "explanations": [
            {
                "feature": "Channel History",
                "value": "23% hit rate",
                "impact": "+15%",
                "direction": "positive",
            }
        ],
        "recommendations": [
            "Consider adding a number to your title",
        ],
        "niche_comparison": {
            "niche": "Technology",
            "your_score": 75.5,
            "niche_average": 50.0,
            "percentile": 85,
        },
    }
