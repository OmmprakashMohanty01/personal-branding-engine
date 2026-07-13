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
from app.models.content import Persona, ContentDraft
from app.services.generation.formatters import LinkedInFormatter
from app.services.generation.prompts import PromptFactory
from app.services.generation.orchestrator import GenerationOrchestrator

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
# 1. FORMATTER TESTS
# ==========================================
def test_linkedin_formatter_emojis_and_spacing():
    formatter = LinkedInFormatter()
    
    # LinkedIn post with more than 3 emojis should be capped
    text_with_emojis = "Python is great! 🐍 🚀 🔥 💻 🌟"
    formatted = formatter.format(text_with_emojis)
    # Check that only the first 3 emojis are kept
    assert "🐍" in formatted
    assert "🚀" in formatted
    assert "🔥" in formatted
    assert "💻" not in formatted
    assert "🌟" not in formatted
    
    # Spacing adjustment
    spaced = "Line 1\nLine 2"
    assert formatter.format(spaced) == "Line 1\n\nLine 2"


# ==========================================
# 2. PROMPT TEMPLATE TESTS
# ==========================================
@pytest.mark.asyncio
async def test_prompt_factory_rendering():
    factory = PromptFactory()
    
    # Mock data
    persona = MagicMock(
        name="John Doe",
        tone_description="Funny and sarcastic",
        vocabulary_rules="Use slang",
        formatting_preferences="Bullet points"
    )
    
    sys_prompt = await factory.render_system_prompt(persona)
    assert "John Doe" in sys_prompt
    assert "LINKEDIN" in sys_prompt
    assert "Funny and sarcastic" in sys_prompt
    
    usr_prompt = factory.render_user_prompt("AI Frameworks", feedback="Make it cooler")
    assert "AI Frameworks" in usr_prompt
    assert "Make it cooler" in usr_prompt


# ==========================================
# 3. ORCHESTRATOR TESTS
# ==========================================
@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("cohere.AsyncClient.chat")
async def test_orchestrator_generate_success(mock_cohere: MagicMock, mock_genai_client: MagicMock, db_session: AsyncSession):
    mock_client_instance = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = '{"content_text": "Generated text from LLM 🐍", "requires_image": false, "image_prompt": null}'
    mock_client_instance.interactions.create.return_value = mock_interaction
    mock_genai_client.return_value = mock_client_instance
    
    mock_cohere_resp = MagicMock()
    mock_cohere_resp.text = "Generated text from LLM 🐍"
    mock_cohere.return_value = mock_cohere_resp
    
    orchestrator = GenerationOrchestrator()
    draft = await orchestrator.generate_draft(
        db=db_session,
        topic="AI agents"
    )
    
    assert draft.content_text == "Generated text from LLM 🐍"
    assert draft.status == "DRAFT"
    
    # Verify saved draft in DB
    res = await db_session.execute(select(ContentDraft).where(ContentDraft.id == draft.id))
    saved_draft = res.scalars().first()
    assert saved_draft is not None
    assert saved_draft.content_text == "Generated text from LLM 🐍"


# ==========================================
# 4. API ROUTE TESTS
# ==========================================
@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("cohere.AsyncClient.chat")
@patch("app.services.publishing.linkedin.client.LinkedInClient.publish_post")
@patch("app.services.publishing.linkedin.client.LinkedInClient.check_and_refresh_token")
async def test_generation_api_endpoints(
    mock_refresh: MagicMock,
    mock_publish: MagicMock,
    mock_cohere: MagicMock,
    mock_genai_client: MagicMock,
    api_client: httpx.AsyncClient,
    db_session: AsyncSession
):
    mock_client_instance = MagicMock()
    mock_interaction = MagicMock()
    mock_interaction.output_text = '{"content_text": "FastAPI is awesome! 🚀", "requires_image": false, "image_prompt": null}'
    mock_client_instance.interactions.create.return_value = mock_interaction
    mock_genai_client.return_value = mock_client_instance
    
    mock_cohere_resp = MagicMock()
    mock_cohere_resp.text = "FastAPI is awesome! 🚀"
    mock_cohere.return_value = mock_cohere_resp
    mock_publish.return_value = "urn:li:share:mock_share_id"
    mock_refresh.return_value = "mock_access_token"
    
    # Seed Persona and LinkedIn Account
    from app.models.integration import LinkedInAccount
    account = LinkedInAccount(
        linkedin_person_urn="urn:li:person:mock",
        access_token="mock",
        expires_at=datetime.now(timezone.utc) + pytest.importorskip("datetime").timedelta(days=1)
    )
    db_session.add(account)
    
    persona = Persona(
        id="p-1",
        name="Technical Writer",
        tone_description="Clear",
        vocabulary_rules="Python",
        formatting_preferences="Paragraphs",
        is_default=True
    )
    db_session.add(persona)
    await db_session.commit()
    
    # 4.1 Test POST /generation (generate draft)
    req_body = {
        "topic": "FastAPI update",
        "persona_id": "p-1"
    }
    resp = await api_client.post("/api/v1/generation", json=req_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_text"] == "FastAPI is awesome! 🚀"
    assert data["status"] == "DRAFT"
    draft_id = data["id"]
    
    # 4.2 Test GET /generation/drafts (list drafts)
    resp_list = await api_client.get("/api/v1/generation/drafts")
    assert resp_list.status_code == 200
    drafts_list = resp_list.json()
    assert len(drafts_list) == 1
    assert drafts_list[0]["id"] == draft_id
    
    # 4.3 Test GET /generation/drafts/{id} (get draft)
    resp_get = await api_client.get(f"/api/v1/generation/drafts/{draft_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == draft_id
    
    # 4.4 Test PUT /generation/drafts/{id} (update draft)
    resp_update = await api_client.put(
        f"/api/v1/generation/drafts/{draft_id}",
        json={"content_text": "Updated content"}
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["content_text"] == "Updated content"
    
    # 4.5 Test POST /generation/drafts/{id}/publish (publish draft)
    resp_pub = await api_client.post(f"/api/v1/generation/drafts/{draft_id}/publish")
    assert resp_pub.status_code == 200
    assert resp_pub.json()["status"] == "PUBLISHED"
