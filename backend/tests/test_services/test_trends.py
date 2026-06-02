import pytest
import pytest_asyncio
import sys
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Ensure backend directory is in path
sys.path.insert(0, "/Users/ommprakashmohanty/personal-branding-engine/backend")

from app.database import Base, get_db
from app.main import app
from app.schemas.trends import TrendPayload
from app.models.trend_source import TrendSource
from app.models.trend import Trend
from app.models.trend_score import TrendScore
from app.services.trends.scorer import TrendScorer
from app.services.trends.deduplicator import TrendDeduplicator
from app.services.trends.aggregator import TrendAggregator
from app.services.trends.connectors.github import GitHubTrendSource
from app.services.trends.connectors.hacker_news import HackerNewsSource
from app.services.trends.connectors.google_trends import GoogleTrendsSource

# Setup in-memory database for testing
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
# 1. SCORER TESTS
# ==========================================
def test_scorer_positive_modifier():
    scorer = TrendScorer()
    # Base metrics = 10, positive keyword "AI" (+15)
    raw, final = scorer.calculate_score("New advances in AI tools", base_metrics=10)
    assert raw == 25.0
    assert final == 25.0

def test_scorer_negative_modifier_penalization():
    scorer = TrendScorer()
    # Positive keyword "AI" (+15) + Negative keyword "politics" (strict 0.0 final_score)
    raw, final = scorer.calculate_score("AI usage in global politics", base_metrics=10)
    assert raw == 25.0
    assert final == 0.0

def test_scorer_max_cap():
    scorer = TrendScorer()
    # Exceed 100 points -> check clamp limit
    raw, final = scorer.calculate_score("Open Source AI automation startup for career growth in business technology python", base_metrics=30)
    assert raw == 100.0
    assert final == 100.0


# ==========================================
# 2. DEDUPLICATOR TESTS
# ==========================================
def test_deduplicator_exact_match_merging():
    dedup = TrendDeduplicator()
    time_now = datetime.now(timezone.utc)
    
    p1 = TrendPayload(
        canonical_url="https://url1.com",
        title="Agentic AI workflows in production!",
        topic="AI",
        published_at=time_now,
        metadata_json={"upvotes": 50, "source_name": "github"}
    )
    p2 = TrendPayload(
        canonical_url="https://url2.com",
        title="Agentic AI Workflows in Production",
        topic="AI",
        published_at=time_now,
        metadata_json={"upvotes": 100, "source_name": "reddit"}
    )
    
    unique_payloads = dedup.deduplicate([p1, p2])
    assert len(unique_payloads) == 1
    merged = unique_payloads[0]
    
    # Check that upvotes were combined
    assert merged.metadata_json["upvotes"] == 150
    # Check that all URLs are preserved in the list
    assert "https://url1.com" in merged.metadata_json["source_urls"]
    assert "https://url2.com" in merged.metadata_json["source_urls"]


# ==========================================
# 3. CONNECTOR ERROR HANDLING TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_connector_http_failure_graceful_recovery(mock_get: MagicMock):
    # Simulate a 500 error from GitHub API
    mock_get.return_value = MagicMock(status_code=500)
    mock_get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=mock_get.return_value
    )
    
    conn = GitHubTrendSource(timeout=1.0)
    # Connector should catch exception and return an empty list instead of crashing
    results = await conn.fetch_trends()
    assert results == []


# ==========================================
# 4. AGGREGATOR TESTS
# ==========================================
@pytest.mark.asyncio
async def test_aggregator_end_to_end_saving(db_session: AsyncSession):
    # Mock connectors that return specific payloads
    time_now = datetime.now(timezone.utc)
    p1 = TrendPayload(
        canonical_url="https://github.com/repo1",
        title="Python AI agents framework",
        topic="AI",
        published_at=time_now,
        metadata_json={"upvotes": 200, "source_name": "github", "connector_type": "api", "source_url": "https://github.com"}
    )
    
    mock_conn = MagicMock(spec=GitHubTrendSource)
    mock_conn.name = "github"
    mock_conn.fetch_trends = AsyncMock(return_value=[p1])
    
    aggregator = TrendAggregator(connectors=[mock_conn])
    scored = await aggregator.aggregate_and_score()
    
    assert len(scored) == 1
    payload, raw, final = scored[0]
    assert final > 0.0 # Positives matched: python (+10), ai (+15) -> > 25.0
    
    # Save to mock test DB
    await aggregator.save_to_db(db_session, scored)
    
    # Verify records got inserted
    # Verify TrendSource
    res_source = await db_session.execute(select(TrendSource))
    source = res_source.scalars().first()
    assert source is not None
    assert source.name == "github"
    
    # Verify Trend
    res_trend = await db_session.execute(select(Trend))
    trend = res_trend.scalars().first()
    assert trend is not None
    assert trend.title == "Python AI agents framework"
    
    # Verify TrendScore
    res_score = await db_session.execute(select(TrendScore))
    score = res_score.scalars().first()
    assert score is not None
    assert score.trend_id == trend.id
    assert score.final_score == final


# ==========================================
# 5. API ROUTE TESTS
# ==========================================
@pytest.mark.asyncio
async def test_api_endpoints_workflow(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Pre-populate some DB records
    source = TrendSource(name="github", source_url="https://github.com", connector_type="api")
    db_session.add(source)
    await db_session.commit()
    
    trend = Trend(
        source_id=source.id,
        canonical_url="https://github.com/openai/gpt",
        title="GPT-5 release details",
        topic="AI",
        published_at=datetime.now(timezone.utc),
        metadata_json={"source_name": "github"}
    )
    db_session.add(trend)
    await db_session.commit()
    
    score = TrendScore(
        trend_id=trend.id,
        raw_score=95.0,
        final_score=95.0
    )
    db_session.add(score)
    await db_session.commit()
    
    # Test GET /trends
    resp = await api_client.get("/api/v1/trends")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "GPT-5 release details"
    assert data[0]["final_score"] == 95.0
    
    # Test GET /trends/top
    resp_top = await api_client.get("/api/v1/trends/top?limit=5")
    assert resp_top.status_code == 200
    data_top = resp_top.json()
    assert len(data_top) == 1
    assert data_top[0]["final_score"] == 95.0
    
    # Test GET /trends/{id}
    resp_detail = await api_client.get(f"/api/v1/trends/{trend.id}")
    assert resp_detail.status_code == 200
    assert resp_detail.json()["title"] == "GPT-5 release details"
    
    # Test POST /trends/refresh
    with patch.dict("os.environ", {"API_CRON_SECRET": "test_cron_key_123"}):
        resp_refresh = await api_client.post(
            "/api/v1/trends/refresh",
            headers={"X-Cron-Secret": "test_cron_key_123"}
        )
        assert resp_refresh.status_code == 202
    assert resp_refresh.json()["status"] == "refresh_scheduled"
