"""
Tests — LinkedIn Agent Skills
================================
Covers:
  1. TextHumanizer — all three passes (lexicon, typography, fingerprint)
  2. generate_outbound_comment — system prompt / LLM call forwarding
  3. generate_thread_reply      — same pattern
  4. POST /api/v1/skills/humanize  — HTTP round-trip (no LLM needed)
  5. POST /api/v1/skills/comment   — HTTP round-trip with mocked LLM
  6. POST /api/v1/skills/reply     — HTTP round-trip with mocked LLM
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


# ──────────────────────────────────────────────────────────────────────────────
# 1. TextHumanizer — unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestTextHumanizerLexiconPurge:
    """Pass 1 — AI buzzword replacement."""

    def setup_method(self):
        from app.services.generation.skills.humanizer import TextHumanizer
        self.h = TextHumanizer

    def test_delve_replaced(self):
        result = self.h.process("We need to delve into the data.")
        assert "delve" not in result.lower()
        assert "explore" in result.lower()

    def test_leverage_replaced(self):
        result = self.h.process("We should leverage our platform.")
        assert "leverage" not in result.lower()
        assert "use" in result.lower()

    def test_robust_replaced(self):
        result = self.h.process("This is a robust system.")
        assert "robust" not in result.lower()
        assert "strong" in result.lower()

    def test_seamless_replaced(self):
        result = self.h.process("It provides a seamless experience.")
        assert "seamless" not in result.lower()
        assert "smooth" in result.lower()

    def test_testament_to_replaced(self):
        result = self.h.process("This is a testament to our hard work.")
        assert "testament to" not in result.lower()
        assert "proof of" in result.lower()

    def test_in_todays_fast_paced_world_removed(self):
        result = self.h.process(
            "In today's fast-paced world, data is everything."
        )
        assert "in today's fast-paced world" not in result.lower()

    def test_case_insensitive_match(self):
        result = self.h.process("We must LEVERAGE every opportunity.")
        assert "LEVERAGE" not in result
        assert "use" in result.lower()

    def test_multiple_replacements_in_one_string(self):
        text = "We need to leverage robust tools to delve into the paradigm shift."
        result = self.h.process(text)
        assert "leverage" not in result.lower()
        assert "robust" not in result.lower()
        assert "delve" not in result.lower()

    def test_no_double_spaces_after_empty_replacement(self):
        text = "In today's fast-paced world, AI is everywhere."
        result = self.h.process(text)
        assert "  " not in result

    def test_empty_string_passthrough(self):
        assert self.h.process("") == ""

    def test_clean_text_unchanged(self):
        text = "Here is a concise, specific data-driven observation."
        result = self.h.process(text)
        # Core meaning preserved — should still contain key words
        assert "concise" in result
        assert "specific" in result
        assert "observation" in result


class TestTextHumanizerTypography:
    """Pass 2 — em-dash and curly quote normalisation."""

    def setup_method(self):
        from app.services.generation.skills.humanizer import TextHumanizer
        self.h = TextHumanizer

    def test_em_dash_replaced_with_comma(self):
        result = self.h.process("Python is fast—surprisingly fast.")
        assert "—" not in result
        assert "," in result

    def test_en_dash_replaced(self):
        result = self.h.process("See pages 10–20.")
        assert "–" not in result

    def test_left_single_curly_quote_normalised(self):
        result = self.h.process("\u2018Hello\u2019")
        assert "\u2018" not in result
        assert "\u2019" not in result
        assert "'" in result

    def test_left_double_curly_quote_normalised(self):
        result = self.h.process('\u201cHello world\u201d')
        assert "\u201c" not in result
        assert "\u201d" not in result
        assert '"' in result


class TestTextHumanizerFingerprintErase:
    """Pass 3 — invisible Unicode character removal."""

    def setup_method(self):
        from app.services.generation.skills.humanizer import TextHumanizer
        self.h = TextHumanizer

    def test_zero_width_space_stripped(self):
        text = "Hello\u200bworld"
        result = self.h.process(text)
        assert "\u200b" not in result
        assert "Helloworld" in result

    def test_word_joiner_stripped(self):
        text = "Hello\u2060world"
        result = self.h.process(text)
        assert "\u2060" not in result

    def test_bom_stripped(self):
        text = "\ufeffThis is content."
        result = self.h.process(text)
        assert "\ufeff" not in result
        assert result.startswith("This")

    def test_multiple_invisible_chars_stripped(self):
        text = "A\u200bB\u2060C\ufeffD"
        result = self.h.process(text)
        assert result == "ABCD"


# ──────────────────────────────────────────────────────────────────────────────
# 2. generate_outbound_comment — unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateOutboundComment:
    """Verify correct prompt forwarding without calling a real LLM."""

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.commenter.FallbackLLMProvider")
    async def test_returns_llm_output(self, MockProvider):
        mock_instance = AsyncMock()
        mock_instance.generate = AsyncMock(
            return_value="  Actually, the p99 latency here often tells a different story than mean.  "
        )
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.commenter import generate_outbound_comment
        result = await generate_outbound_comment("Great insights on database tuning!")
        assert "p99 latency" in result
        # Verify leading/trailing whitespace is stripped
        assert result == result.strip()

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.commenter.FallbackLLMProvider")
    async def test_system_prompt_contains_persona(self, MockProvider):
        captured_kwargs: dict = {}

        async def capture(**kwargs):
            captured_kwargs.update(kwargs)
            return "A comment."

        mock_instance = MagicMock()
        mock_instance.generate = AsyncMock(side_effect=capture)
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.commenter import generate_outbound_comment
        await generate_outbound_comment("Some post text.", comment_type="data")

        system_instruction = captured_kwargs.get("system_instruction", "")
        assert "Senior Data Analyst" in system_instruction
        assert "Great post" in system_instruction  # The prohibition must be in the prompt
        assert "data" in system_instruction.lower()

    @pytest.mark.asyncio
    async def test_raises_on_empty_post_text(self):
        from app.services.generation.skills.commenter import generate_outbound_comment
        with pytest.raises(ValueError, match="must not be empty"):
            await generate_outbound_comment("")

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.commenter.FallbackLLMProvider")
    async def test_invalid_comment_type_falls_back_to_contrarian(self, MockProvider):
        mock_instance = AsyncMock()
        mock_instance.generate = AsyncMock(return_value="Thoughtful pushback.")
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.commenter import generate_outbound_comment
        # Should NOT raise — falls back gracefully
        result = await generate_outbound_comment("Post text.", comment_type="INVALID_TYPE")
        assert result == "Thoughtful pushback."


# ──────────────────────────────────────────────────────────────────────────────
# 3. generate_thread_reply — unit tests
# ──────────────────────────────────────────────────────────────────────────────

class TestGenerateThreadReply:

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.replier.FallbackLLMProvider")
    async def test_returns_llm_output(self, MockProvider):
        mock_instance = AsyncMock()
        mock_instance.generate = AsyncMock(return_value="  Great question — the answer is...")
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.replier import generate_thread_reply
        result = await generate_thread_reply("Post about caching.", "How does LRU differ from LFU?")
        assert result == "Great question — the answer is..."

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.replier.FallbackLLMProvider")
    async def test_noise_comment_returns_skip_literal(self, MockProvider):
        mock_instance = AsyncMock()
        mock_instance.generate = AsyncMock(return_value="[SKIP]")
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.replier import generate_thread_reply
        result = await generate_thread_reply("Post text.", "Buy cheap followers now!")
        assert result == "[SKIP]"

    @pytest.mark.asyncio
    @patch("app.services.generation.skills.replier.FallbackLLMProvider")
    async def test_system_prompt_contains_categories(self, MockProvider):
        captured_kwargs: dict = {}

        async def capture(**kwargs):
            captured_kwargs.update(kwargs)
            return "Thank you!"

        mock_instance = MagicMock()
        mock_instance.generate = AsyncMock(side_effect=capture)
        MockProvider.return_value = mock_instance

        from app.services.generation.skills.replier import generate_thread_reply
        await generate_thread_reply("Post text.", "Love this content!")

        system_instruction = captured_kwargs.get("system_instruction", "")
        for category in ("Substance", "Peer", "Support", "Noise"):
            assert category in system_instruction

    @pytest.mark.asyncio
    async def test_raises_on_empty_original_post(self):
        from app.services.generation.skills.replier import generate_thread_reply
        with pytest.raises(ValueError, match="must not be empty"):
            await generate_thread_reply("", "A comment.")

    @pytest.mark.asyncio
    async def test_raises_on_empty_user_comment(self):
        from app.services.generation.skills.replier import generate_thread_reply
        with pytest.raises(ValueError, match="must not be empty"):
            await generate_thread_reply("A post.", "")


# ──────────────────────────────────────────────────────────────────────────────
# 4-6. HTTP endpoint tests (via ASGI transport)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skills_humanize_endpoint_no_llm():
    """POST /api/v1/skills/humanize — deterministic, no LLM needed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/humanize",
            json={"text": "We need to leverage robust, seamless solutions to delve into the data."},
        )

    assert response.status_code == 200
    data = response.json()
    assert "humanized_text" in data
    assert "leverage" not in data["humanized_text"].lower()
    assert "robust" not in data["humanized_text"].lower()
    assert "seamless" not in data["humanized_text"].lower()
    assert "delve" not in data["humanized_text"].lower()
    assert data["original_length"] > 0
    assert data["humanized_length"] > 0


@pytest.mark.asyncio
async def test_skills_humanize_endpoint_fingerprint_erase():
    """POST /api/v1/skills/humanize — invisible chars should be stripped."""
    text_with_zwsp = "Hello\u200bworld\u2060."
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/humanize",
            json={"text": text_with_zwsp},
        )

    assert response.status_code == 200
    data = response.json()
    assert "\u200b" not in data["humanized_text"]
    assert "\u2060" not in data["humanized_text"]


@pytest.mark.asyncio
async def test_skills_humanize_endpoint_empty_text_rejected():
    """POST /api/v1/skills/humanize — empty string should return 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/humanize",
            json={"text": ""},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
@patch(
    "app.services.generation.skills.commenter.FallbackLLMProvider",
)
async def test_skills_comment_endpoint(MockProvider):
    """POST /api/v1/skills/comment — mocked LLM, verifies response shape."""
    mock_instance = AsyncMock()
    mock_instance.generate = AsyncMock(
        return_value="In practice, the write amplification factor here can easily exceed 3x on SSDs."
    )
    MockProvider.return_value = mock_instance

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/comment",
            json={
                "post_text": "Using LSM trees in your database will dramatically speed up writes.",
                "comment_type": "contrarian",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "comment" in data
    assert "comment_type" in data
    assert data["comment_type"] == "contrarian"
    assert len(data["comment"]) > 0


@pytest.mark.asyncio
@patch(
    "app.services.generation.skills.commenter.FallbackLLMProvider",
)
async def test_skills_comment_endpoint_default_type(MockProvider):
    """POST /api/v1/skills/comment — omitting comment_type defaults to 'contrarian'."""
    mock_instance = AsyncMock()
    mock_instance.generate = AsyncMock(return_value="An additive observation.")
    MockProvider.return_value = mock_instance

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/comment",
            json={"post_text": "A long enough post about software architecture."},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["comment_type"] == "contrarian"


@pytest.mark.asyncio
@patch(
    "app.services.generation.skills.replier.FallbackLLMProvider",
)
async def test_skills_reply_endpoint(MockProvider):
    """POST /api/v1/skills/reply — mocked LLM, verifies response shape."""
    mock_instance = AsyncMock()
    mock_instance.generate = AsyncMock(
        return_value="LRU evicts the least-recently used entry; LFU tracks access frequency and evicts the least-frequently accessed, which is better for skewed distributions."
    )
    MockProvider.return_value = mock_instance

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/reply",
            json={
                "original_post": "Caching is one of the hardest problems in distributed systems.",
                "user_comment": "Can you explain the difference between LRU and LFU eviction policies?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert "is_skip" in data
    assert data["is_skip"] is False
    assert len(data["reply"]) > 0


@pytest.mark.asyncio
@patch(
    "app.services.generation.skills.replier.FallbackLLMProvider",
)
async def test_skills_reply_endpoint_skip_flag(MockProvider):
    """POST /api/v1/skills/reply — is_skip=True when LLM returns '[SKIP]'."""
    mock_instance = AsyncMock()
    mock_instance.generate = AsyncMock(return_value="[SKIP]")
    MockProvider.return_value = mock_instance

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/reply",
            json={
                "original_post": "Any post about data science.",
                "user_comment": "Buy followers at discount! Visit spammy.site",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "[SKIP]"
    assert data["is_skip"] is True


@pytest.mark.asyncio
async def test_skills_reply_endpoint_empty_post_rejected():
    """POST /api/v1/skills/reply — empty original_post returns 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/reply",
            json={"original_post": "", "user_comment": "A comment."},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_skills_routes_do_not_break_existing_health_route():
    """Regression — existing /api/v1/health must still work after skills router is added."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
