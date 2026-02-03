import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
import pytest_asyncio

@pytest_asyncio.fixture(scope="function")
async def client():
    """Async client for testing FastAPI endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as ac:
        yield ac

@pytest.fixture(scope="function")
def test_db():
    """
    Creates a fresh in-memory SQLite database for each test.
    Returns a Session object.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.database import Base
    
    # Create in-memory engine
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Create session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
