"""
pipeline.py
===========
ContentGenerationPipeline — modular, feature-flagged execution pipeline for
autonomous content draft generation.

Stages:
1. Context Initialization & Persona Resolution
2. Strategy & Memory Selection
3. LLM Draft Generation (Gemini primary, Cohere fallback)
4. JSON Structural Repair
5. Content-Preservation Gate
6. Validation Registry
7. Deduplication & Metrics Calculation
8. Image Generation (deterministic prompt + Pollinations AI)
9. Image Quality Gate
10. Database Persistence & Transaction Commit
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
from app.services.generation.image_director import ImageDirector
from app.services.generation.json_repair import JSONRepairStage
from app.services.generation.prompt_builder import PromptBuilder
from app.services.generation.prompt_memory import PromptMemoryService
from app.services.generation.providers import PollinationsImageProvider, ImagenProvider
from app.services.generation.image_quality_gate import ImageQualityGate
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
        self.imagen_provider = ImagenProvider()
        self.linkedin_formatter = LinkedInFormatter()
        self.image_rules_engine = ImageRulesEngine()
        self.image_director = ImageDirector()

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

    @staticmethod
    def _log_stage(stage_name: str, trace_id: str, status: str, detail: str = ""):
        """Emit a structured stage log for production pipeline traceability."""
        logger.info(
            f"[PIPELINE] [{stage_name}] {status}" + (f" — {detail}" if detail else ""),
            extra={"trace_id": trace_id, "stage": stage_name, "status": status, "detail": detail},
        )

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
        self._log_stage("PERSONA_RESOLVE", context.trace_id, "START")
        if context.db and not context.persona:
            context.persona = await self._get_persona(context.db, context.persona_id)
        self._log_stage("PERSONA_RESOLVE", context.trace_id, "SUCCESS", f"persona={context.persona.name if context.persona else 'None'}")

        # 2. System Prompt & Strategy Assembly
        self._log_stage("PROMPT_BUILD", context.trace_id, "START")
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
        self._log_stage("PROMPT_BUILD", context.trace_id, "SUCCESS", f"system={len(system_prompt)} chars, user={len(user_prompt)} chars")

        # 3. LLM Generation (Gemini primary, Cohere fallback)
        self._log_stage("LLM_GENERATE", context.trace_id, "START")
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
            
            # TRACE: Stage 1 Raw Gemini Output
            import hashlib
            s1_hash = hashlib.sha256(stage1_raw.encode('utf-8')).hexdigest()[:8]
            s1_char = len(stage1_raw)
            s1_para = len([p for p in stage1_raw.split('\n\n') if p.strip()])
            logger.info(f"[TRACE] [STAGE 1 RAW] chars={s1_char} | paras={s1_para} | hash={s1_hash} | end={repr(stage1_raw[-50:])}")

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
                        model="command-a",
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

        parsed_data, was_repaired = self.json_repair_stage.repair(stage1_raw)
        self._log_stage("JSON_REPAIR", context.trace_id, "SUCCESS", f"repaired={was_repaired}")
        if was_repaired:
            context.add_warning("JSON structural repair applied to Stage 1 output.")

        generated_text = parsed_data.get("content_text", stage1_raw)
        
        # TRACE: Post JSON Repair
        s15_hash = hashlib.sha256(generated_text.encode('utf-8')).hexdigest()[:8]
        s15_char = len(generated_text)
        s15_para = len([p for p in generated_text.split('\n\n') if p.strip()])
        logger.info(f"[TRACE] [POST JSON REPAIR] chars={s15_char} | paras={s15_para} | hash={s15_hash} | end={repr(generated_text[-50:])}")
        
        # Override dynamic evaluation: hardcode requires_image = True for all pipeline executions
        context.requires_image = True
        llm_output_metadata = parsed_data.get("metadata", {})
        if not isinstance(llm_output_metadata, dict):
            llm_output_metadata = {}

        # P2: Wrap LLM image idea using Image Director
        if context.requires_image:
            context.image_prompt = await self.image_director.generate_prompt(
                core_topic=context.topic
            )
        else:
            context.image_prompt = None

        # Stage 2 removed: Cohere is now only used as a Stage 1 fallback.
        # generated_text goes directly to formatting — no second LLM rewrite.

        # Format LinkedIn spacing
        self._log_stage("FORMAT", context.trace_id, "START")
        formatted_text = self.linkedin_formatter.format(generated_text)
        crushed_text = re.sub(r'(?:\r?\n\s*){2,}', '\n\n', formatted_text).strip()
        context.refined_text = crushed_text
        
        # TRACE: LinkedIn Formatter
        s3_hash = hashlib.sha256(crushed_text.encode('utf-8')).hexdigest()[:8]
        s3_char = len(crushed_text)
        s3_para = len([p for p in crushed_text.split('\n\n') if p.strip()])
        logger.info(f"[TRACE] [LINKEDIN FORMATTER] chars={s3_char} | paras={s3_para} | hash={s3_hash} | end={repr(crushed_text[-50:])}")

        # P3: Content-Preservation Gate
        # Ensures no stage silently destroys content during formatting.
        pre_format_len = len(generated_text)
        post_format_len = len(crushed_text)
        pre_format_paras = len([p for p in generated_text.split('\n\n') if p.strip()])
        post_format_paras = len([p for p in crushed_text.split('\n\n') if p.strip()])

        if pre_format_len > 0 and post_format_len < (pre_format_len * 0.5):
            logger.error(
                f"[CONTENT PRESERVATION FAILED] Formatter reduced content from "
                f"{pre_format_len} to {post_format_len} chars ({post_format_len/pre_format_len:.0%})"
            )
            raise RuntimeError(
                f"Content preservation failed: formatter reduced text by more than 50% "
                f"({pre_format_len} → {post_format_len} chars)"
            )

        if pre_format_paras > 2 and post_format_paras < (pre_format_paras * 0.5):
            logger.error(
                f"[CONTENT PRESERVATION FAILED] Formatter reduced paragraphs from "
                f"{pre_format_paras} to {post_format_paras}"
            )
            raise RuntimeError(
                f"Content preservation failed: formatter lost more than 50% of paragraphs "
                f"({pre_format_paras} → {post_format_paras})"
            )

        logger.info(
            f"[CONTENT GATE PASSED] {pre_format_len}→{post_format_len} chars, "
            f"{pre_format_paras}→{post_format_paras} paras"
        )

        # Explicit Runtime Assertion: Draft Length
        if not (0 < len(context.refined_text) <= 3000):
            logger.error(f"[ASSERTION FAILED] Draft length is {len(context.refined_text)} characters, exceeding LinkedIn limit.")
            raise RuntimeError(f"Draft length validation failed: generated {len(context.refined_text)} characters. Expected 1-3000.")

        self._log_stage("CONTENT_GATE", context.trace_id, "SUCCESS", f"{pre_format_len}→{post_format_len} chars, {pre_format_paras}→{post_format_paras} paras")

        # 6. Validation Registry Stage
        self._log_stage("VALIDATE", context.trace_id, "START")
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
        self._log_stage("VALIDATE", context.trace_id, "SUCCESS", f"errors={len(context.errors)}, warnings={len(context.warnings)}")

        # 7. Deduplication & Content Metrics Stage
        self._log_stage("DEDUP", context.trace_id, "START")
        metrics = self.dedup_stage.calculate_metrics(context.refined_text)
        if settings.ENABLE_DEDUP and context.db:
            is_dup, sim_score, match_snippet = await self.dedup_stage.check_duplicate(
                new_text=context.refined_text,
                db=context.db,
            )
            if is_dup:
                context.add_warning(f"High content similarity ({sim_score:.2f}) with past post.")
                logger.warning(f"[ASSERTION WARNING] Content deduplication flagged similarity score {sim_score:.2f}")
        self._log_stage("DEDUP", context.trace_id, "SUCCESS")

        # 8. Image Generation Stage (if required or configured)
        self._log_stage("IMAGE_GEN", context.trace_id, "START", f"requires_image={context.requires_image}")
        if context.requires_image and context.image_prompt:
            img_start = time.time()
            try:
                # Primary: Google Imagen 3
                logger.info(f"[IMAGE GENERATION PROMPT] Sending prompt to provider: {context.image_prompt}")
                logger.info(f"[IMAGE_GEN] Attempting Imagen 3 generation for: {context.image_prompt[:50]}...")
                img_url = await self.imagen_provider.generate_image(context.image_prompt)
                
                # Secondary Fallback: Pollinations (FLUX)
                if not img_url:
                    logger.warning("[IMAGE FALLBACK] Imagen provider returned None or timed out. Falling back to Pollinations (FLUX).")
                    img_url = await self.image_provider.generate_image(context.image_prompt)
                
                # Tertiary Fallback: Text-Only
                if not img_url:
                    logger.warning("[IMAGE FALLBACK: Text-Only Mode] Both Imagen and Pollinations returned no URL. Degrading to text-only.")
                    context.image_url = None
                    context.requires_image = False
                else:
                    # P4: Image Quality Gate
                    is_valid, reason = ImageQualityGate.validate(img_url)
                    if is_valid:
                        context.image_url = img_url
                    else:
                        logger.warning(f"[IMAGE FALLBACK: Text-Only Mode] Image Quality Gate Rejected: {reason}. Falling back to text-only.")
                        context.image_url = None
                        context.requires_image = False
            except Exception as e:
                logger.warning(f"[IMAGE FALLBACK: Text-Only Mode] Image generation pipeline threw unexpected error: {e}. Proceeding to publish as standard text-only payload.")
                context.image_url = None
                context.requires_image = False
            context.telemetry.image_generation_latency_ms = round((time.time() - img_start) * 1000, 2)
        self._log_stage("IMAGE_GEN", context.trace_id, "SUCCESS", f"has_image={context.image_url is not None}")

        # 9. Store ContentDraft in Database
        self._log_stage("DB_PERSIST", context.trace_id, "START")
        context.telemetry.finish()

        llm_metadata = {
            "trace_id": context.trace_id,
            "model": "gemini-3.5-flash" if not context.telemetry.fallback_provider_used else f"cohere (fallback)",
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

        if context.draft:
            draft = context.draft
            draft.persona_id = context.persona.id if context.persona else None
            draft.content_text = context.refined_text
            draft.status = "DRAFT"
            draft.generated_at = datetime.now(timezone.utc)
            draft.llm_metadata = llm_metadata
        else:
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
            if not context.draft:
                context.db.add(draft)
            if commit_db:
                await context.db.commit()
            else:
                await context.db.flush()
            await context.db.refresh(draft)
            context.telemetry.db_latency_ms = round((time.time() - db_start) * 1000, 2)

        context.draft = draft
        self._log_stage("DB_PERSIST", context.trace_id, "SUCCESS", f"draft_id={draft.id if draft else None}")
        logger.info(
            f"[PIPELINE RUN COMPLETE] Trace: {context.trace_id}, Draft ID: {draft.id if draft else None}, "
            f"Duration: {context.telemetry.total_duration_ms}ms"
        )
        return draft
