import pytest
import pytest_asyncio
import sys
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.future import select

# Ensure backend directory is in path
sys.path.insert(0, "/Users/ommprakashmohanty/.gemini/antigravity-ide/scratch/personal-branding-engine/backend")

from app.database import Base, get_db
from app.main import app
from app.models.trend import Trend
from app.models.content import Persona, ContentDraft
from app.services.generation.formatters import (
    XFormatter,
    LinkedInFormatter,
    ThreadsFormatter,
    SubstackFormatter
)
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
def test_x_formatter_splitting():
    formatter = XFormatter()
    
    # Text shorter than 280 characters should remain intact
    short_text = "This is a short post."
    assert formatter.format(short_text) == short_text
    
    # Text exceeding 280 should split
    long_text = "Paragraph 1: " + "a" * 150 + "\n\nParagraph 2: " + "b" * 150
    formatted = formatter.format(long_text)
    assert "---thread-split---" in formatted
    parts = formatted.split("---thread-split---")
    assert len(parts) == 2
    assert all(len(p) <= 280 for p in parts)
    
    # Explicit splits
    explicit = "Post 1 ---thread-split--- Post 2"
    assert formatter.format(explicit) == "Post 1---thread-split---Post 2"

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
    trend = MagicMock(
        title="AI Frameworks",
        summary="A summary about frameworks",
        topic="AI",
        metadata_json={}
    )
    
    sys_prompt = await factory.render_system_prompt("linkedin", persona)
    assert "John Doe" in sys_prompt
    assert "LINKEDIN" in sys_prompt
    assert "Funny and sarcastic" in sys_prompt
    
    usr_prompt = factory.render_user_prompt(trend, feedback="Make it cooler")
    assert "AI Frameworks" in usr_prompt
    assert "Make it cooler" in usr_prompt


# ==========================================
# 3. ORCHESTRATOR TESTS
# ==========================================
@pytest.mark.asyncio
@patch("app.services.llm_provider.FallbackLLMProvider.generate")
async def test_orchestrator_generate_success(mock_generate: MagicMock, db_session: AsyncSession):
    mock_generate.return_value = "Generated text from LLM 🐍"
    
    # Seed required Trend in DB
    trend = Trend(
        id="t-1",
        canonical_url="https://url.com",
        title="AI agents",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    await db_session.commit()
    
    orchestrator = GenerationOrchestrator()
    draft = await orchestrator.generate_draft(
        db=db_session,
        trend_id="t-1",
        platform="linkedin"
    )
    
    assert draft.platform == "linkedin"
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
@patch("app.services.llm_provider.FallbackLLMProvider.generate")
async def test_generation_api_endpoints(mock_generate: MagicMock, api_client: httpx.AsyncClient, db_session: AsyncSession):
    mock_generate.return_value = "FastAPI is awesome! 🚀"
    
    # Seed Trend and Persona
    trend = Trend(
        id="t-2",
        canonical_url="https://fastapi.tiangolo.com",
        title="FastAPI update",
        topic="AI",
        published_at=datetime.now(timezone.utc)
    )
    db_session.add(trend)
    
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
    
    # 4.1 Test POST /trend/{trend_id}
    req_body = {
        "platforms": ["linkedin", "x"],
        "persona_id": "p-1"
    }
    resp = await api_client.post("/api/v1/generation/trend/t-2", json=req_body)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["platform"] == "linkedin"
    assert data[1]["platform"] == "x"
    
    # 4.2 Test GET /drafts
    resp_list = await api_client.get("/api/v1/generation/drafts?platform=x")
    assert resp_list.status_code == 200
    drafts_list = resp_list.json()
    assert len(drafts_list) == 1
    assert drafts_list[0]["platform"] == "x"
    draft_id = drafts_list[0]["id"]
    
    # 4.3 Test PUT /drafts/{id}/regenerate
    mock_generate.return_value = "FastAPI is super awesome! 🔥"
    resp_regen = await api_client.put(
        f"/api/v1/generation/drafts/{draft_id}/regenerate",
        json={"feedback": "Add fire emoji"}
    )
    assert resp_regen.status_code == 200
    data_regen = resp_regen.json()
    assert data_regen["content_text"] == "FastAPI is super awesome! 🔥"
    assert data_regen["status"] == "DRAFT"
    
    # 4.4 Test POST /batch
    resp_batch = await api_client.post("/api/v1/generation/batch")
    assert resp_batch.status_code == 202
    assert resp_batch.json()["status"] == "batch_generation_scheduled"
