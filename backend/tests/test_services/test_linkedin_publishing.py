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
    
    # Seed account and draft in database
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-10",
        content_text="LinkedIn post text",
        status="DRAFT"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-10")
    
    assert updated_draft.status == "PUBLISHED"
    assert updated_draft.llm_metadata["linkedin_post_id"] == "urn:li:share:share_id_987"
    assert "published_url" in updated_draft.llm_metadata

    # Verify that the draft was NOT deleted but remains in database with PUBLISHED status
    db_session.expire_all()
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == "d-10"))
    db_draft = res.scalars().first()
    assert db_draft is not None
    assert db_draft.status == "PUBLISHED"

@pytest.mark.asyncio
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
async def test_orchestrator_publishing_failure_handling(mock_publish: MagicMock, db_session: AsyncSession):
    # Simulate API HTTP Error
    mock_publish.side_effect = Exception("HTTP 400 Bad Request")
    
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("access"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-11",
        content_text="LinkedIn post text",
        status="DRAFT"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    with pytest.raises(Exception):
        await orchestrator.publish_draft(db_session, "d-11")
    
    # Assert database preserves the record for review in FAILED status
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == "d-11"))
    db_draft = res.scalars().first()
    assert db_draft is not None
    assert db_draft.status == "FAILED"


# ==========================================
# 4. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_publishing_api_endpoints_connect(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Test POST /publishing/linkedin/connect (Mocked exchange code callback)
    resp_connect = await api_client.post("/api/v1/publishing/linkedin/connect?code=auth_code_123&redirect_uri=https://personal-branding-engine.vercel.app")
    assert resp_connect.status_code == 200
    data_conn = resp_connect.json()
    assert data_conn["status"] == "connected"
    assert "linkedin_person_urn" in data_conn
    
    # URN should have been saved to DB
    res_acc = await db_session.execute(select(LinkedInAccount))
    account = res_acc.scalars().first()
    assert account is not None


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
        content_text=long_content,
        status="DRAFT"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    with pytest.raises(ValueError) as exc_info:
        await orchestrator.publish_draft(db_session, "d-li-long")
    
    assert "exceeds 3,000-character limit" in str(exc_info.value)
    
    # Verify status is FAILED in db
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == "d-li-long"))
    db_draft = res.scalars().first()
    assert db_draft is not None
    assert db_draft.status == "FAILED"


@pytest.mark.asyncio
async def test_check_and_refresh_token_corrupted_wipes_db(db_session: AsyncSession):
    # Seed a token that is encrypted with a different key
    from cryptography.fernet import Fernet
    different_key = Fernet.generate_key()
    corrupted_payload = Fernet(different_key).encrypt(b"some_access_token").decode()

    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=corrupted_payload,
        expires_at=datetime.now(timezone.utc) + timedelta(days=5)
    )
    db_session.add(account)
    await db_session.commit()

    from fastapi import HTTPException
    client = LinkedInClient()
    with pytest.raises(HTTPException) as exc_info:
        await client.check_and_refresh_token(db_session, account)

    assert exc_info.value.status_code == 401
    assert "expired or corrupted" in exc_info.value.detail

    # Verify account was deleted from database
    res = await db_session.execute(select(LinkedInAccount).where(LinkedInAccount.id == account.id))
    db_account = res.scalars().first()
    assert db_account is None


@pytest.mark.asyncio
async def test_publish_post_with_image_upload(db_session: AsyncSession):
    # Mock account
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:abc",
        access_token=encrypt_token("some_token"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=5)
    )
    db_session.add(account)
    await db_session.commit()

    client = LinkedInClient()
    
    with patch("httpx.AsyncClient.post") as mock_post, patch("httpx.AsyncClient.put") as mock_put:
        # Mock registerUpload response
        mock_register_resp = MagicMock(status_code=200)
        mock_register_resp.json.return_value = {
            "value": {
                "uploadMechanism": {
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                        "uploadUrl": "https://api.linkedin.com/upload-target-123"
                    }
                },
                "asset": "urn:li:digitalmediaAsset:C123XYZ"
            }
        }
        
        # Mock posts response
        mock_posts_resp = MagicMock(status_code=201)
        mock_posts_resp.headers = {"x-restli-id": "urn:li:share:post_123_abc"}
        
        # Make post call return register response first, then posts response
        mock_post.side_effect = [mock_register_resp, mock_posts_resp]
        
        mock_put_resp = MagicMock(status_code=200)
        mock_put.return_value = mock_put_resp
        
        image_base64 = "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        post_urn = await client.publish_post(db_session, account, "Test commentary", image_url=image_base64)
        
        assert post_urn == "urn:li:share:post_123_abc"
        
        # Assert registerUpload POST was called
        mock_post.assert_any_call(
            "https://api.linkedin.com/v2/assets?action=registerUpload",
            json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": "urn:li:person:abc",
                    "serviceRelationships": [
                        {
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent"
                        }
                    ],
                    "supportedUploadMechanism": ["SYNCHRONOUS_UPLOAD"]
                }
            },
            headers={
                "Authorization": "Bearer some_token",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            }
        )
        
        # Assert PUT request was called with binary data
        import base64
        expected_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
        mock_put.assert_called_once_with(
            "https://api.linkedin.com/upload-target-123",
            content=expected_bytes,
            headers={"Content-Type": "application/octet-stream"}
        )
        
        # Assert posts POST was called with content media URN and shareMediaCategory
        mock_post.assert_any_call(
            "https://api.linkedin.com/v2/posts",
            json={
                "author": "urn:li:person:abc",
                "commentary": "Test commentary",
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": []
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
                "content": {
                    "media": {
                        "id": "urn:li:digitalmediaAsset:C123XYZ"
                    }
                },
                "shareMediaCategory": "IMAGE"
            },
            headers={
                "Authorization": "Bearer some_token",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0"
            }
        )
