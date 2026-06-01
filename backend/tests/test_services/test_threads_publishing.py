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
from app.models.integration import ThreadsAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token
from app.services.publishing.threads.client import ThreadsClient, ThreadsPublishingError
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
    req = httpx.Request("POST", "https://graph.threads.net")
    return httpx.Response(status_code=status_code, json=json_data, text=text, request=req)


# ==========================================
# 1. CLIENT TOKEN LIFECYCLE TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_threads_client_token_refresh_needed(mock_get: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    # Expiring in 6 days (within the 7-day rolling refresh window)
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_user",
        access_token=encrypt_token("old_long_lived_token"),
        expires_at=now + timedelta(days=6)
    )
    db_session.add(account)
    await db_session.commit()
    
    mock_get.return_value = make_response(
        status_code=200,
        json_data={
            "access_token": "new_long_lived_token_789",
            "expires_in": 5184000
        }
    )
    
    client = ThreadsClient()
    active_token = await client.check_and_refresh_token(db_session, account)
    
    assert active_token == "new_long_lived_token_789"
    mock_get.assert_called_once()
    
    # Verify values saved to DB
    res = await db_session.execute(select(ThreadsAccount).where(ThreadsAccount.id == account.id))
    db_account = res.scalars().first()
    assert db_account is not None
    assert decrypt_token(db_account.access_token) == "new_long_lived_token_789"
    assert db_account.expires_at > now + timedelta(days=59)


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_threads_client_token_refresh_not_needed(mock_get: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    # Expiring in 10 days (outside the 7-day rolling refresh window)
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_user",
        access_token=encrypt_token("current_long_lived_token"),
        expires_at=now + timedelta(days=10)
    )
    db_session.add(account)
    await db_session.commit()
    
    client = ThreadsClient()
    active_token = await client.check_and_refresh_token(db_session, account)
    
    assert active_token == "current_long_lived_token"
    mock_get.assert_not_called()


# ==========================================
# 2. CLIENT TWO-STEP CONTAINER PUBLISHING TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_threads_client_publish_single_success(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_user",
        access_token=encrypt_token("valid_token"),
        expires_at=now + timedelta(days=20)
    )
    db_session.add(account)
    await db_session.commit()
    
    # Step 1 response (creation_id), then Step 2 response (post_id)
    responses = [
        make_response(status_code=200, json_data={"id": "c111"}),
        make_response(status_code=200, json_data={"id": "post_999"})
    ]
    mock_post.side_effect = responses
    
    client = ThreadsClient()
    posted_ids = await client.publish_post(db_session, account, "Threads post text")
    
    assert posted_ids == ["post_999"]
    assert mock_post.call_count == 2
    
    call_args = mock_post.call_args_list
    # Assert Step 1 call
    assert call_args[0][0][0] == f"https://graph.threads.net/v1.0/{account.threads_user_id}/threads"
    assert call_args[0][1]["json"] == {"media_type": "TEXT", "text": "Threads post text"}
    # Assert Step 2 call
    assert call_args[1][0][0] == f"https://graph.threads.net/v1.0/{account.threads_user_id}/threads_publish"
    assert call_args[1][1]["json"] == {"creation_id": "c111"}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_threads_client_publish_thread_success(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_user",
        access_token=encrypt_token("valid_token"),
        expires_at=now + timedelta(days=20)
    )
    db_session.add(account)
    await db_session.commit()
    
    # Thread size = 2 posts.
    # 4 calls total:
    # 1. Step 1 Part 1 -> returns c1
    # 2. Step 2 Part 1 -> returns post1
    # 3. Step 1 Part 2 (with reply_to_id="post1") -> returns c2
    # 4. Step 2 Part 2 -> returns post2
    responses = [
        make_response(status_code=200, json_data={"id": "c1"}),
        make_response(status_code=200, json_data={"id": "post1"}),
        make_response(status_code=200, json_data={"id": "c2"}),
        make_response(status_code=200, json_data={"id": "post2"}),
    ]
    mock_post.side_effect = responses
    
    client = ThreadsClient()
    thread_text = "Part 1---thread-split---Part 2"
    posted_ids = await client.publish_post(db_session, account, thread_text)
    
    assert posted_ids == ["post1", "post2"]
    assert mock_post.call_count == 4
    
    call_args = mock_post.call_args_list
    # Part 1 calls
    assert call_args[0][1]["json"] == {"media_type": "TEXT", "text": "Part 1"}
    assert call_args[1][1]["json"] == {"creation_id": "c1"}
    # Part 2 calls (assert reply_to_id linkage)
    assert call_args[2][1]["json"] == {"media_type": "TEXT", "text": "Part 2", "reply_to_id": "post1"}
    assert call_args[3][1]["json"] == {"creation_id": "c2"}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_threads_client_publish_step2_failure_orphan(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_user",
        access_token=encrypt_token("valid_token"),
        expires_at=now + timedelta(days=20)
    )
    db_session.add(account)
    await db_session.commit()
    
    # Step 1 Containerization succeeds, Step 2 Publishing fails (e.g. 500 error)
    responses = [
        make_response(status_code=200, json_data={"id": "c_orphan_123"}),
        make_response(status_code=500, text="Internal publishing error")
    ]
    mock_post.side_effect = responses
    
    client = ThreadsClient()
    with pytest.raises(ThreadsPublishingError) as exc_info:
        await client.publish_post(db_session, account, "Orphan test")
        
    assert exc_info.value.creation_id == "c_orphan_123"
    assert "Publishing failed (Step 2)" in str(exc_info.value)
    assert exc_info.value.published_post_ids == []
    assert mock_post.call_count == 2


# ==========================================
# 3. ORCHESTRATOR PUBLISHING RUNS TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.publishing.threads.client.ThreadsClient.publish_post")
async def test_orchestrator_threads_success(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.return_value = ["post1", "post2"]
    
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_star",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-t-10",
        platform="threads",
        content_text="Draft text",
        final_content="Part 1---thread-split---Part 2",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-t-10")
    
    assert updated_draft.status == "PUBLISHED"
    assert updated_draft.llm_metadata["threads_post_ids"] == ["post1", "post2"]
    assert updated_draft.llm_metadata["published_url"] == "https://www.threads.net/@threads_star/post/post1"


@pytest.mark.asyncio
@patch("app.services.publishing.threads.client.ThreadsClient.publish_post")
async def test_orchestrator_threads_orphan_failure(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.side_effect = ThreadsPublishingError("Step 2 Failed", ["post1"], creation_id="c_orphan_abc")
    
    account = ThreadsAccount(
        threads_user_id="threads_user_123",
        username="threads_star",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-t-11",
        platform="threads",
        content_text="Draft text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-t-11")
    
    assert updated_draft.status == "FAILED_PUBLISHING"
    assert updated_draft.llm_metadata["threads_post_ids"] == ["post1"]
    assert updated_draft.llm_metadata["published_url"] == "https://www.threads.net/@threads_star/post/post1"
    assert "Orphan container creation_id: c_orphan_abc" in updated_draft.feedback_notes


# ==========================================
# 4. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_threads_publishing_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # 4.1 Test POST /publishing/threads/connect
    with patch("app.services.publishing.threads.client.ThreadsClient.exchange_code_for_short_token") as mock_short, \
         patch("app.services.publishing.threads.client.ThreadsClient.exchange_short_for_long_token") as mock_long, \
         patch("app.services.publishing.threads.client.ThreadsClient.fetch_user_profile") as mock_profile:
         
        mock_short.return_value = {"access_token": "mock_short_val", "user_id": "123"}
        mock_long.return_value = {"access_token": "mock_long_val_60_days", "expires_in": 5184000}
        mock_profile.return_value = {"id": "threads_usr_id_888", "username": "meta_creator"}
        
        resp = await api_client.post("/api/v1/publishing/threads/connect?code=auth_threads_code_1122")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "connected"
        assert data["threads_user_id"] == "threads_usr_id_888"
        assert data["username"] == "meta_creator"
        
        # Verify account in DB
        res_acc = await db_session.execute(select(ThreadsAccount).where(ThreadsAccount.threads_user_id == "threads_usr_id_888"))
        acc = res_acc.scalars().first()
        assert acc is not None
        assert decrypt_token(acc.access_token) == "mock_long_val_60_days"
        
    # 4.2 Seed draft with status APPROVED
    draft = ContentDraft(
        id="d-threads-api-test",
        platform="threads",
        content_text="Threads platform test",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    # 4.3 Test POST /publishing/drafts/{draft_id}/publish-now
    with patch("app.services.publishing.threads.client.ThreadsClient.publish_post") as mock_publish:
        mock_publish.return_value = ["threads_live_post_id_abc"]
        
        resp_pub = await api_client.post("/api/v1/publishing/drafts/d-threads-api-test/publish-now")
        assert resp_pub.status_code == 200
        data_pub = resp_pub.json()
        assert data_pub["status"] == "PUBLISHED"
        assert data_pub["llm_metadata"]["threads_post_ids"] == ["threads_live_post_id_abc"]
        assert data_pub["llm_metadata"]["published_url"] == "https://www.threads.net/@meta_creator/post/threads_live_post_id_abc"
