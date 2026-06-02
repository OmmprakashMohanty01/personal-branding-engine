import pytest
import pytest_asyncio
import sys
import httpx
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Ensure backend directory is in path
sys.path.insert(0, "/Users/ommprakashmohanty/personal-branding-engine/backend")

from app.database import Base, get_db
from app.main import app
from app.models.content import ContentDraft, Persona
from app.models.scheduling import ScheduleConfig
from app.services.scheduling.queue import QueueManager
from app.services.scheduling.dispatch import DispatchService
from app.services.publishing.orchestrator import PublishingOrchestrator

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
# 1. QUEUE MANAGER SCHEDULING & COLLISION TESTS
# ==========================================
@pytest.mark.asyncio
async def test_queue_manager_optimal_slots(db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-sch-1",
        name="Schedule Persona",
        tone_description="Assertive",
        vocabulary_rules="Tech only",
        formatting_preferences="Concise"
    )
    db_session.add(persona)
    await db_session.flush()
    
    # Configure ScheduleConfig: slots at 08:00 and 17:00 in America/New_York
    config = ScheduleConfig(
        persona_id=persona.id,
        platform="linkedin",
        posting_times_json=["08:00", "17:00"],
        timezone="America/New_York",
        is_active=True
    )
    db_session.add(config)
    
    # 2 Drafts: both APPROVED and unscheduled
    d1 = ContentDraft(
        persona_id=persona.id,
        platform="linkedin",
        content_text="Post 1 text",
        status="APPROVED"
    )
    d2 = ContentDraft(
        persona_id=persona.id,
        platform="linkedin",
        content_text="Post 2 text",
        status="APPROVED"
    )
    db_session.add_all([d1, d2])
    await db_session.commit()
    
    manager = QueueManager()
    scheduled_count = await manager.assign_schedules(db_session)
    
    assert scheduled_count == 2
    
    # Verify both have different non-colliding future timestamps
    res = await db_session.execute(select(ContentDraft).order_by(ContentDraft.scheduled_for.asc()))
    drafts = res.scalars().all()
    
    assert drafts[0].scheduled_for is not None
    assert drafts[1].scheduled_for is not None
    
    # Assert they are at least 1 hour apart (matching 08:00 vs 17:00 New York offsets)
    diff = abs((drafts[1].scheduled_for - drafts[0].scheduled_for).total_seconds())
    assert diff >= 3600


# ==========================================
# 2. DISPATCH SERVICE TESTS WITH LOCKS
# ==========================================
@pytest.mark.asyncio
@patch.object(PublishingOrchestrator, "publish_draft", new_callable=AsyncMock)
async def test_dispatch_service_mature_only(mock_publish: MagicMock, db_session: AsyncSession):
    # Draft 1: Mature schedule (scheduled for 1 hour ago) -> Should dispatch
    d1 = ContentDraft(
        platform="x",
        content_text="Mature tweet",
        status="APPROVED",
        scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    # Draft 2: Future schedule (scheduled for 2 hours in the future) -> Should be skipped
    d2 = ContentDraft(
        platform="x",
        content_text="Future tweet",
        status="APPROVED",
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add_all([d1, d2])
    await db_session.commit()
    
    dispatcher = DispatchService()
    dispatched_count = await dispatcher.dispatch_mature_posts(db_session)
    
    assert dispatched_count == 1
    mock_publish.assert_called_once_with(db_session, d1.id)
    
    # Assert optimistic lock reset d1's scheduled_for back to None
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == d1.id))
    db_d1 = res.scalars().first()
    assert db_d1.scheduled_for is None


# ==========================================
# 3. API CONTROLLER & CRON SECURITY TESTS
# ==========================================
@pytest.mark.asyncio
async def test_scheduling_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-sch-api",
        name="Schedule Persona API",
        tone_description="Enthusiastic",
        vocabulary_rules="AI",
        formatting_preferences="Emojis"
    )
    db_session.add(persona)
    await db_session.flush()
    
    # 3.1 Test POST /scheduling/configs
    config_body = {
        "persona_id": persona.id,
        "platform": "x",
        "posting_times_json": ["09:00", "18:00"],
        "timezone": "UTC"
    }
    resp_config = await api_client.post("/api/v1/scheduling/configs", json=config_body)
    assert resp_config.status_code == 201
    
    # Add a draft for testing /assign
    d1 = ContentDraft(
        persona_id=persona.id,
        platform="x",
        content_text="API Tweet",
        status="APPROVED"
    )
    db_session.add(d1)
    await db_session.commit()
    
    # 3.2 Test POST /scheduling/assign
    resp_assign = await api_client.post("/api/v1/scheduling/assign")
    assert resp_assign.status_code == 200
    assert resp_assign.json()["status"] == "scheduled"
    assert resp_assign.json()["scheduled_count"] == 1
    
    # 3.3 Test POST /scheduling/dispatch security
    # Without X-Cron-Secret -> 422 (because header is completely missing) or 401 depending on validation
    resp_dispatch_missing = await api_client.post("/api/v1/scheduling/dispatch")
    assert resp_dispatch_missing.status_code == 422 # FastAPI validation fails on missing header
    
    # With incorrect X-Cron-Secret -> 401
    resp_dispatch_wrong = await api_client.post(
        "/api/v1/scheduling/dispatch",
        headers={"X-Cron-Secret": "wrong_cron_key"}
    )
    assert resp_dispatch_wrong.status_code == 401
    
    # With correct X-Cron-Secret -> 202 Accepted
    with patch.dict("os.environ", {"API_CRON_SECRET": "test_env_cron_key_999"}):
        resp_dispatch_correct = await api_client.post(
            "/api/v1/scheduling/dispatch",
            headers={"X-Cron-Secret": "test_env_cron_key_999"}
        )
        assert resp_dispatch_correct.status_code == 202
        assert resp_dispatch_correct.json()["status"] == "dispatch_scheduled"
