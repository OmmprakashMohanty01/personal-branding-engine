"""
pipeline.py
===========
ContentGenerationPipeline — modular, feature-flagged execution pipeline for
autonomous content draft generation.

Stages:
1. Context Initialization & Persona Resolution
2. Strategy & Memory Selection
3. Stage 1 Draft Generation (Gemini 3.5 Flash)
4. JSON Structural Repair
5. Stage 2 Tone Editing (Cohere Command A+)
6. Validation Registry
7. Deduplication & Metrics Calculation
8. Image Generation (Pollinations AI)
9. Database Persistence & Transaction Commit
"""

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.content import ContentDraft, Persona
from app.services.generation.author_knowledge import AuthorKnowledgeService
from app.services.generation.circuit_breaker import CircuitBreaker, execute_with_retry
from app.services.generation.context import PipelineContext
from app.services.generation.deduplication import ContentDeduplicationStage
from app.services.generation.formatters import LinkedInFormatter
from app.services.generation.image_rules import ImageRulesEngine
from app.services.generation.json_repair import JSONRepairStage
from app.services.generation.prompt_builder import PromptBuilder
from app.services.generation.prompt_memory import PromptMemoryService
from app.services.generation.providers import PollinationsImageProvider
from app.services.generation.strategy_selector import StrategySelector
from app.services.generation.validators import ValidatorRegistry
from app.services.generation.writing_dna import WritingDNAEngine

logger = logging.getLogger("branding_engine.generation.pipeline")


class ContentGenerationPipeline:
    """Orchestrates modular stages for content generation with feature flags and resilience."""

    def __init__(self):
        self.prompt_builder = PromptBuilder()
        self.strategy_selector = StrategySelector()
        self.json_repair_stage = JSONRepairStage()
        self.validator_registry = ValidatorRegistry()
        self.dedup_stage = ContentDeduplicationStage()
        self.image_provider = PollinationsImageProvider()
        self.linkedin_formatter = LinkedInFormatter()

        self.gemini_api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        self.cohere_api_key = settings.COHERE_API_KEY or os.getenv("COHERE_API_KEY")

        self.gemini_breaker = CircuitBreaker(provider_name="gemini")
        self.cohere_breaker = CircuitBreaker(provider_name="cohere")

    async def _get_persona(self, db: AsyncSession, persona_id: Optional[str]) -> Persona:
        """Resolve requested persona or return default persona."""
        if persona_id:
            stmt = select(Persona).where(Persona.id == persona_id)
            res = await db.execute(stmt)
            persona = res.scalars().first()
            if persona:
                return persona

        stmt = select(Persona).where(Persona.is_default == True)
        res = await db.execute(stmt)
        persona = res.scalars().first()

        if not persona:
            persona = Persona(
                name="CS Graduate Tech Brand",
                tone_description="Professional, enthusiastic, tech-savvy, educational, startup-minded.",
                vocabulary_rules="Avoid buzzwords, use clear terminology, emphasize open source, Python, automation.",
                formatting_preferences="Clean spacing, list highlights, max 1 link.",
                is_default=True,
            )
            db.add(persona)
            await db.flush()

        return persona

    async def run(self, context: PipelineContext, commit_db: bool = True) -> ContentDraft:
        """Run all generation pipeline stages sequentially using the provided context.

        Args:
            context: PipelineContext object.
            commit_db: If True, commit the transaction at the end. If False, just flush.

        Returns:
            Saved ContentDraft database instance.

        Raises:
            RuntimeError: If EMERGENCY_STOP is enabled or critical generation fails.
        """
        # 0. Emergency Stop Guard
        if settings.EMERGENCY_STOP:
            logger.critical(f"[EMERGENCY STOP ENABLED] Halting pipeline execution for trace {context.trace_id}.")
            raise RuntimeError("Pipeline execution halted globally by EMERGENCY_STOP feature flag.")

        logger.info(
            f"[PIPELINE RUN START] Trace: {context.trace_id}, Topic: '{context.topic}'",
            extra={"trace_id": context.trace_id, "topic": context.topic},
        )

        # 1. Resolve Persona
        if context.db and not context.persona:
            context.persona = await self._get_persona(context.db, context.persona_id)

        # 2. System Prompt & Strategy Assembly
        system_prompt = await self.prompt_builder.build_system_prompt(
            persona=context.persona,
            topic=context.topic,
            db=context.db if settings.ENABLE_MEMORY else None,
        )
        user_prompt = self.prompt_builder.build_user_prompt(
            topic=context.topic,
            feedback=context.feedback,
        )
        pipeline_metadata = self.prompt_builder.get_generation_metadata()

        # 3. Stage 1 LLM Generation (Gemini 3.5 Flash)
        p_start = time.time()
        stage1_raw = ""
        stage_1_prompt = f"{system_prompt}\n\nUser Input/Topic: {user_prompt}"

        def inc_retry(attempt: int):
            context.telemetry.retry_count += 1

        async def call_gemini():
            import asyncio
            from google import genai
            gemini_key = self.gemini_api_key or "mock_gemini_key"
            client = genai.Client(api_key=gemini_key)
            
            def _sync_call():
                return client.interactions.create(
                    model="gemini-3.5-flash",
                    input=stage_1_prompt,
                )
            return await asyncio.to_thread(_sync_call)

        try:
            interaction = await execute_with_retry(
                call_gemini,
                circuit_breaker=self.gemini_breaker,
                max_retries=2,
                on_retry=inc_retry
            )
            stage1_raw = interaction.output_text
            context.telemetry.provider_latency_ms = round((time.time() - p_start) * 1000, 2)
            logger.info(f"[STAGE 1 - Gemini] Generated raw draft in {context.telemetry.provider_latency_ms}ms")

        except Exception as exc:
            error_str = str(exc).lower()
            if "high demand" in error_str or "capacity" in error_str:
                logger.warning(f"[STAGE 1 FALLBACK] Gemini capacity error: {exc}. Attempting Cohere fallback.")
            else:
                logger.warning(f"[STAGE 1 FALLBACK] Gemini primary error: {exc}. Attempting Cohere fallback.")
            context.telemetry.fallback_provider_used = "cohere"
            try:
                import cohere

                async def call_cohere():
                    cohere_key = self.cohere_api_key or "mock_cohere_key"
                    co = cohere.AsyncClientV2(api_key=cohere_key)
                    return await co.chat(
                        model="command-a-plus-05-2026",
                        messages=[{"role": "user", "content": stage_1_prompt}],
                    )
                
                resp = await execute_with_retry(
                    call_cohere,
                    circuit_breaker=self.cohere_breaker,
                    max_retries=2,
                    on_retry=inc_retry
                )
                stage1_raw = next(
                    (block.text for block in resp.message.content if hasattr(block, "text") and block.text),
                    "",
                ) if (resp.message and resp.message.content) else ""
            except Exception as cohere_err:
                logger.error(f"Stage 1 Cohere fallback also failed: {cohere_err}")
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=503,
                    detail="All AI providers are temporarily unavailable. Please try again later."
                )

        # 4. JSON Repair Stage
        parsed_data, was_repaired = self.json_repair_stage.repair(stage1_raw)
        if was_repaired:
            context.add_warning("JSON structural repair applied to Stage 1 output.")

        generated_text = parsed_data.get("content_text", stage1_raw)
        context.requires_image = parsed_data.get("requires_image", False)
        context.image_prompt = parsed_data.get("image_prompt")
        llm_output_metadata = parsed_data.get("metadata", {})
        if not isinstance(llm_output_metadata, dict):
            llm_output_metadata = {}

        # 5. Stage 2 LLM Tone Refinement (Cohere Command A+)
        final_text = generated_text
        try:
            import cohere

            async def call_cohere_refine():
                cohere_key = self.cohere_api_key or "mock_cohere_key"
                co = cohere.AsyncClientV2(api_key=cohere_key)
                cohere_system = self.prompt_builder.build_cohere_prompt()

                return await co.chat(
                    model="command-a-plus-05-2026",
                    messages=[
                        {"role": "system", "content": cohere_system},
                        {"role": "user", "content": generated_text},
                    ],
                )

            resp = await execute_with_retry(
                call_cohere_refine,
                circuit_breaker=self.cohere_breaker,
                max_retries=2,
                on_retry=inc_retry
            )
            final_text = next(
                (block.text for block in resp.message.content if hasattr(block, "text") and block.text),
                "",
            ) if (resp.message and resp.message.content) else ""
        except Exception as cohere_err:
            logger.warning(f"[STAGE 2 FALLBACK] Cohere tone editing skipped: {cohere_err}")
            final_text = generated_text

        # Format LinkedIn spacing
        formatted_text = self.linkedin_formatter.format(final_text)
        crushed_text = re.sub(r'(?:\r?\n\s*){2,}', '\n\n', formatted_text).strip()
        context.refined_text = crushed_text

        # 6. Validation Registry Stage
        if settings.ENABLE_VALIDATION:
            val_result = self.validator_registry.validate(
                content_text=context.refined_text,
                requires_image=context.requires_image,
                image_prompt=context.image_prompt or "",
                author_context=self.prompt_builder._last_author_context,
            )
            for err in val_result.errors:
                context.add_error(err)
            for warn in val_result.warnings:
                context.add_warning(warn)

        # 7. Deduplication & Content Metrics Stage
        metrics = self.dedup_stage.calculate_metrics(context.refined_text)
        if settings.ENABLE_DEDUP and context.db:
            is_dup, sim_score, match_snippet = await self.dedup_stage.check_duplicate(
                new_text=context.refined_text,
                db=context.db,
            )
            if is_dup:
                context.add_warning(f"High content similarity ({sim_score:.2f}) with past post.")

        # 8. Image Generation Stage (if required or configured)
        if context.requires_image and context.image_prompt:
            img_start = time.time()
            img_url = await self.image_provider.generate_image(context.image_prompt)
            context.image_url = img_url
            context.telemetry.image_generation_latency_ms = round((time.time() - img_start) * 1000, 2)

        # 9. Store ContentDraft in Database
        context.telemetry.finish()

        llm_metadata = {
            "trace_id": context.trace_id,
            "model": "gemini-3.5-flash & cohere",
            "prompt_length": len(user_prompt) + len(system_prompt),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requires_image": context.requires_image,
            "image_prompt": context.image_prompt,
            "image_url": context.image_url,
            "topic": context.topic,
            "metrics": metrics.to_dict(),
            "telemetry": context.telemetry.to_dict(),
            "llm_output_metadata": llm_output_metadata,
        }
        llm_metadata.update(pipeline_metadata)

        draft = ContentDraft(
            persona_id=context.persona.id if context.persona else None,
            platform="linkedin",
            content_text=context.refined_text,
            status="DRAFT",
            generated_at=datetime.now(timezone.utc),
            llm_metadata=llm_metadata,
        )

        if context.db:
            db_start = time.time()
            context.db.add(draft)
            if commit_db:
                await context.db.commit()
            else:
                await context.db.flush()
            await context.db.refresh(draft)
            context.telemetry.db_latency_ms = round((time.time() - db_start) * 1000, 2)

        context.draft = draft
        logger.info(
            f"[PIPELINE RUN COMPLETE] Trace: {context.trace_id}, Draft ID: {draft.id if draft else None}, "
            f"Duration: {context.telemetry.total_duration_ms}ms"
        )
        return draft
