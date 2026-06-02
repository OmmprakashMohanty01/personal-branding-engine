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
from app.models.content import ContentDraft, PostAnalytics, Persona
from app.models.trend import Trend
from app.models.optimization import OptimizationFeedback
from app.services.optimization.analyzer import FeedbackAnalyzer
from app.services.optimization.optimizer import PromptOptimizer
from app.services.generation.prompts import PromptFactory
from app.services.generation.orchestrator import GenerationOrchestrator
from app.services.llm_provider import FallbackLLMProvider

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
# 1. FEEDBACK ANALYZER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_feedback_analyzer_aggregation(db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-opt-1",
        name="Opt Persona",
        tone_description="Assertive",
        vocabulary_rules="Tech only",
        formatting_preferences="Concise"
    )
    db_session.add(persona)
    await db_session.flush()
    
    # 1. Add human corrections: final_content != content_text
    d1 = ContentDraft(
        persona_id=persona.id,
        platform="x",
        content_text="Draft post about AI.",
        final_content="Optimized punchy post about AI.", # Human correction
        status="PUBLISHED",
        updated_at=datetime.now(timezone.utc)
    )
    # 2. Add rejection notes
    d2 = ContentDraft(
        persona_id=persona.id,
        platform="x",
        content_text="Another bad post.",
        status="REJECTED",
        feedback_notes="Too boring. Avoid questions.",
        updated_at=datetime.now(timezone.utc)
    )
    # 3. Add viral success (top 10%)
    d3 = ContentDraft(
        id="d-viral-success",
        persona_id=persona.id,
        platform="x",
        content_text="Awesome high-performing X post.",
        status="PUBLISHED",
        updated_at=datetime.now(timezone.utc)
    )
    db_session.add_all([d1, d2, d3])
    await db_session.flush()
    
    # Associate high metrics with d3
    pa = PostAnalytics(
        draft_id="d-viral-success",
        likes=1000, # Extremely high
        views=50000,
        last_synced_at=datetime.now(timezone.utc)
    )
    db_session.add(pa)
    await db_session.commit()
    
    analyzer = FeedbackAnalyzer()
    data = await analyzer.gather_feedback_data(db_session, persona.id, "x")
    
    assert len(data["human_corrections"]) == 1
    assert data["human_corrections"][0]["original"] == "Draft post about AI."
    assert data["human_corrections"][0]["edited"] == "Optimized punchy post about AI."
    
    assert len(data["rejections"]) == 1
    assert data["rejections"][0] == "Too boring. Avoid questions."
    
    assert len(data["viral_successes"]) == 1
    assert data["viral_successes"][0]["likes"] == 1000


# ==========================================
# 2. PROMPT OPTIMIZER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_prompt_optimizer_meta_tuning(db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-opt-2",
        name="Opt Persona 2",
        tone_description="Helpful",
        vocabulary_rules="Clear",
        formatting_preferences="Lists"
    )
    db_session.add(persona)
    await db_session.flush()
    
    # Seed a human correction
    d1 = ContentDraft(
        persona_id=persona.id,
        platform="linkedin",
        content_text="Original Text",
        final_content="Improved human edited text",
        status="PUBLISHED",
        updated_at=datetime.now(timezone.utc)
    )
    db_session.add(d1)
    await db_session.commit()
    
    optimizer = PromptOptimizer()
    
    mock_opt_rules = "### Historical Style Adjustments for LINKEDIN:\n- Stop using standard greetings.\n- Always open with a strong query hook."
    
    # Mock LLMProvider call to return rule string
    with patch.object(FallbackLLMProvider, "generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = mock_opt_rules
        
        feedback_rec = await optimizer.optimize_prompt(db_session, persona.id, "linkedin")
        
        assert feedback_rec.persona_id == persona.id
        assert feedback_rec.platform == "linkedin"
        assert feedback_rec.is_active is True
        assert "Historical Style Adjustments for LINKEDIN" in feedback_rec.optimized_system_prompt
        
        # Verify saved in database
        stmt = select(OptimizationFeedback).where(OptimizationFeedback.id == feedback_rec.id)
        res = await db_session.execute(stmt)
        saved = res.scalars().first()
        assert saved is not None
        assert saved.optimized_system_prompt == mock_opt_rules


# ==========================================
# 3. DYNAMIC INJECTION HOOK TESTS
# ==========================================
@pytest.mark.asyncio
async def test_dynamic_prompt_injection(db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-opt-3",
        name="Opt Persona 3",
        tone_description="Friendly",
        vocabulary_rules="Casual",
        formatting_preferences="Short"
    )
    db_session.add(persona)
    
    # Add active optimization prompt rules
    mock_opt_rules = "### Historical Style Adjustments for THREADS:\n- Always end with an open question.\n- Keep sentences under 15 words."
    opt_feedback = OptimizationFeedback(
        persona_id=persona.id,
        platform="threads",
        optimized_system_prompt=mock_opt_rules,
        is_active=True
    )
    db_session.add(opt_feedback)
    await db_session.commit()
    
    # Assert PromptFactory renders system prompt with injection
    factory = PromptFactory()
    sys_prompt = await factory.render_system_prompt("threads", persona, db=db_session)
    
    assert "Friendly" in sys_prompt
    assert "THREADS" in sys_prompt
    assert "Always end with an open question." in sys_prompt
    assert "Keep sentences under 15 words." in sys_prompt


# ==========================================
# 4. API CONTROLLER TESTS
# ==========================================
@pytest.mark.asyncio
async def test_optimization_api_endpoints(api_client: httpx.AsyncClient, db_session: AsyncSession):
    # Setup Persona
    persona = Persona(
        id="p-opt-api",
        name="Opt Persona API",
        tone_description="Educational",
        vocabulary_rules="Precise",
        formatting_preferences="Sections"
    )
    db_session.add(persona)
    
    # Seed a correction to run LLM optimizer
    d1 = ContentDraft(
        persona_id=persona.id,
        platform="substack",
        content_text="Substack text",
        final_content="Substack text with headings",
        status="PUBLISHED",
        updated_at=datetime.now(timezone.utc)
    )
    db_session.add(d1)
    await db_session.commit()
    
    mock_opt_rules = "### Historical Style Adjustments for SUBSTACK:\n- Add headers to all paragraphs."
    
    # 4.1 Test POST /optimization/tune/{persona_id} (scoped to substack)
    with patch.object(FallbackLLMProvider, "generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = mock_opt_rules
        
        resp_tune = await api_client.post(
            f"/api/v1/optimization/tune/{persona.id}",
            json={"platform": "substack"}
        )
        assert resp_tune.status_code == 200
        data_tune = resp_tune.json()
        assert len(data_tune) == 1
        assert data_tune[0]["platform"] == "substack"
        assert data_tune[0]["optimized_system_prompt"] == mock_opt_rules
        assert data_tune[0]["is_active"] is True
        
    # 4.2 Test GET /optimization/history/{persona_id}
    resp_hist = await api_client.get(f"/api/v1/optimization/history/{persona.id}")
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    assert len(data_hist) == 1
    assert data_hist[0]["platform"] == "substack"
    assert data_hist[0]["optimized_system_prompt"] == mock_opt_rules
