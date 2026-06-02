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
from app.models.content import ContentDraft, PostAnalytics, Persona
from app.models.trend import Trend
from app.models.trend_score import TrendScore
from app.models.integration import XAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token
from app.services.analytics.metrics import PipelineMetricsService
from app.services.analytics.syncer import EngagementSyncer
from app.services.publishing.x.client import XClient

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
# 1. METRICS SERVICE TESTS
# ==========================================
@pytest.mark.asyncio
async def test_pipeline_metrics_service(db_session: AsyncSession):
    # Add dummy Trend
    trend = Trend(
        canonical_url="https://github.com/google/jax",
        title="JAX upgrades",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    await db_session.flush()

    score = TrendScore(
        trend_id=trend.id,
        raw_score=80.0,
        final_score=85.0
    )
    db_session.add(score)
    
    # Add drafts with different statuses
    d1 = ContentDraft(
        trend_id=trend.id,
        platform="x",
        content_text="Post about JAX",
        status="PUBLISHED"
    )
    d2 = ContentDraft(
        trend_id=trend.id,
        platform="linkedin",
        content_text="Post about JAX on LinkedIn",
        status="APPROVED"
    )
    d3 = ContentDraft(
        trend_id=trend.id,
        platform="threads",
        content_text="Post about JAX on Threads",
        status="DRAFT"
    )
    d4 = ContentDraft(
        trend_id=trend.id,
        platform="substack",
        content_text="Post about JAX on Substack",
        status="REJECTED"
    )
    db_session.add_all([d1, d2, d3, d4])
    await db_session.commit()

    service = PipelineMetricsService()
    metrics = await service.get_dashboard_metrics(db_session)

    assert metrics["total_drafts_generated"] == 4
    # approval rate: (PUBLISHED + APPROVED) / Total = 2/4 = 0.50
    assert metrics["approval_rate"] == 0.50
    assert metrics["platform_distribution"]["x"] == 1
    assert metrics["platform_distribution"]["linkedin"] == 0 # because d2 is APPROVED, not PUBLISHED
    assert len(metrics["top_performing_trends"]) == 1
    assert metrics["top_performing_trends"][0]["trend_id"] == trend.id
    assert metrics["top_performing_trends"][0]["score"] == 85.0
    assert metrics["top_performing_trends"][0]["post_count"] == 4


@pytest.mark.asyncio
async def test_pipeline_metrics_fallback(db_session: AsyncSession):
    # Setup similar records
    trend = Trend(
        canonical_url="https://github.com/google/jax2",
        title="JAX upgrades 2",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    await db_session.flush()

    score = TrendScore(
        trend_id=trend.id,
        raw_score=90.0,
        final_score=92.0
    )
    db_session.add(score)
    
    d1 = ContentDraft(
        trend_id=trend.id,
        platform="x",
        content_text="Post 1",
        status="PUBLISHED"
    )
    d2 = ContentDraft(
        trend_id=trend.id,
        platform="linkedin",
        content_text="Post 2",
        status="APPROVED"
    )
    db_session.add_all([d1, d2])
    await db_session.commit()

    service = PipelineMetricsService()
    
    # Simulating DB dialect error by intercepting execute
    original_execute = db_session.execute
    async def mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "join" in stmt_str or "group_by" in stmt_str or "count" in stmt_str:
            raise ValueError("Simulated DB Dialect Error")
        return await original_execute(stmt, *args, **kwargs)
    db_session.execute = mock_execute
    
    metrics = await service.get_dashboard_metrics(db_session)
    
    # Verify fallback computes correct values in Python memory
    assert metrics["total_drafts_generated"] == 2
    assert metrics["approval_rate"] == 1.0 # APPROVED + PUBLISHED out of 2
    assert metrics["platform_distribution"]["x"] == 1
    assert metrics["platform_distribution"]["linkedin"] == 0
    assert len(metrics["top_performing_trends"]) == 1
    assert metrics["top_performing_trends"][0]["score"] == 92.0
    assert metrics["top_performing_trends"][0]["post_count"] == 2


# ==========================================
# 2. X CLIENT METRICS FETCH TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_x_client_fetch_tweet_metrics(mock_get: MagicMock, db_session: AsyncSession):
    account = XAccount(
        twitter_id="mock_twitter_id",
        username="mock_username",
        access_token=encrypt_token("mock_x_access_token"),
        refresh_token=encrypt_token("mock_x_refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "id": "123456",
                "public_metrics": {
                    "like_count": 100,
                    "retweet_count": 20,
                    "reply_count": 5,
                    "impression_count": 1500
                }
            }
        ]
    }
    mock_get.return_value = mock_resp
    
    client = XClient()
    metrics = await client.fetch_tweet_metrics(db_session, account, ["123456"])
    
    assert "data" in metrics
    assert metrics["data"][0]["id"] == "123456"
    assert metrics["data"][0]["public_metrics"]["like_count"] == 100


# ==========================================
# 3. ENGAGEMENT SYNCER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_engagement_syncer(db_session: AsyncSession):
    # Add X Account
    account = XAccount(
        twitter_id="mock_twitter_id",
        username="mock_username",
        access_token=encrypt_token("mock_x_access_token"),
        refresh_token=encrypt_token("mock_x_refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db_session.add(account)
    
    # 1. Draft to sync: published 2 days ago, platform X
    d1 = ContentDraft(
        platform="x",
        content_text="X post",
        status="PUBLISHED",
        llm_metadata={"x_tweet_ids": ["tweet_1", "tweet_2"]},
        updated_at=datetime.now(timezone.utc) - timedelta(days=2)
    )
    # 2. Draft to skip: platform LinkedIn (gets stubbed/timestamp updated)
    d2 = ContentDraft(
        platform="linkedin",
        content_text="LinkedIn post",
        status="PUBLISHED",
        llm_metadata={"linkedin_post_id": "urn:li:share:123"},
        updated_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    # 3. Draft to skip: published 10 days ago (older than 7 days)
    d3 = ContentDraft(
        platform="x",
        content_text="Old X post",
        status="PUBLISHED",
        llm_metadata={"x_tweet_ids": ["tweet_old"]},
        updated_at=datetime.now(timezone.utc) - timedelta(days=10)
    )
    # 4. Draft to skip: synced 2 hours ago (within 6 hour threshold)
    d4 = ContentDraft(
        platform="x",
        content_text="Recently synced X post",
        status="PUBLISHED",
        llm_metadata={"x_tweet_ids": ["tweet_recent"]},
        updated_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    
    db_session.add_all([d1, d2, d3, d4])
    await db_session.flush()
    
    # Pre-populate PostAnalytics for d4 to show it was recently synced
    pa_d4 = PostAnalytics(
        draft_id=d4.id,
        likes=10,
        shares=2,
        comments=1,
        views=100,
        last_synced_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    db_session.add(pa_d4)
    await db_session.commit()
    
    # Mock XClient's fetch_tweet_metrics
    mock_metrics = {
        "data": [
            {
                "id": "tweet_1",
                "public_metrics": {"like_count": 50, "retweet_count": 10, "reply_count": 2, "impression_count": 500, "quote_count": 1}
            },
            {
                "id": "tweet_2",
                "public_metrics": {"like_count": 30, "retweet_count": 5, "reply_count": 1, "impression_count": 300, "quote_count": 0}
            }
        ]
    }
    
    syncer = EngagementSyncer()
    
    with patch.object(XClient, "fetch_tweet_metrics", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_metrics
        
        # Execute sync
        synced_count = await syncer.sync_engagement(db_session)
        
        # We expect 2 drafts to be synchronized (d1 and d2)
        assert synced_count == 2
        
        # Verify XClient was called with only tweet_1 and tweet_2
        mock_fetch.assert_called_once()
        called_args = mock_fetch.call_args[0]
        # called_args[2] is tweet_ids
        assert set(called_args[2]) == {"tweet_1", "tweet_2"}
        
        # Verify d1 analytics updated (sum of tweet_1 and tweet_2)
        stmt_pa_d1 = select(PostAnalytics).where(PostAnalytics.draft_id == d1.id)
        res_pa_d1 = await db_session.execute(stmt_pa_d1)
        pa_d1 = res_pa_d1.scalars().first()
        assert pa_d1 is not None
        assert pa_d1.likes == 80  # 50 + 30
        assert pa_d1.shares == 16 # 10 + 1 (quote) + 5 + 0
        assert pa_d1.comments == 3 # 2 + 1
        assert pa_d1.views == 800 # 500 + 300
        
        # Verify d2 (LinkedIn) was stubbed with 0s
        stmt_pa_d2 = select(PostAnalytics).where(PostAnalytics.draft_id == d2.id)
        res_pa_d2 = await db_session.execute(stmt_pa_d2)
        pa_d2 = res_pa_d2.scalars().first()
        assert pa_d2 is not None
        assert pa_d2.likes == 0
        assert pa_d2.views == 0


@pytest.mark.asyncio
async def test_engagement_syncer_error_handling(db_session: AsyncSession):
    # Verify OAuth errors on XClient sync don't crash loop, but update timestamps to avoid infinite syncs
    account = XAccount(
        twitter_id="mock_twitter_id",
        username="mock_username",
        access_token=encrypt_token("mock_x_access_token"),
        refresh_token=encrypt_token("mock_x_refresh_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db_session.add(account)
    
    d1 = ContentDraft(
        platform="x",
        content_text="X post",
        status="PUBLISHED",
        llm_metadata={"x_tweet_ids": ["tweet_err"]},
        updated_at=datetime.now(timezone.utc) - timedelta(days=2)
    )
    db_session.add(d1)
    await db_session.commit()
    
    syncer = EngagementSyncer()
    
    # Mock XClient to throw an exception
    with patch.object(XClient, "fetch_tweet_metrics", side_effect=Exception("API Rate Limit or Connection Failure")):
        synced_count = await syncer.sync_engagement(db_session)
        assert synced_count == 1
        
        # Verify that d1 analytics got created/updated (stubbed or preserved timestamp)
        stmt_pa_d1 = select(PostAnalytics).where(PostAnalytics.draft_id == d1.id)
        res_pa_d1 = await db_session.execute(stmt_pa_d1)
        pa_d1 = res_pa_d1.scalars().first()
        assert pa_d1 is not None
        assert pa_d1.likes == 0
        assert pa_d1.last_synced_at is not None


# ==========================================
# 4. API LAYER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_analytics_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Pre-populate dummy data
    trend = Trend(
        canonical_url="https://github.com/google/jax-api",
        title="JAX API",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    await db_session.flush()
    
    d1 = ContentDraft(
        id="draft_id_1",
        trend_id=trend.id,
        platform="x",
        content_text="API X post",
        status="PUBLISHED"
    )
    d2 = ContentDraft(
        id="draft_id_2",
        trend_id=trend.id,
        platform="linkedin",
        content_text="API LinkedIn post",
        status="PUBLISHED"
    )
    db_session.add_all([d1, d2])
    await db_session.flush()
    
    pa1 = PostAnalytics(
        draft_id=d1.id,
        likes=120,
        shares=10,
        comments=4,
        views=2500
    )
    pa2 = PostAnalytics(
        draft_id=d2.id,
        likes=45,
        shares=5,
        comments=2,
        views=800
    )
    db_session.add_all([pa1, pa2])
    await db_session.commit()
    
    # 1. GET /api/v1/analytics/dashboard
    resp = await api_client.get("/api/v1/analytics/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_drafts_generated"] == 2
    assert data["approval_rate"] == 1.0
    assert data["platform_distribution"]["x"] == 1
    assert data["platform_distribution"]["linkedin"] == 1
    
    # 2. GET /api/v1/analytics/posts (without sorting)
    resp_posts = await api_client.get("/api/v1/analytics/posts")
    assert resp_posts.status_code == 200
    posts_data = resp_posts.json()
    assert len(posts_data) == 2
    
    # 3. GET /api/v1/analytics/posts (sort_by=likes, order=desc)
    resp_posts_sorted = await api_client.get("/api/v1/analytics/posts?sort_by=likes&order=desc")
    assert resp_posts_sorted.status_code == 200
    posts_sorted = resp_posts_sorted.json()
    assert posts_sorted[0]["id"] == "draft_id_1"
    assert posts_sorted[0]["analytics"]["likes"] == 120
    assert posts_sorted[1]["id"] == "draft_id_2"
    assert posts_sorted[1]["analytics"]["likes"] == 45

    # 4. POST /api/v1/analytics/sync
    resp_sync = await api_client.post("/api/v1/analytics/sync")
    assert resp_sync.status_code == 202
    assert resp_sync.json()["status"] == "sync_scheduled"
