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
from app.models.integration import SubstackAccount
from app.services.publishing.substack.client import SubstackClient
from app.services.publishing.orchestrator import PublishingOrchestrator
import smtplib

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
# 1. CLIENT FORMATTING & SMTP DISPATCH TESTS
# ==========================================
@pytest.mark.asyncio
@patch("smtplib.SMTP")
async def test_substack_client_formatting_and_send(mock_smtp_class: MagicMock, db_session: AsyncSession):
    mock_smtp_instance = MagicMock()
    mock_smtp_class.return_value = mock_smtp_instance
    
    account = SubstackAccount(
        newsletter_name="My Tech Brand",
        secret_email_address="secret-ingest@substack.post",
        author_email="authorized@sender.com"
    )
    db_session.add(account)
    await db_session.commit()
    
    client = SubstackClient()
    client.smtp_host = "smtp.test.com"
    client.smtp_port = 587
    client.smtp_user = "test_user"
    client.smtp_password = "test_password"
    
    draft_content = "# Welcome to the Brand Engine\n\nThis is a newsletter text.\n\n- Bullet 1\n- Bullet 2"
    
    await client.publish_post(db_session, account, draft_content)
    
    # Verify SMTP was called
    mock_smtp_class.assert_called_once_with("smtp.test.com", 587, timeout=10)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("test_user", "test_password")
    mock_smtp_instance.sendmail.assert_called_once()
    mock_smtp_instance.quit.assert_called_once()
    
    # Assert sent mail content
    args, kwargs = mock_smtp_instance.sendmail.call_args
    from_email, to_email, msg_str = args
    assert from_email == "authorized@sender.com"
    assert to_email == "secret-ingest@substack.post"
    assert "Subject: Welcome to the Brand Engine" in msg_str
    
    # Verify markdown was parsed to HTML
    assert "<p>This is a newsletter text.</p>" in msg_str
    assert "<li>Bullet 1</li>" in msg_str


@pytest.mark.asyncio
@patch("smtplib.SMTP_SSL")
async def test_substack_client_ssl_send(mock_smtp_ssl_class: MagicMock, db_session: AsyncSession):
    mock_smtp_ssl_instance = MagicMock()
    mock_smtp_ssl_class.return_value = mock_smtp_ssl_instance
    
    account = SubstackAccount(
        newsletter_name="My Tech Brand",
        secret_email_address="secret-ingest@substack.post",
        author_email="authorized@sender.com"
    )
    db_session.add(account)
    await db_session.commit()
    
    client = SubstackClient()
    client.smtp_host = "smtp.test.com"
    client.smtp_port = 465
    client.smtp_user = "test_user"
    client.smtp_password = "test_password"
    
    await client.publish_post(db_session, account, "# Title\nContent here")
    
    mock_smtp_ssl_class.assert_called_once_with("smtp.test.com", 465, timeout=10)
    mock_smtp_ssl_instance.login.assert_called_once_with("test_user", "test_password")
    mock_smtp_ssl_instance.sendmail.assert_called_once()
    mock_smtp_ssl_instance.quit.assert_called_once()


# ==========================================
# 2. ORCHESTRATOR PUBLISHING RUNS TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.publishing.substack.client.SubstackClient.publish_post")
async def test_orchestrator_substack_success(mock_publish: MagicMock, db_session: AsyncSession):
    account = SubstackAccount(
        newsletter_name="My Tech Brand",
        secret_email_address="secret-ingest@substack.post",
        author_email="authorized@sender.com"
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-s-10",
        platform="substack",
        content_text="# Title\nContent text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-s-10")
    
    assert updated_draft.status == "PUBLISHED"
    assert updated_draft.llm_metadata["substack_dispatch"] == "Successfully sent post via email-to-publish draft ingestion."
    assert updated_draft.llm_metadata["published_url"] == "https://substack.com"
    mock_publish.assert_called_once_with(db_session, account, "# Title\nContent text")


@pytest.mark.asyncio
@patch("app.services.publishing.substack.client.SubstackClient.publish_post")
async def test_orchestrator_substack_smtp_failure(mock_publish: MagicMock, db_session: AsyncSession):
    mock_publish.side_effect = smtplib.SMTPAuthenticationError(535, "Authentication failed")
    
    account = SubstackAccount(
        newsletter_name="My Tech Brand",
        secret_email_address="secret-ingest@substack.post",
        author_email="authorized@sender.com"
    )
    db_session.add(account)
    
    draft = ContentDraft(
        id="d-s-11",
        platform="substack",
        content_text="# Title\nContent text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    orchestrator = PublishingOrchestrator()
    updated_draft = await orchestrator.publish_draft(db_session, "d-s-11")
    
    assert updated_draft.status == "FAILED_PUBLISHING"
    assert "SMTP publishing failed" in updated_draft.feedback_notes
    assert "Authentication failed" in updated_draft.feedback_notes


# ==========================================
# 3. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_substack_publishing_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # 3.1 Test POST /publishing/substack/config
    payload = {
        "newsletter_name": "Tech Insights",
        "secret_email_address": "secret@substack.post",
        "author_email": "authorized@domain.com"
    }
    resp = await api_client.post("/api/v1/publishing/substack/config", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "configured"
    assert data["newsletter_name"] == "Tech Insights"
    
    # Verify saved in DB
    res_acc = await db_session.execute(select(SubstackAccount).where(SubstackAccount.newsletter_name == "Tech Insights"))
    acc = res_acc.scalars().first()
    assert acc is not None
    assert acc.secret_email_address == "secret@substack.post"
    assert acc.author_email == "authorized@domain.com"
    
    # 3.2 Seed draft with status APPROVED
    draft = ContentDraft(
        id="d-substack-api-test",
        platform="substack",
        content_text="# API Title\nContent API",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    # 3.3 Test POST /publishing/drafts/{draft_id}/publish-now
    with patch("app.services.publishing.substack.client.SubstackClient.publish_post") as mock_publish:
        resp_pub = await api_client.post("/api/v1/publishing/drafts/d-substack-api-test/publish-now")
        assert resp_pub.status_code == 200
        data_pub = resp_pub.json()
        assert data_pub["status"] == "PUBLISHED"
        assert data_pub["llm_metadata"]["substack_dispatch"] == "Successfully sent post via email-to-publish draft ingestion."
        mock_publish.assert_called_once()
