"""
orchestrator.py
===============
GenerationOrchestrator — manages the lifecycle of content draft generation
using the modular prompt pipeline.

Stage 1: Gemini 3.5 Flash (structural draft with nested metadata schema)
Stage 2: Cohere Command A+ (humanized tone & style editing)
"""

import logging
import json
import random
import re
import os
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import Persona, ContentDraft
from app.services.generation.prompts import PromptFactory
from app.services.generation.formatters import LinkedInFormatter

logger = logging.getLogger("branding_engine.generation.orchestrator")


class GenerationOrchestrator:
    """Manages the lifecycle of content draft generation from user-supplied topics and personas."""

    def __init__(self):
        self.prompt_factory = PromptFactory()
        self.linkedin_formatter = LinkedInFormatter()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.cohere_api_key = os.getenv("COHERE_API_KEY")

    @staticmethod
    def _randomize_temperature() -> float:
        """Generate a randomized temperature between 0.75 and 0.90."""
        return round(random.uniform(0.75, 0.90), 2)

    @staticmethod
    def _randomize_top_p() -> float:
        """Generate a randomized top_p between 0.90 and 0.98."""
        return round(random.uniform(0.90, 0.98), 2)

    async def _get_default_persona(self, db: AsyncSession) -> Persona:
        """Find or create default persona representation."""
        stmt = select(Persona).where(Persona.is_default == True)
        res = await db.execute(stmt)
        persona = res.scalars().first()

        if not persona:
            persona = Persona(
                name="CS Graduate Tech Brand",
                tone_description="Professional, enthusiastic, tech-savvy, educational, startup-minded.",
                vocabulary_rules="Avoid buzzwords, use clear terminology, emphasize open source, Python, automation.",
                formatting_preferences="Clean spacing, list highlights, max 1 link.",
                is_default=True
            )
            db.add(persona)
            await db.flush()

        return persona

    async def generate_draft(
        self,
        db: AsyncSession,
        topic: str,
        persona_id: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> ContentDraft:
        """Generate and persist a LinkedIn content draft based on a topic string.

        Args:
            db: SQLAlchemy AsyncSession.
            topic: The user supplied topic.
            persona_id: Optional UUID override for persona guidelines.
            feedback: Optional adjustment feedback for regeneration.

        Returns:
            The saved ContentDraft database model.
        """
        # 1. Fetch Persona
        if persona_id:
            persona_stmt = select(Persona).where(Persona.id == persona_id)
            persona_res = await db.execute(persona_stmt)
            persona = persona_res.scalars().first()
            if not persona:
                raise ValueError(f"Persona with ID {persona_id} not found.")
        else:
            persona = await self._get_default_persona(db)

        # 2. Randomize generation parameters
        temperature = self._randomize_temperature()
        top_p = self._randomize_top_p()

        # 3. Render Prompts via modular pipeline
        logger.info(f"[PIPELINE START] Processing topic: {topic}")

        system_prompt_gemini = await self.prompt_factory.render_system_prompt(
            persona, db=db, topic=topic
        )
        user_prompt = self.prompt_factory.render_user_prompt(topic, feedback)

        # 4. Log pipeline metadata (without content)
        pipeline_metadata = self.prompt_factory.get_generation_metadata()
        logger.info(
            "[PIPELINE CONFIG]",
            extra={
                "temperature": temperature,
                "top_p": top_p,
                **pipeline_metadata,
            },
        )

        # 5. Stage 1: Google Gemini 3.5 Flash
        gemini_start = time.time()
        stage1_raw = ""
        try:
            from google import genai
            gemini_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or "mock_gemini_key"

            client = genai.Client(api_key=gemini_key)
            stage_1_prompt = f"{system_prompt_gemini}\n\nUser Input/Topic: {user_prompt}"

            import asyncio
            from fastapi import HTTPException
            def _sync_call():
                return client.interactions.create(
                    model="gemini-3.5-flash",
                    input=stage_1_prompt
                )
            for attempt in range(3):
                try:
                    interaction = await asyncio.to_thread(_sync_call)
                    stage1_raw = interaction.output_text
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.warning(f"Gemini attempt {attempt + 1} failed: {e}. Retrying...")
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise e
            gemini_duration = time.time() - gemini_start
            logger.info(f"[STAGE 1 COMPLETE - Gemini] Draft generated in {gemini_duration:.2f}s")
        except Exception as e:
            logger.warning(f"[STAGE 1 FALLBACK] Gemini rate limited, falling back to Cohere for drafting: {e}")
            try:
                import cohere
                cohere_key = self.cohere_api_key or os.getenv("COHERE_API_KEY") or "mock_cohere_key"
                co = cohere.AsyncClientV2(api_key=cohere_key)
                response = await co.chat(
                    model="command-r",
                    messages=[{"role": "user", "content": stage_1_prompt}]
                )
                stage1_raw = next((block.text for block in response.message.content if hasattr(block, "text") and block.text), "") if (response.message and response.message.content) else ""
                logger.info("[STAGE 1 FALLBACK COMPLETE - Cohere] Draft generated using Cohere")
            except Exception as cohere_err:
                logger.exception("Both providers failed")
                raise HTTPException(
                    status_code=503,
                    detail="All AI providers are temporarily unavailable. Please try again later."
                )

        # 6. Parse Stage 1 JSON Output (nested metadata schema)
        generated_text = stage1_raw
        requires_image = False
        image_prompt = None
        llm_output_metadata = {}

        try:
            clean_output = stage1_raw.strip()
            # Strip markdown json code blocks if present
            code_block_match = re.search(r"```json\s*(.*?)\s*```", clean_output, re.DOTALL)
            if code_block_match:
                clean_output = code_block_match.group(1)

            try:
                parsed_data = json.loads(clean_output)
            except json.JSONDecodeError:
                # Robust regex-based fallback for unescaped newlines
                parsed_data = {}
                content_text_match = re.search(r'"content_text"\s*:\s*"(.*)"\s*,\s*"requires_image"', clean_output, re.DOTALL)
                if not content_text_match:
                    content_text_match = re.search(r'"content_text"\s*:\s*"(.*)"', clean_output, re.DOTALL)

                requires_image_match = re.search(r'"requires_image"\s*:\s*(true|false)', clean_output, re.IGNORECASE)
                image_prompt_match = re.search(r'"image_prompt"\s*:\s*"(.*)"', clean_output, re.DOTALL)

                if content_text_match:
                    val = content_text_match.group(1)
                    if '",\n  "requires_image"' in val:
                        val = val.split('",\n  "requires_image"')[0]
                    elif '",\r\n  "requires_image"' in val:
                        val = val.split('",\r\n  "requires_image"')[0]
                    elif '",\n"requires_image"' in val:
                        val = val.split('",\n"requires_image"')[0]
                    elif '", "requires_image"' in val:
                        val = val.split('", "requires_image"')[0]
                    elif '"' in val:
                        val = val.rsplit('"', 1)[0]
                    parsed_data["content_text"] = val

                if requires_image_match:
                    parsed_data["requires_image"] = requires_image_match.group(1).lower() == "true"

                if image_prompt_match:
                    val_prompt = image_prompt_match.group(1)
                    if '"' in val_prompt:
                        val_prompt = val_prompt.split('"')[0]
                    parsed_data["image_prompt"] = val_prompt

                if not parsed_data:
                    raise ValueError("Could not parse JSON even with robust regex extraction")

            generated_text = parsed_data.get("content_text", stage1_raw)
            requires_image = parsed_data.get("requires_image", False)
            image_prompt = parsed_data.get("image_prompt")

            # Extract nested metadata dict from LLM output (if present)
            llm_output_metadata = parsed_data.get("metadata", {})
            if not isinstance(llm_output_metadata, dict):
                llm_output_metadata = {}

            # Also support flat fields for backward compatibility
            if not llm_output_metadata:
                for key in ("post_type", "hook_style", "hook_strategy", "audience", "goal"):
                    if key in parsed_data:
                        llm_output_metadata[key] = parsed_data[key]

        except Exception as e:
            logger.error(f"Failed to parse Stage 1 JSON response: {e}. Falling back to raw text. Raw output: {stage1_raw}")
            generated_text = stage1_raw

        # 7. Stage 2: Cohere Command A+ (Humanized Tone & Style Editing)
        cohere_start = time.time()
        final_text = generated_text
        pipeline_model = "gemini-3.5-flash & cohere"
        try:
            import cohere
            cohere_key = self.cohere_api_key or os.getenv("COHERE_API_KEY") or "mock_cohere_key"
            co = cohere.AsyncClientV2(api_key=cohere_key)

            cohere_system_prompt = self.prompt_factory.COHERE_SYSTEM_TEMPLATE

            # Pass temperature and top_p to Cohere when supported
            cohere_kwargs = {
                "model": "command-r",
                "messages": [
                    {"role": "system", "content": cohere_system_prompt},
                    {"role": "user", "content": generated_text}
                ],
            }
            try:
                cohere_kwargs["temperature"] = temperature
                cohere_kwargs["p"] = top_p
            except Exception:
                pass  # Graceful degradation if SDK version doesn't support these

            response = await co.chat(**cohere_kwargs)
            final_text = next((block.text for block in response.message.content if hasattr(block, "text") and block.text), "") if (response.message and response.message.content) else ""
            cohere_duration = time.time() - cohere_start
            logger.info(f"[STAGE 2 COMPLETE - Cohere] Tone refinement completed in {cohere_duration:.2f}s")
            pipeline_model = "gemini-3.5-flash & cohere"
        except Exception as e:
            logger.warning(f"[PIPELINE FALLBACK TRIGGERED] Cohere unavailable, defaulting to Gemini draft. Reason: {e}")
            final_text = generated_text

        # 8. Post-Process & Persist to Database
        formatted_output = self.linkedin_formatter.format(final_text)
        crushed_output = re.sub(r'(?:\r?\n\s*){2,}', '\n\n', formatted_output).strip()

        # Build comprehensive metadata
        llm_metadata = {
            "model": pipeline_model,
            "prompt_length": len(user_prompt) + len(system_prompt_gemini),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requires_image": requires_image,
            "image_prompt": image_prompt,
            "temperature": temperature,
            "top_p": top_p,
            "topic": topic,
        }

        # Add nested metadata from LLM output
        if llm_output_metadata:
            llm_metadata["llm_output_metadata"] = llm_output_metadata

        # Add pipeline metadata from PromptBuilder (hook, ending, goal, audience, etc.)
        llm_metadata.update(pipeline_metadata)

        draft = ContentDraft(
            persona_id=persona.id,
            platform="linkedin",
            content_text=crushed_output,
            status="DRAFT",
            generated_at=datetime.now(timezone.utc),
            llm_metadata=llm_metadata,
        )

        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        logger.info(
            "[PIPELINE COMPLETE] Draft saved",
            extra={
                "draft_id": draft.id,
                "temperature": temperature,
                "top_p": top_p,
                "llm_output_metadata": llm_output_metadata,
            },
        )

        return draft
