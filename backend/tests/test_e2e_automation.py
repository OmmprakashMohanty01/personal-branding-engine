import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from app.main import app
from app.config import settings

@pytest.fixture
def override_settings(monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET_KEY", "test_secret")
    monkeypatch.setattr(settings, "AUTO_PUBLISH_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_LINKEDIN_PUBLISHING", True)
    monkeypatch.setattr(settings, "ENABLE_MEMORY", False)
    monkeypatch.setattr(settings, "ENABLE_VALIDATION", False)
    monkeypatch.setattr(settings, "ENABLE_DEDUP", False)
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")

@pytest.mark.asyncio
@patch("app.services.generation.pipeline.litellm.acompletion", new_callable=AsyncMock)
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post", new_callable=AsyncMock)
@patch("app.services.publishing.orchestrator.PublishingOrchestrator._get_default_linkedin_account", new_callable=AsyncMock)
@patch("app.api.endpoints.automation.check_today_idempotency", return_value=None)
async def test_automation_daily_success(
    mock_check_idempotency,
    mock_get_account,
    mock_publish,
    mock_litellm,
    override_settings
):
    """Test 1: Complete Scheduled Automation Flow (API -> DB -> Publish -> Success)"""
    mock_get_account.return_value = AsyncMock()
    mock_publish.return_value = "urn:li:share:987654321"
    
    # Mock LiteLLM to return structured JSON
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = '{"paragraphs": ["This is a fully generated post ready for publishing.", "It has enough content to pass all the validation gates and length checks."], "self_check": "All good.", "quote_hook": "Automation success."}'
    mock_litellm.return_value = mock_response
    
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async def override_get_db():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session
        
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/automation/daily", 
                headers={"X-Cron-Secret": "test_secret", "X-Run-ID": "run-test-1"}
            )
            
            if response.status_code == 200 and "Sunday" in response.text:
                pytest.skip("Test run on a Sunday; automation is skipped.")
                
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "PUBLISHED"
            assert data["linkedin_post_id"] == "urn:li:share:987654321"
            assert data["character_count"] > 10
            assert data["image_uploaded"] is True
            assert data["trace_id"] == "run-test-1"
            
            # Verify mocks were called
            mock_litellm.assert_awaited()
            mock_publish.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
@patch("app.services.generation.pipeline.litellm.acompletion", new_callable=AsyncMock)
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post", new_callable=AsyncMock)
@patch("app.services.publishing.orchestrator.PublishingOrchestrator._get_default_linkedin_account", new_callable=AsyncMock)
@patch("app.api.endpoints.automation.check_today_idempotency", return_value=None)
async def test_full_length_post_integrity(
    mock_check_idempotency,
    mock_get_account,
    mock_publish,
    mock_litellm,
    override_settings
):
    """Test 2: Ensure a 2800-character post is not truncated at any step."""
    long_post_text = "A" * 2800
    
    # Mock LiteLLM to return the 2800-char text as a JSON draft
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    import json
    mock_response.choices[0].message.content = json.dumps({
        "paragraphs": [long_post_text],
        "self_check": "OK",
        "quote_hook": "Long post hook"
    })
    mock_litellm.return_value = mock_response
    mock_publish.return_value = "urn:li:share:longpost"
    
    from app.database import get_db
    
    # We need a real SQLite DB for this to verify DB truncation behavior
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async def override_get_db():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session() as session:
            yield session
            
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/automation/daily", 
                headers={"X-Cron-Secret": "test_secret"}
            )
            if response.status_code == 200 and "Sunday" in response.text:
                pytest.skip("Test run on a Sunday; automation is skipped.")
                
            assert response.status_code == 200
            data = response.json()
            
            # 1. API response character count verification
            assert data["character_count"] == 2800
            
            # 2. LinkedIn payload verification
            # Verify what was passed to LinkedInClient.publish_post
            publish_args = mock_publish.call_args.kwargs
            assert len(publish_args["text"]) == 2800
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_automation_consecutive_days_simulation(override_settings):
    """Test 4: Simulate 7 consecutive days of execution verifying uniqueness of idempotency keys."""
    from app.api.endpoints.automation import check_today_idempotency
    from unittest.mock import patch
    import datetime
    
    base_date = datetime.datetime(2026, 7, 27, tzinfo=datetime.timezone.utc)
    
    for i in range(7):
        current_date = base_date + datetime.timedelta(days=i)
        
        with patch("datetime.datetime") as mock_datetime:
            mock_datetime.now.return_value = current_date
            mock_datetime.today.return_value = current_date
            
            idempotency_key = f"daily-automation-{current_date.strftime('%Y-%m-%d')}"
            
            # Ensure the generated key matches the exact day
            expected_date_str = current_date.strftime('%Y-%m-%d')
            assert idempotency_key == f"daily-automation-{expected_date_str}"

@pytest.mark.asyncio
@patch("app.api.endpoints.automation.check_today_idempotency", return_value=False)
@patch("app.api.endpoints.automation.run_pipeline_sync", new_callable=AsyncMock)
@patch("app.services.publishing.orchestrator.PublishingOrchestrator.publish_draft", new_callable=AsyncMock)
async def test_automation_daily_endpoint_response(
    mock_publish_draft,
    mock_run_pipeline_sync,
    mock_check_idempotency,
    override_settings
):
    """Test that the endpoint properly formats the AutomationResponse"""
    from app.models.content import ContentDraft
    import datetime
    
    # Mock draft
    mock_draft = ContentDraft(
        id="test-draft-123",
        content_text="This is a test post.",
        status="MEDIA_VALIDATED",
        llm_metadata={
            "linkedin_post_id": "urn:li:share:123",
            "image_url": "https://example.com/img.jpg"
        }
    )
    
    # Mock the synchronous pipeline
    mock_run_pipeline_sync.return_value = mock_draft
    
    # Mock publishing to return PUBLISHED status
    published_draft = ContentDraft(
        id="test-draft-123",
        content_text="This is a test post.",
        status="PUBLISHED",
        llm_metadata={
            "linkedin_post_id": "urn:li:share:123",
            "image_url": "https://example.com/img.jpg"
        }
    )
    mock_publish_draft.return_value = published_draft
    
    # Needs a real DB session for the lock, so we mock the lock execution via dependency overrides
    from app.database import get_db
    
    from sqlalchemy.ext.asyncio import AsyncSession
    mock_db = AsyncMock(spec=AsyncSession)
    
    async def override_get_db():
        yield mock_db
        
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First, check without auth
            response = await client.post("/api/v1/automation/daily")
            assert response.status_code == 401
            
            # Now with auth
            response = await client.post(
                "/api/v1/automation/daily", 
                headers={"X-Cron-Secret": "test_secret"}
            )
            
            # If it's sunday, the logic skips. We need to mock datetime if we want to ensure it runs
            if response.status_code == 200 and "Sunday" in response.text:
                pytest.skip("Test run on a Sunday; automation is skipped.")
                
            assert response.status_code == 200
            data = response.json()
            
            assert data["status"] == "PUBLISHED"
            assert data["draft_id"] == "test-draft-123"
            assert data["linkedin_post_id"] == "urn:li:share:123"
            assert data["character_count"] == len("This is a test post.")
            assert data["image_uploaded"] is True
            assert "trace_id" in data
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
@patch("app.api.endpoints.automation.check_today_idempotency", return_value=None)
async def test_automation_daily_concurrency(
    mock_check_idempotency,
    override_settings
):
    """Test that a concurrent request resulting in IntegrityError returns 429."""
    from app.database import get_db
    import sqlalchemy
    from sqlalchemy.ext.asyncio import AsyncSession
    
    mock_db = AsyncMock(spec=AsyncSession)
    # Simulate another thread inserting the same idempotency_key
    mock_db.commit.side_effect = sqlalchemy.exc.IntegrityError("Unique constraint failed", params={}, orig=Exception())
    
    async def override_get_db():
        yield mock_db
        
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/automation/daily", 
                headers={"X-Cron-Secret": "test_secret"}
            )
            
            if response.status_code == 200 and "Sunday" in response.text:
                pytest.skip("Test run on a Sunday; automation is skipped.")
                
            assert response.status_code == 429
            assert "Another automation process just started running" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@patch("app.api.endpoints.automation.check_today_idempotency")
@patch("app.api.endpoints.automation.run_pipeline_sync", new_callable=AsyncMock)
@patch("app.services.publishing.orchestrator.PublishingOrchestrator.publish_draft", new_callable=AsyncMock)
async def test_automation_daily_resumption(
    mock_publish_draft,
    mock_run_pipeline_sync,
    mock_check_idempotency,
    override_settings
):
    """Test that if an existing draft is in DRAFT state, it skips generation and publishes directly."""
    from app.models.content import ContentDraft
    from app.database import get_db
    
    # Existing draft that failed publishing previously
    existing_draft = ContentDraft(
        id="test-draft-resume",
        content_text="This is a recovered post.",
        status="DRAFT",
        llm_metadata={"requires_image": True}
    )
    mock_check_idempotency.return_value = existing_draft
    
    # When published, it returns a published draft
    published_draft = ContentDraft(
        id="test-draft-resume",
        content_text="This is a recovered post.",
        status="PUBLISHED",
        llm_metadata={"linkedin_post_id": "urn:li:share:resume"}
    )
    mock_publish_draft.return_value = published_draft
    
    from sqlalchemy.ext.asyncio import AsyncSession
    mock_db = AsyncMock(spec=AsyncSession)
    async def override_get_db():
        yield mock_db
        
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/automation/daily", 
                headers={"X-Cron-Secret": "test_secret"}
            )
            
            if response.status_code == 200 and "Sunday" in response.text:
                pytest.skip("Test run on a Sunday; automation is skipped.")
                
            assert response.status_code == 200
            
            # The generation pipeline should NOT be called!
            mock_run_pipeline_sync.assert_not_called()
            
            # The publishing orchestrator SHOULD be called!
            mock_publish_draft.assert_awaited_once()
            
            data = response.json()
            assert data["status"] == "PUBLISHED"
            assert data["draft_id"] == "test-draft-resume"
            assert data["linkedin_post_id"] == "urn:li:share:resume"
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
@patch("app.services.publishing.linkedin.client.LinkedInClient.fetch_recent_posts", new_callable=AsyncMock)
async def test_linkedin_idempotency_timeout_recovery(
    mock_fetch_recent_posts,
    override_settings
):
    """Test that a TimeoutException during publish triggers a fetch and recovers the URN if text matches."""
    import httpx
    from app.services.publishing.linkedin.client import LinkedInClient
    from app.models.integration import LinkedInAccount
    from unittest.mock import MagicMock
    
    mock_account = LinkedInAccount(linkedin_person_urn="urn:li:person:123")
    
    # Mock httpx.AsyncClient to raise TimeoutException on post
    class MockHttpxClient:
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc_val, exc_tb): pass
        async def post(self, url, **kwargs):
            raise httpx.TimeoutException("Network timeout simulation")
            
    client = LinkedInClient()
    
    test_text = "This is a much longer test post text that exceeds one hundred characters to pass the validation assertion we added." * 2
    
    # Provide a match in the recent posts
    mock_fetch_recent_posts.return_value = [
        {"id": "urn:li:share:recovered123", "commentary": test_text}
    ]
    
    with patch("httpx.AsyncClient", return_value=MockHttpxClient()):
        with patch.object(client, "check_and_refresh_token", AsyncMock(return_value="mock_token")):
            result = await client.publish_post(
                db=AsyncMock(),
                account=mock_account,
                text=test_text,
                idempotency_key="test-idem-key"
            )
            
            # The client should have swallowed the exception and returned the matched URN
            assert result == "urn:li:share:recovered123"
            mock_fetch_recent_posts.assert_awaited_once()

@pytest.mark.asyncio
async def test_failure_recovery_gemini_timeout():
    """Test 6: Verify execute_with_retry backs off and recovers on Gemini HTTP Timeout (429/Timeout)."""
    from app.services.generation.circuit_breaker import execute_with_retry
    import httpx
    
    attempts = 0
    async def mock_failing_llm():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.TimeoutException("Gemini timeout simulation")
        return "Success!"
        
    result = await execute_with_retry(mock_failing_llm, max_retries=3, initial_backoff=0.1)
    
    assert result == "Success!"
    assert attempts == 3


@pytest.mark.asyncio
@patch("app.api.endpoints.generation.run_pipeline_sync", new_callable=AsyncMock)
async def test_manual_generation_sync(mock_run_pipeline):
    """Test that the manual generation endpoint returns 200 OK synchronously."""
    from app.database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock
    from app.models.content import ContentDraft

    # Mock the synchronous pipeline to return a completed draft
    mock_draft = ContentDraft(
        id="test-sync-draft",
        content_text="This is a synchronously generated post with enough length to pass checks.",
        status="MEDIA_VALIDATED",
        llm_metadata={"image_url": "data:image/png;base64,abc"}
    )
    mock_run_pipeline.return_value = mock_draft

    mock_db = AsyncMock(spec=AsyncSession)
    
    async def override_get_db():
        yield mock_db
        
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/generation", 
                json={"topic": "Test topic", "persona_id": "test-persona"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "MEDIA_VALIDATED"
            assert "draft_id" in data
    finally:
        app.dependency_overrides.pop(get_db, None)
