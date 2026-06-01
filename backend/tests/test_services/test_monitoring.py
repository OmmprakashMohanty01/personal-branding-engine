import pytest
import pytest_asyncio
import sys
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Ensure backend directory is in path
sys.path.insert(0, "/Users/ommprakashmohanty/.gemini/antigravity-ide/scratch/personal-branding-engine/backend")

from app.database import Base, get_db
from app.main import app
from app.services.monitoring.alerts import AlertManager

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
AsyncSessionTesting = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    """Provides a transactional database session for tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with AsyncSessionTesting() as session:
        yield session
        await session.close()
        
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> httpx.AsyncClient:
    """Provides an AsyncClient with database injection override."""
    async def override_get_db():
        yield db_session
        
    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ==========================================
# 1. ALERT MANAGER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_alert_manager_no_webhook():
    # IfALERT_WEBHOOK_URL is not set, no alert should be sent, returns True gracefully
    with patch("app.services.monitoring.alerts.settings.ALERT_WEBHOOK_URL", None):
        manager = AlertManager()
        assert manager.webhook_url is None
        res = await manager.send_alert("Bypassed alert", "INFO")
        assert res is True

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_alert_manager_discord_payload(mock_post: MagicMock):
    # Set mock webhook URL and provider
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp
    
    with patch("app.services.monitoring.alerts.settings.ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/123"), \
         patch("app.services.monitoring.alerts.settings.ALERT_PROVIDER", "discord"):
        manager = AlertManager()
        assert manager.provider == "discord"
        
        res = await manager.send_alert("Connection failure", "CRITICAL")
        assert res is True
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"] == {"content": "🚨 [CRITICAL] Connection failure"}

@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_alert_manager_slack_payload(mock_post: MagicMock):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp
    
    with patch("app.services.monitoring.alerts.settings.ALERT_WEBHOOK_URL", "https://hooks.slack.com/services/abc"), \
         patch("app.services.monitoring.alerts.settings.ALERT_PROVIDER", "slack"):
        manager = AlertManager()
        assert manager.provider == "slack"
        
        res = await manager.send_alert("Low rate limit", "WARNING")
        assert res is True
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"] == {"text": "⚠️ [WARNING] Low rate limit"}


# ==========================================
# 2. HEALTH CHECK API ENDPOINTS TESTS
# ==========================================
@pytest.mark.asyncio
async def test_shallow_health_endpoint(api_client: httpx.AsyncClient):
    resp = await api_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data

@pytest.mark.asyncio
async def test_deep_health_endpoint_success(api_client: httpx.AsyncClient):
    resp = await api_client.get("/api/v1/health/deep")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "timestamp" in data

@pytest.mark.asyncio
async def test_deep_health_endpoint_failure(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Mock database execute to throw exception
    with patch.object(db_session, "execute", side_effect=Exception("Database connection timed out.")):
        resp = await api_client.get("/api/v1/health/deep")
        assert resp.status_code == 503
        data = resp.json()
        assert "Database connection failed" in data["detail"]
