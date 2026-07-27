"""
test_e2e_automation.py
======================
End-to-End integration tests for the daily automation endpoint.
Verifies atomicity, concurrency locks, observability, and full pipeline execution.
"""

import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

client = TestClient(app)

@pytest.fixture
def mock_db_session():
    # Setup mock session with required methods for atomicity and locking
    mock_session = AsyncMock(spec=AsyncSession)
    
    # Mock lock acquisition
    mock_result = MagicMock()
    mock_result.scalar.return_value = True
    
    # Mock returning Persona
    mock_persona_result = MagicMock()
    mock_persona = MagicMock()
    mock_persona.id = "mock_persona_id"
    mock_persona_result.scalars().first.return_value = mock_persona
    
    # Mock check_today_idempotency
    mock_idem_result = MagicMock()
    mock_idem_result.scalars().first.return_value = None
    
    # Sequence of returns for db.execute:
    # 1. check_today_idempotency count (scalars().first() -> None)
    # 2. get_persona (scalars().first() -> persona)
    # 3. publish_draft select draft (scalars().first() -> draft)
    # 4. _get_default_linkedin_account (scalars().first() -> account)
    mock_draft = ContentDraft(
        id="mock-draft-id",
        content_text="E2E test content",
        status="DRAFT",
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        llm_metadata={"requires_image": False}
    )
    mock_draft_result = MagicMock()
    mock_draft_result.scalars().first.return_value = mock_draft
    
    mock_account = LinkedInAccount(id="account-id", linkedin_person_urn="urn:li:person:123")
    mock_account_result = MagicMock()
    mock_account_result.scalars().first.return_value = mock_account

    mock_session.execute.side_effect = [
        mock_idem_result,    # 1. check_today_idempotency (scalars().first() -> None)
        mock_draft_result,   # 2. publish_draft (ContentDraft)
        mock_account_result, # 3. _get_default_linkedin_account
    ]
    
    return mock_session


@pytest.mark.asyncio
@patch("app.api.endpoints.automation.get_db")
@patch("app.services.generation.pipeline.ContentGenerationPipeline.run")
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
async def test_generate_daily_atomic_success(mock_publish, mock_run, mock_get_db, mock_db_session):
    # Setup mocks
    mock_get_db.return_value = mock_db_session
    mock_publish.return_value = "urn:li:share:987654321"
    
    mock_draft = ContentDraft(
        id="mock-draft-id",
        content_text="E2E test content",
        status="DRAFT",
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        llm_metadata={}
    )
    mock_run.return_value = mock_draft
    
    # Inject db session override
    app.dependency_overrides[get_db] = lambda: mock_db_session

    headers = {"X-Cron-Secret": "test_cron_secret"} # Assuming test env has this secret
    
    with patch("app.api.endpoints.automation.verify_cron_secret", return_value=None):
        with patch("app.api.endpoints.automation.settings.AUTO_PUBLISH_ENABLED", True):
            # We also mock weekday to not be Sunday
            with patch("app.api.endpoints.automation.datetime") as mock_datetime:
                mock_datetime.datetime.today.return_value.weekday.return_value = 1 # Monday
                mock_datetime.datetime.now = datetime.datetime.now
                mock_datetime.timezone = datetime.timezone
                
                response = client.post("/api/v1/automation/daily", headers=headers)

    app.dependency_overrides = {}
    
    assert response.status_code == 200
    assert response.json()["status"] == "PUBLISHED"
    
    # Verify atomicity lifecycle
    mock_run.assert_called_once()
    mock_db_session.rollback.assert_not_called()
    mock_publish.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.endpoints.automation.get_db")
async def test_generate_daily_concurrency_lock_failure(mock_get_db):
    # Setup mock to simulate another job holding the lock via IntegrityError on commit
    mock_session = AsyncMock(spec=AsyncSession)
    
    # Check today idempotency returns None
    mock_idem_result = MagicMock()
    mock_idem_result.scalars().first.return_value = None
    mock_session.execute.return_value = mock_idem_result
    
    from sqlalchemy.exc import IntegrityError
    mock_session.commit.side_effect = IntegrityError("Concurrent insert", params=None, orig=None)
    
    app.dependency_overrides[get_db] = lambda: mock_session

    with patch("app.api.endpoints.automation.verify_cron_secret", return_value=None):
        with patch("app.api.endpoints.automation.datetime") as mock_datetime:
            mock_datetime.datetime.today.return_value.weekday.return_value = 1 # Monday
            response = client.post("/api/v1/automation/daily")
            
    app.dependency_overrides = {}
    
    assert response.status_code == 429
    assert "Another automation process just started running" in response.json()["detail"]


@pytest.mark.asyncio
@patch("app.api.endpoints.automation.get_db")
@patch("app.services.generation.pipeline.ContentGenerationPipeline.run")
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
async def test_generate_daily_atomic_rollback_on_publish_failure(mock_publish, mock_run, mock_get_db, mock_db_session):
    mock_get_db.return_value = mock_db_session
    mock_publish.side_effect = Exception("LinkedIn API Timeout")
    
    mock_draft = ContentDraft(
        id="mock-draft-id",
        content_text="E2E test content",
        status="DRAFT",
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        llm_metadata={}
    )
    mock_run.return_value = mock_draft
    
    mock_idem_result = MagicMock()
    mock_idem_result.scalars().first.return_value = None
    
    mock_draft_result = MagicMock()
    mock_draft_result.scalars().first.return_value = mock_draft
    
    mock_account_result = MagicMock()
    mock_account_result.scalars().first.return_value = LinkedInAccount(id="test", linkedin_person_urn="test")
    
    mock_db_session.execute.side_effect = [
        mock_idem_result,
        mock_draft_result,
        mock_account_result
    ]
    
    app.dependency_overrides[get_db] = lambda: mock_db_session

    with patch("app.api.endpoints.automation.verify_cron_secret", return_value=None):
        with patch("app.api.endpoints.automation.settings.AUTO_PUBLISH_ENABLED", True):
            with patch("app.api.endpoints.automation.datetime") as mock_datetime:
                mock_datetime.datetime.today.return_value.weekday.return_value = 1 # Monday
                mock_datetime.datetime.now = datetime.datetime.now
                mock_datetime.timezone = datetime.timezone
                
                response = client.post("/api/v1/automation/daily")

    app.dependency_overrides = {}
    
    assert response.status_code == 500
    assert "LinkedIn API Timeout" in response.json()["detail"]
    
    # The transaction MUST rollback to maintain atomicity if the end-to-end flow breaks
    mock_db_session.rollback.assert_called_once()
