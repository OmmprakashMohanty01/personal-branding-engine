"""
pipeline.py
===========
ContentGenerationPipeline — single-pass LiteLLM generation pipeline.

Replaces the two-stage (raw log → compiler) cognitive pipeline with a single
unified LiteLLM call that produces structured JSON. Provider fallback is
handled by cascading through the PROVIDER_CHAIN. Lexical enforcement is
deterministic Python string cleanup (no LLM retry loop).

Stages:
1. Context Initialization & Persona Resolution
2. Strategy & Memory Selection
3. Single-Pass LiteLLM Generation (Gemini → Groq 70B → Groq 8B)
4. Deterministic Lexical Cleanup
5. JSON Structural Repair
6. Content-Preservation Gate
7. Validation Registry
8. Deduplication & Metrics Calculation
9. Database Persistence & Transaction Commit
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import litellm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.models.content import ContentDraft, Persona
from app.services.generation.context import PipelineContext
from app.services.generation.deduplication import ContentDeduplicationStage
from app.services.generation.formatters import LinkedInFormatter
from app.services.generation.prompt_builder import PromptBuilder
from app.services.generation.strategy_selector import StrategySelector
from app.services.generation.validators import ValidatorRegistry

logger = logging.getLogger("branding_engine.generation.pipeline")
litellm.suppress_debug_info = True

# ── LiteLLM Provider Cascade ──
# Each entry is a LiteLLM model string. We try them in order until one succeeds.
PROVIDER_CHAIN = [
    "gemini/gemini-3.5-flash-lite",
    "gemini/gemini-3.5-flash",
]

FORBIDDEN_PATTERNS = [
    r"^\s*[-*]\s+",           # Matches bullet points or dashes at the start of a line
    r"(?i)\b(maybe I'?m wrong|I could be wrong|I realized)\b" # Matches forbidden hooks
]

# Words that must never appear in the output
FORBIDDEN_WORDS = [
    "delve", "tapestry", "landscape", "game-changer", "seamless",
    "robust", "ensure", "leverage", "crucial",
]

# ── The Unified System Prompt ──
UNIFIED_SYSTEM_PROMPT = """You are a Senior Software Engineer writing a LinkedIn post about the topic below. You just spent hours deep in the code and you're sharing what actually happened.

VOICE & STRUCTURE:
Write in a raw, authentic, build in public engineering voice. No polish. Real talk.
Anchor every point on concrete technical details: actual code patterns, real metrics, specific debugging stories. Show the messy reality.
FORMATTING: Write in short, punchy paragraphs (1 to 3 sentences max) to ensure the reader is properly hooked and does not skip the post. You MUST separate every paragraph with double newlines (`\n\n`). Do NOT output a single wall of text.
You must continue to completely avoid using hyphens or dashes (-) anywhere in the text to maintain a humanized tone.


ABSOLUTE FORBIDDEN LAWS:
You MUST NOT use hyphens or dashes anywhere in the text. Not even in compound words. Replace them with spaces or rephrase.
You MUST NOT use bullet points, asterisks, numbered lists, or any list formatting.
You MUST NOT use these words: delve, tapestry, landscape, game changer, seamless, robust, ensure, leverage, crucial, reliable, scalable.
You MUST NOT start with "I realized", "I could be wrong", "In today's", "It's amazing how", or "Maybe I'm wrong".
You MUST NOT add a moral, a lesson, or broad advice at the end. The story IS the lesson.
You MUST NOT use any B2B marketing fluff or sweeping certainties.

ENDING:
End the post by asking a single, specific question inviting the audience to share their own frustrating experience.

OUTPUT FORMAT:
Respond with ONLY a JSON object (no markdown fences, no extra text):
{"draft": "<the full LinkedIn post text>", "self_check": "<1 sentence note on any rule you almost broke>", "visual_type": "<'diagram', 'photo', or 'card'>", "visual_payload": "<PlantUML code, scene description, or quote hook>"}

THIRD & FOURTH FIELDS — visual_type and visual_payload:
Choose the best visual strategy:

1. SOFTWARE ARCHITECTURE / SYSTEM DESIGN:
- visual_type: "diagram"
- visual_payload: Valid PlantUML code mapping the technologies discussed.

2. PHYSICAL OBJECTS / HARDWARE (e.g., Wearables, Mainframes):
- visual_type: "photo"
- visual_payload: Concrete physical description ending with "highly detailed, 8k, photorealistic". DO NOT use desk/laptop fallbacks.

3. ABSTRACT TECH, STORIES, LOGGING, OPINIONS:
- visual_type: "card"
- visual_payload: Extract a punchy, thought-provoking quote (10-15 words) directly from your draft. No quotes marks.
"""


class ContentGenerationPipeline:
    """Orchestrates modular stages for content generation with LiteLLM and deterministic cleanup."""

    def __init__(self):
        self.prompt_builder = PromptBuilder()
        self.strategy_selector = StrategySelector()
        self.validator_registry = ValidatorRegistry()
        self.dedup_stage = ContentDeduplicationStage()
        self.linkedin_formatter = LinkedInFormatter()

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

    @staticmethod
    def _deterministic_cleanup(text: str) -> str:
        """Enforce lexical rules via deterministic Python string operations.
        
        This replaces the old LLM retry loop — zero API calls, zero quota waste.
        """
        # Strip all hyphens and dashes (em dash, en dash, regular hyphen)
        text = text.replace("—", " ")
        text = text.replace("–", " ")
        text = text.replace("-", " ")

        # Remove bullet point lines (lines starting with *, -, •, or numbered lists)
        text = re.sub(r"^\s*[*•]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)

        # Remove forbidden words (case-insensitive, whole word)
        for word in FORBIDDEN_WORDS:
            text = re.sub(rf"\b{re.escape(word)}\b", "", text, flags=re.IGNORECASE)

        # Collapse multiple spaces into one
        text = re.sub(r"  +", " ", text)

        # Collapse excessive blank lines (more than 2 newlines → 2)
        text = re.sub(r"(?:\r?\n\s*){3,}", "\n\n", text)

        return text.strip()

    async def _call_litellm(self, topic: str, context_string: str, telemetry) -> str:
        """Call LiteLLM with provider cascade. Returns the raw JSON string response."""
        import litellm

        # Suppress LiteLLM's verbose internal logging
        litellm.suppress_debug_info = True

        user_message = f"Topic: {topic}\n\nContext: {context_string}"

        messages = [
            {"role": "system", "content": UNIFIED_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        last_error = None
        for i, model in enumerate(PROVIDER_CHAIN):
            try:
                logger.info(f"[LITELLM] Attempting model {model} ({i+1}/{len(PROVIDER_CHAIN)})...")
                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1500,
                    response_format={"type": "json_object"},
                )
                result = response.choices[0].message.content
                logger.info(f"[LITELLM] Success with {model}. Response length: {len(result)} chars")

                if i > 0:
                    telemetry.fallback_provider_used = model

                return result

            except Exception as exc:
                last_error = exc
                telemetry.retry_count += 1
                logger.warning(f"[LITELLM] Model {model} failed: {exc}")
                continue

        # All providers exhausted
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def _parse_llm_json(self, raw_response: str) -> dict:
        """Parse the structured JSON from the LLM response, with repair."""
        # Strip markdown fences if present
        cleaned = raw_response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if "draft" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

        # Attempt repair: find the first { and last }
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                parsed = json.loads(cleaned[first_brace:last_brace + 1])
                if "draft" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # Last resort: treat the entire response as the draft
        logger.warning("[JSON REPAIR] Could not parse JSON. Using raw text as draft.")
        return {"draft": cleaned, "self_check": "JSON parsing failed, used raw text."}

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

        # 3. Single-Pass LiteLLM Generation
        self._log_stage("LLM_GENERATE", context.trace_id, "START")
        p_start = time.time()

        context_string = f"{system_prompt}\n\nAdditional Input: {user_prompt}"
        raw_response = await self._call_litellm(context.topic, context_string, context.telemetry)

        context.telemetry.provider_latency_ms = round((time.time() - p_start) * 1000, 2)
        logger.info(f"[LITELLM] Generated draft in {context.telemetry.provider_latency_ms}ms")

        # Parse the structured JSON response
        parsed = self._parse_llm_json(raw_response)
        generated_text = parsed.get("draft", "")
        self_check = parsed.get("self_check", "")
        visual_type = parsed.get("visual_type", "photo")
        visual_payload = parsed.get("visual_payload", "")

        if self_check:
            logger.info(f"[SELF CHECK] {self_check}")

        import hashlib
        s1_hash = hashlib.sha256(generated_text.encode('utf-8')).hexdigest()[:8]
        logger.info(f"[TRACE] [LLM OUTPUT] chars={len(generated_text)} | hash={s1_hash}")

        self._log_stage("LLM_GENERATE", context.trace_id, "SUCCESS")

        # 4. Deterministic Lexical Cleanup (replaces the old LLM retry loop)
        self._log_stage("LEXICAL_CLEANUP", context.trace_id, "START")
        generated_text = self._deterministic_cleanup(generated_text)
        self._log_stage("LEXICAL_CLEANUP", context.trace_id, "SUCCESS", f"post_cleanup_chars={len(generated_text)}")

        # Override dynamic evaluation: hardcode requires_image = True for all pipeline executions
        context.requires_image = True
        llm_output_metadata = {"self_check": self_check}

        # Store the extracted visual properties in context for the orchestrator
        context.visual_type = visual_type
        context.visual_payload = visual_payload

        # 5. Format LinkedIn spacing
        self._log_stage("FORMAT", context.trace_id, "START")
        formatted_text = self.linkedin_formatter.format(generated_text)
        crushed_text = re.sub(r'(?:\r?\n\s*){2,}', '\n\n', formatted_text).strip()
        context.refined_text = crushed_text

        # TRACE: LinkedIn Formatter
        s3_hash = hashlib.sha256(crushed_text.encode('utf-8')).hexdigest()[:8]
        s3_char = len(crushed_text)
        s3_para = len([p for p in crushed_text.split('\n\n') if p.strip()])
        logger.info(f"[TRACE] [LINKEDIN FORMATTER] chars={s3_char} | paras={s3_para} | hash={s3_hash}")

        # 6. Content-Preservation Gate
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

        # 7. Validation Registry Stage
        self._log_stage("VALIDATE", context.trace_id, "START")
        if settings.ENABLE_VALIDATION:
            val_result = self.validator_registry.validate(
                content_text=context.refined_text,
                requires_image=context.requires_image,
                image_prompt=getattr(context, "visual_payload", "") or "",
                author_context=self.prompt_builder._last_author_context,
            )
            for err in val_result.errors:
                context.add_error(err)
            for warn in val_result.warnings:
                context.add_warning(warn)
        self._log_stage("VALIDATE", context.trace_id, "SUCCESS", f"errors={len(context.errors)}, warnings={len(context.warnings)}")

        # 8. Deduplication & Content Metrics Stage
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

        # 9. Image Generation Stage (handled by orchestrator)
        self._log_stage("IMAGE_GEN", context.trace_id, "SKIPPED", "Handled by Orchestrator")

        # 10. Store ContentDraft in Database
        self._log_stage("DB_PERSIST", context.trace_id, "START")
        context.telemetry.finish()

        provider_used = context.telemetry.fallback_provider_used or PROVIDER_CHAIN[0]
        llm_metadata = {
            "trace_id": context.trace_id,
            "model": provider_used,
            "prompt_length": len(user_prompt) + len(system_prompt),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requires_image": context.requires_image,
            "visual_type": context.visual_type,
            "visual_payload": context.visual_payload,
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
            # We do NOT set status to 'DRAFT' here; orchestrator will finalize it
            draft.generated_at = datetime.now(timezone.utc)
            draft.llm_metadata = llm_metadata
        else:
            draft = ContentDraft(
                persona_id=context.persona.id if context.persona else None,
                platform="linkedin",
                content_text=context.refined_text,
                status="GENERATING", # Orchestrator will finalize it to DRAFT_READY
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
