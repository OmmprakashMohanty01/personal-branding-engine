import pytest
import pytest_asyncio
import sys
import httpx
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Ensure backend directory is in path
sys.path.insert(0, "/Users/ommprakashmohanty/.gemini/antigravity-ide/scratch/personal-branding-engine/backend")

from app.database import Base, get_db
from app.main import app
from app.models.content import ContentDraft
from app.models.integration import XAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token
from app.services.publishing.x.client import XClient, XPublishingError
from app.services.publishing.orchestrator import PublishingOrchestrator

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


def make_response(status_code: int, json_data: dict = None, text: str = None) -> httpx.Response:
    """Helper to create a real httpx.Response with a dummy request attached."""
    req = httpx.Request("POST", "https://api.twitter.com")
    return httpx.Response(status_code=status_code, json=json_data, text=text, request=req)


# ==========================================
# 1. CLIENT TOKEN LIFECYCLE TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_x_client_token_refresh(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("old_access_token"),
        refresh_token=encrypt_token("valid_refresh_token"),
        expires_at=now - timedelta(hours=1), # Expired 1 hour ago
    )
    db_session.add(account)
    await db_session.commit()
    
    mock_post.return_value = make_response(
        status_code=200,
        json_data={
            "access_token": "new_access_token_abc",
            "refresh_token": "new_refresh_token_def",
            "expires_in": 7200,
        }
    )
    
    client = XClient()
    active_token = await client.check_and_refresh_token(db_session, account)
    
    assert active_token == "new_access_token_abc"
    
    # Verify values saved to DB
    res = await db_session.execute(select(XAccount).where(XAccount.id == account.id))
    db_account = res.scalars().first()
    assert db_account is not None
    assert decrypt_token(db_account.access_token) == "new_access_token_abc"
    assert decrypt_token(db_account.refresh_token) == "new_refresh_token_def"
    assert db_account.expires_at > now


# ==========================================
# 2. CLIENT TWEET & THREAD PUBLISHING TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_x_client_publish_single_success(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("valid_access_token"),
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(account)
    await db_session.commit()
    
    mock_post.return_value = make_response(
        status_code=201,
        json_data={
            "data": {
                "id": "tweet_111",
                "text": "Hello world!"
            }
        }
    )
    
    client = XClient()
    posted_ids = await client.publish_post(db_session, account, "Hello world!")
    
    assert posted_ids == ["tweet_111"]
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "Hello world!"}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_x_client_publish_thread_success(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("valid_access_token"),
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(account)
    await db_session.commit()
    
    responses = [
        make_response(status_code=201, json_data={"data": {"id": "t1"}}),
        make_response(status_code=201, json_data={"data": {"id": "t2"}}),
        make_response(status_code=201, json_data={"data": {"id": "t3"}}),
    ]
    mock_post.side_effect = responses
    
    client = XClient()
    thread_text = "Part 1---thread-split---Part 2---thread-split---Part 3"
    posted_ids = await client.publish_post(db_session, account, thread_text)
    
    assert posted_ids == ["t1", "t2", "t3"]
    assert mock_post.call_count == 3
    
    call_args_list = mock_post.call_args_list
    assert call_args_list[0][1]["json"] == {"text": "Part 1"}
    assert call_args_list[1][1]["json"] == {"text": "Part 2", "reply": {"in_reply_to_tweet_id": "t1"}}
    assert call_args_list[2][1]["json"] == {"text": "Part 3", "reply": {"in_reply_to_tweet_id": "t2"}}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_x_client_publish_thread_partial_failure(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("valid_access_token"),
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(account)
    await db_session.commit()
    
    responses = [
        make_response(status_code=201, json_data={"data": {"id": "t1"}}),
        make_response(status_code=429, text="Rate limit exceeded"),
    ]
    mock_post.side_effect = responses
    
    client = XClient()
    thread_text = "Part 1---thread-split---Part 2---thread-split---Part 3"
    
    with pytest.raises(XPublishingError) as exc_info:
        await client.publish_post(db_session, account, thread_text)
        
    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.published_tweet_ids == ["t1"]
    assert mock_post.call_count == 2


# ==========================================
# 3. ORCHESTRATOR PUBLISHING RUNS TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.publishing.x.client.XClient.publish_post")
async def test_orchestrator_x_success(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.return_value = ["t1", "t2"]
    
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-x-10",
        platform="x",
        content_text="Tweet text",
        final_content="Part 1---thread-split---Part 2",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-x-10")
    
    assert updated_draft.status == "PUBLISHED"
    assert updated_draft.llm_metadata["x_tweet_ids"] == ["t1", "t2"]
    assert updated_draft.llm_metadata["published_url"] == "https://x.com/i/web/status/t1"


@pytest.mark.asyncio
@patch("app.services.publishing.x.client.XClient.publish_post")
async def test_orchestrator_x_partial_failure(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.side_effect = XPublishingError("Rate Limit reached", ["t1"])
    
    account = XAccount(
        twitter_id="12345",
        username="test_user",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-x-11",
        platform="x",
        content_text="Tweet text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-x-11")
    
    assert updated_draft.status == "FAILED_PUBLISHING"
    assert updated_draft.llm_metadata["x_tweet_ids"] == ["t1"]
    assert updated_draft.llm_metadata["published_url"] == "https://x.com/i/web/status/t1"
    assert "Publishing failed mid-way: Rate Limit reached" in updated_draft.feedback_notes


# ==========================================
# 4. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_x_publishing_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # 4.1 Test POST /publishing/x/connect
    with patch("app.services.publishing.x.client.XClient.exchange_code_for_tokens") as mock_exchange, \
         patch("app.services.publishing.x.client.XClient.fetch_user_profile") as mock_profile:
         
        mock_exchange.return_value = {
            "access_token": "mock_x_access_token_123",
            "refresh_token": "mock_x_refresh_token_456",
            "expires_in": 7200
        }
        mock_profile.return_value = {
            "id": "12345678",
            "username": "brand_builder"
        }
        
        resp = await api_client.post("/api/v1/publishing/x/connect?code=auth_x_code_789&code_verifier=xyz123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected"
        assert data["twitter_id"] == "12345678"
        assert data["username"] == "brand_builder"
        
        # Verify account in DB
        res_acc = await db_session.execute(select(XAccount).where(XAccount.twitter_id == "12345678"))
        acc = res_acc.scalars().first()
        assert acc is not None
        assert decrypt_token(acc.access_token) == "mock_x_access_token_123"
        assert decrypt_token(acc.refresh_token) == "mock_x_refresh_token_456"
        
    # 4.2 Seed draft with status APPROVED
    draft = ContentDraft(
        id="d-x-api-test",
        platform="x",
        content_text="X platform test tweet",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    # 4.3 Test POST /publishing/drafts/{draft_id}/publish-now
    with patch("app.services.publishing.x.client.XClient.publish_post") as mock_publish:
        mock_publish.return_value = ["tweet_id_api_123"]
        
        resp_pub = await api_client.post("/api/v1/publishing/drafts/d-x-api-test/publish-now")
        assert resp_pub.status_code == 200
        data_pub = resp_pub.json()
        assert data_pub["status"] == "PUBLISHED"
        assert data_pub["llm_metadata"]["x_tweet_ids"] == ["tweet_id_api_123"]
        assert data_pub["llm_metadata"]["published_url"] == "https://x.com/i/web/status/tweet_id_api_123"
