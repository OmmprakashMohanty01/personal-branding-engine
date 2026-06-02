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
from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token
from app.services.publishing.linkedin.client import LinkedInClient
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


# ==========================================
# 1. CRYPTO HELPER TESTS
# ==========================================
def test_encryption_decryption_utility():
    plain = "secret-token-key-1234"
    enc = encrypt_token(plain)
    assert enc != plain
    dec = decrypt_token(enc)
    assert dec == plain


# ==========================================
# 2. CLIENT TOKEN LIFECYCLE TESTS
# ==========================================
@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_client_refresh_expired_token(mock_post: MagicMock, db_session: AsyncSession):
    # Set up expired LinkedIn account
    now = datetime.now(timezone.utc)
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:principal",
        access_token=encrypt_token("old_access_token"),
        refresh_token=encrypt_token("valid_refresh_token"),
        expires_at=now - timedelta(hours=1), # Expired 1 hour ago
        refresh_expires_at=now + timedelta(days=30)
    )
    db_session.add(account)
    await db_session.commit()
    
    # Mock LinkedIn Token API Response
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {
        "access_token": "new_access_token_123",
        "refresh_token": "new_refresh_token_456",
        "expires_in": 3600,
        "refresh_token_expires_in": 86400
    }
    
    client = LinkedInClient()
    # Forces refresh, should return the refreshed access token
    active_token = await client.check_and_refresh_token(db_session, account)
    
    assert active_token == "new_access_token_123"
    
    # Verify values saved to DB
    res = await db_session.execute(select(LinkedInAccount).where(LinkedInAccount.id == account.id))
    db_account = res.scalars().first()
    assert db_account is not None
    assert decrypt_token(db_account.access_token) == "new_access_token_123"
    assert decrypt_token(db_account.refresh_token) == "new_refresh_token_456"
    assert db_account.expires_at > now


# ==========================================
# 3. ORCHESTRATOR PUBLISHING RUNS TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
async def test_orchestrator_publishing_success(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.return_value = "urn:li:share:share_id_987"
    
    # Seed account and approved draft in database
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-10",
        platform="linkedin",
        content_text="LinkedIn post text",
        final_content="Edited LinkedIn post text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-10")
    
    assert updated_draft.status == "PUBLISHED"
    assert updated_draft.llm_metadata["linkedin_post_id"] == "urn:li:share:share_id_987"
    assert "published_url" in updated_draft.llm_metadata

    # Assert database cleanup expunged the record
    db_session.expire_all()
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == "d-10"))
    db_draft = res.scalars().first()
    assert db_draft is None

@pytest.mark.asyncio
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
async def test_orchestrator_publishing_failure_handling(mock_publish: MagicMock, db_session: AsyncSession):
    # Simulate API HTTP Error
    mock_publish.side_effect = Exception("HTTP 400 Bad Request: Invalid payload structure")
    
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-11",
        platform="linkedin",
        content_text="LinkedIn post text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-11")
    
    assert updated_draft.status == "FAILED_PUBLISHING"
    assert "Publishing failed" in updated_draft.feedback_notes

    # Assert database preserves the record for review
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == "d-11"))
    db_draft = res.scalars().first()
    assert db_draft is not None
    assert db_draft.status == "FAILED_PUBLISHING"


# ==========================================
# 4. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_publishing_api_endpoints_connect_and_publish(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # 4.1 Test POST /publishing/linkedin/connect (Mocked exchange code callback)
    resp_connect = await api_client.post("/api/v1/publishing/linkedin/connect?code=auth_code_123")
    assert resp_connect.status_code == 200
    data_conn = resp_connect.json()
    assert data_conn["status"] == "connected"
    assert "linkedin_person_urn" in data_conn
    
    # URN should have been saved to DB
    res_acc = await db_session.execute(select(LinkedInAccount))
    account = res_acc.scalars().first()
    assert account is not None
    
    # 4.2 Seed draft with status APPROVED
    draft = ContentDraft(
        id="d-12",
        platform="linkedin",
        content_text="LinkedIn post text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    # 4.3 Test POST /publishing/drafts/{draft_id}/publish-now
    with patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post") as mock_publish:
        mock_publish.return_value = "urn:li:share:urn_test_123"
        
        resp_pub = await api_client.post("/api/v1/publishing/drafts/d-12/publish-now")
        assert resp_pub.status_code == 200
        data_pub = resp_pub.json()
        assert data_pub["status"] == "PUBLISHED"
        assert data_pub["llm_metadata"]["linkedin_post_id"] == "urn:li:share:urn_test_123"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_client_refresh_within_48_hours(mock_post: MagicMock, db_session: AsyncSession):
    now = datetime.now(timezone.utc)
    # Token expires in 40 hours (within the 48-hour threshold window)
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:principal",
        access_token=encrypt_token("old_access_token"),
        refresh_token=encrypt_token("valid_refresh_token"),
        expires_at=now + timedelta(hours=40),
        refresh_expires_at=now + timedelta(days=30)
    )
    db_session.add(account)
    await db_session.commit()
    
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {
        "access_token": "new_refreshed_access_48h",
        "refresh_token": "valid_refresh_token",
        "expires_in": 3600,
        "refresh_token_expires_in": 86400
    }
    
    client = LinkedInClient()
    active_token = await client.check_and_refresh_token(db_session, account)
    
    assert active_token == "new_refreshed_access_48h"
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_linkedin_pre_flight_length_validation_failure(db_session: AsyncSession):
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    # 3001 characters (exceeds LinkedIn limit of 3000)
    long_content = "l" * 3001
    draft = ContentDraft(
        id="d-li-long",
        platform="linkedin",
        content_text=long_content,
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-li-long")
    
    assert updated_draft.status == "FAILED_PUBLISHING"
    assert "Pre-flight validation failed" in updated_draft.feedback_notes
