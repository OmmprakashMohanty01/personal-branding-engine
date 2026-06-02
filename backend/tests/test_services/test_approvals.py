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
from app.models.trend import Trend
from app.models.content import Persona, ContentDraft
from app.services.approval import ApprovalStateMachine, ApprovalService

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
# 1. STATE MACHINE TRANSITION TESTS
# ==========================================
def test_state_machine_valid_transitions():
    # Valid transitions should not raise any exceptions
    ApprovalStateMachine.validate_transition("DRAFT", "PENDING_APPROVAL")
    ApprovalStateMachine.validate_transition("DRAFT", "APPROVED")
    ApprovalStateMachine.validate_transition("PENDING_APPROVAL", "APPROVED")
    ApprovalStateMachine.validate_transition("PENDING_APPROVAL", "REJECTED")
    ApprovalStateMachine.validate_transition("REJECTED", "PENDING_APPROVAL")
    ApprovalStateMachine.validate_transition("APPROVED", "APPROVED") # Self transition

def test_state_machine_invalid_transitions():
    # Invalid transitions should raise ValueError
    with pytest.raises(ValueError) as exc:
        ApprovalStateMachine.validate_transition("APPROVED", "PENDING_APPROVAL")
    assert "Disallowed state transition" in str(exc.value)
    
    with pytest.raises(ValueError) as exc:
        ApprovalStateMachine.validate_transition("APPROVED", "REJECTED")
    assert "Disallowed state transition" in str(exc.value)
    
    with pytest.raises(ValueError) as exc:
        ApprovalStateMachine.validate_transition("REJECTED", "APPROVED")
    assert "Disallowed state transition" in str(exc.value)


# ==========================================
# 2. APPROVAL SERVICE BUSINESS LOGIC TESTS
# ==========================================
@pytest.mark.asyncio
async def test_approve_draft_fallback(db_session: AsyncSession):
    # Setup ContentDraft
    draft = ContentDraft(
        id="d-1",
        platform="linkedin",
        content_text="Original content text",
        status="DRAFT"
    )
    db_session.add(draft)
    await db_session.commit()
    
    service = ApprovalService()
    
    # 2.1 Approve with edited text override
    approved_override = await service.approve_draft(db_session, "d-1", "Edited content text")
    assert approved_override.status == "APPROVED"
    assert approved_override.final_content == "Edited content text"
    assert approved_override.approved_at is not None
    
    # Reset status back to DRAFT for next check (force direct update in DB)
    approved_override.status = "DRAFT"
    await db_session.commit()
    
    # 2.2 Approve with None (should fall back to original content_text)
    approved_fallback = await service.approve_draft(db_session, "d-1", None)
    assert approved_fallback.status == "APPROVED"
    assert approved_fallback.final_content == "Original content text"

@pytest.mark.asyncio
async def test_disallowed_trans_raises_value_error(db_session: AsyncSession):
    # Setup already APPROVED ContentDraft
    draft = ContentDraft(
        id="d-2",
        platform="linkedin",
        content_text="Original text",
        status="APPROVED"
    )
    db_session.add(draft)
    await db_session.commit()
    
    service = ApprovalService()
    
    # Attempting to reject an already APPROVED draft should fail
    with pytest.raises(ValueError) as exc:
        await service.reject_draft(db_session, "d-2", "Reject it anyway")
    assert "Disallowed state transition" in str(exc.value)


# ==========================================
# 3. ROUTE CONTROLLER API TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.llm_provider.FallbackLLMProvider.generate")
async def test_approval_api_endpoints_workflow(mock_generate: MagicMock, api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Mock LLM for revision requests
    mock_generate.return_value = "Revised content from LLM 🚀"
    
    # Seed Database with Trend, Persona, and Draft
    trend = Trend(
        id="t-3",
        canonical_url="https://domain.com",
        title="Agentic AI workflows",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    
    persona = Persona(
        id="p-2",
        name="Curation Persona",
        tone_description="Friendly",
        vocabulary_rules="Tech",
        formatting_preferences="Clean",
        is_default=True
    )
    db_session.add(persona)
    await db_session.commit()
    
    draft = ContentDraft(
        id="d-3",
        trend_id="t-3",
        persona_id="p-2",
        platform="x",
        content_text="Initial draft post text",
        status="PENDING_APPROVAL"
    )
    db_session.add(draft)
    await db_session.commit()
    
    # 3.1 Test GET /approvals/pending
    resp_pending = await api_client.get("/api/v1/approvals/pending?platform=x")
    assert resp_pending.status_code == 200
    pending_list = resp_pending.json()
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == "d-3"
    
    # 3.2 Test POST /approvals/{id}/revise (Request Revision)
    resp_revise = await api_client.post(
        "/api/v1/approvals/d-3/revise",
        json={"feedback_notes": "Make it much punchier"}
    )
    assert resp_revise.status_code == 200
    data_rev = resp_revise.json()
    assert data_rev["content_text"] == "Revised content from LLM 🚀"
    assert data_rev["status"] == "PENDING_APPROVAL"
    assert data_rev["feedback_notes"] == "Make it much punchier"
    
    # 3.3 Test POST /approvals/{id}/reject
    resp_reject = await api_client.post(
        "/api/v1/approvals/d-3/reject",
        json={"reason": "We do not like this version"}
    )
    assert resp_reject.status_code == 200
    data_rej = resp_reject.json()
    assert data_rej["status"] == "REJECTED"
    assert data_rej["feedback_notes"] == "We do not like this version"
    
    # 3.4 Test POST /approvals/{id}/approve (Approve Rejected Draft -> wait, is REJECTED -> APPROVED allowed?
    # No, state machine disallowed: REJECTED only goes to PENDING_APPROVAL via revise.
    # Let's confirm that trying to approve a REJECTED draft returns a 409 Conflict.
    resp_approve_rejected = await api_client.post(
        "/api/v1/approvals/d-3/approve",
        json={"edited_content": "Manually fixed content"}
    )
    assert resp_approve_rejected.status_code == 409
    assert "Disallowed state transition" in resp_approve_rejected.json()["detail"]
