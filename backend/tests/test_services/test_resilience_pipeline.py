"""
test_resilience_pipeline.py
============================
Unit & Integration tests for CircuitBreaker, JSONRepairStage, ValidatorRegistry,
ContentDeduplicationStage, and PipelineContext.
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.generation.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenException,
    CircuitState,
    execute_with_retry,
    is_retriable_error,
)
from app.services.generation.context import PipelineContext, TelemetryData
from app.services.generation.deduplication import ContentDeduplicationStage
from app.services.generation.json_repair import JSONRepairStage
from app.services.generation.validators import (
    BannedWordValidator,
    ImageValidator,
    LengthValidator,
    LinkValidator,
    ValidationResult,
    ValidatorRegistry,
)


# ==========================================
# 1. CIRCUIT BREAKER TESTS
# ==========================================
class TestCircuitBreaker:

    def test_circuit_breaker_initial_state_closed(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=3, recovery_time_seconds=1.0)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_circuit_breaker_trips_to_open(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=2, recovery_time_seconds=60.0)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_circuit_breaker_transitions_to_half_open_after_recovery(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=1, recovery_time_seconds=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_resets_to_closed(self):
        cb = CircuitBreaker(provider_name="test", failure_threshold=1, recovery_time_seconds=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.allow_request()  # transitions to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


# ==========================================
# 2. RETRY POLICY TESTS
# ==========================================
class TestRetryPolicy:

    def test_is_retriable_error_identification(self):
        assert is_retriable_error(Exception("429 Too Many Requests")) is True
        assert is_retriable_error(Exception("503 Service Unavailable")) is True
        assert is_retriable_error(Exception("Connection timed out")) is True

        assert is_retriable_error(Exception("401 Unauthorized")) is False
        assert is_retriable_error(Exception("400 Bad Request")) is False

    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self):
        async_func = AsyncMock(return_value="Success")
        res = await execute_with_retry(async_func, max_retries=2, initial_backoff=0.01)
        assert res == "Success"
        assert async_func.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_with_retry_retries_on_429(self):
        async_func = AsyncMock(side_effect=[Exception("429 Rate Limit"), "Success"])
        res = await execute_with_retry(async_func, max_retries=2, initial_backoff=0.01)
        assert res == "Success"
        assert async_func.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_with_retry_fails_fast_on_401(self):
        async_func = AsyncMock(side_effect=Exception("401 Unauthorized"))
        with pytest.raises(Exception, match="401 Unauthorized"):
            await execute_with_retry(async_func, max_retries=3, initial_backoff=0.01)
        assert async_func.call_count == 1


# ==========================================
# 3. JSON REPAIR STAGE TESTS
# ==========================================
class TestJSONRepairStage:

    def test_clean_json_parsed_unchanged(self):
        raw = '{"content_text": "Hello", "requires_image": true}'
        parsed, was_repaired = JSONRepairStage.repair(raw)
        assert parsed["content_text"] == "Hello"
        assert was_repaired is False

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"content_text\": \"Code text\", \"requires_image\": true}\n```"
        parsed, was_repaired = JSONRepairStage.repair(raw)
        assert parsed["content_text"] == "Code text"
        assert parsed["requires_image"] is True
        assert was_repaired is True

    def test_fallback_regex_extraction(self):
        raw = 'Random prefix\n"content_text": "Extracted text via regex", "requires_image": true, "image_prompt": "cinematic sunset"'
        parsed, was_repaired = JSONRepairStage.repair(raw)
        assert parsed["content_text"] == "Extracted text via regex"
        assert parsed["requires_image"] is True
        assert parsed["image_prompt"] == "cinematic sunset"


# ==========================================
# 4. VALIDATOR REGISTRY TESTS
# ==========================================
class TestValidatorRegistry:

    def test_banned_word_validator_flags_cliche(self):
        validator = BannedWordValidator()
        result = ValidationResult(is_valid=True)
        validator.validate("We must delve into AI innovation.", result)
        assert result.is_valid is False
        assert any("delve" in err for err in result.errors)

    def test_length_validator_flags_exceeding_max(self):
        validator = LengthValidator(max_length=50)
        result = ValidationResult(is_valid=True)
        validator.validate("A" * 60, result)
        assert result.is_valid is False

    def test_link_validator_flags_fake_shorteners(self):
        validator = LinkValidator()
        result = ValidationResult(is_valid=True)
        validator.validate("Check out http://lnkd.in/fake123", result)
        assert result.is_valid is False

    def test_registry_aggregates_validations(self):
        registry = ValidatorRegistry()
        result = registry.validate(
            content_text="Clean technical breakdown of Python async queues.",
            requires_image=True,
            image_prompt="A glowing fiber optic mountain",
        )
        assert result.is_valid is True
        assert len(result.errors) == 0


# ==========================================
# 5. DEDUPLICATION & METRICS TESTS
# ==========================================
class TestDeduplication:

    def test_calculate_metrics(self):
        metrics = ContentDeduplicationStage.calculate_metrics(
            "Building Python pipelines with FastAPI. Achieving 99.9% uptime! 🚀"
        )
        assert metrics.character_count > 0
        assert metrics.word_count > 0
        assert metrics.has_metric is True
        assert metrics.has_tool_name is True

    def test_jaccard_similarity(self):
        t1 = "Building Python pipelines with FastAPI and Docker."
        t2 = "Building Python pipelines with FastAPI and Docker."
        t3 = "Completely different topic about sports photography."

        sim_identical = ContentDeduplicationStage.jaccard_similarity(t1, t2)
        sim_different = ContentDeduplicationStage.jaccard_similarity(t1, t3)

        assert sim_identical == 1.0
        assert sim_different < 0.2


# ==========================================
# 6. PIPELINE CONTEXT TESTS
# ==========================================
class TestPipelineContext:

    def test_pipeline_context_creation(self):
        ctx = PipelineContext(topic="AI Agents")
        assert ctx.trace_id is not None
        assert ctx.topic == "AI Agents"

        ctx.add_error("Error 1")
        ctx.add_warning("Warning 1")
        assert len(ctx.errors) == 1
        assert len(ctx.warnings) == 1

        tel = TelemetryData()
        dur = tel.finish()
        assert dur >= 0
