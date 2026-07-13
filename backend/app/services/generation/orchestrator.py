import logging
import json
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

    async def _get_default_persona(self, db: AsyncSession) -> Persona:
        """Find or create default persona representation."""
        stmt = select(Persona).where(Persona.is_default == True)
        res = await db.execute(stmt)
        persona = res.scalars().first()
        
        if not persona:
            # Seed a default persona in-memory if missing from database
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
            
        # 2. Render Prompts
        logger.info(f"[PIPELINE START] Processing topic: {topic}")
        
        system_prompt_gemini = await self.prompt_factory.render_system_prompt(persona, db=db)
        user_prompt = self.prompt_factory.render_user_prompt(topic, feedback)
        
        # 3. Stage 1: Google Gemini 1.5 Flash
        gemini_start = time.time()
        stage1_raw = ""
        try:
            from google import genai
            gemini_key = self.gemini_api_key or os.getenv("GEMINI_API_KEY") or "mock_gemini_key"
            
            client = genai.Client(api_key=gemini_key)
            stage_1_prompt = f"{system_prompt_gemini}\n\nUser Input/Topic: {user_prompt}"
            
            interaction = client.interactions.create(
                model="gemini-3.5-flash",
                input=stage_1_prompt
            )
            stage1_raw = interaction.output_text
            gemini_duration = time.time() - gemini_start
            logger.info(f"[STAGE 1 COMPLETE - Gemini] Draft generated in {gemini_duration:.2f}s")
        except Exception as e:
            logger.warning(f"[STAGE 1 FALLBACK] Gemini rate limited, falling back to Cohere for drafting: {e}")
            try:
                import cohere
                cohere_key = self.cohere_api_key or os.getenv("COHERE_API_KEY") or "mock_cohere_key"
                co = cohere.AsyncClient(api_key=cohere_key)
                response = await co.chat(
                    message=stage_1_prompt,
                    model="command-r"
                )
                stage1_raw = response.text
                logger.info("[STAGE 1 FALLBACK COMPLETE - Cohere] Draft generated using Cohere")
            except Exception as cohere_err:
                logger.error(f"Stage 1 Cohere fallback also failed: {cohere_err}")
                raise e

        # Parse Stage 1 JSON Output
        generated_text = stage1_raw
        requires_image = False
        image_prompt = None
        
        try:
            clean_output = stage1_raw.strip()
            # Strip markdown json code blocks if present
            code_block_match = re.search(r"```json\s*(.*?)\s*```", clean_output, re.DOTALL)
            if code_block_match:
                clean_output = code_block_match.group(1)
            
            try:
                parsed_data = json.loads(clean_output)
            except json.JSONDecodeError:
                # Robust regex-based fallback for unescaped newlines and other parsing errors
                parsed_data = {}
                content_text_match = re.search(r'"content_text"\s*:\s*"(.*?)"\s*,\s*"requires_image"', clean_output, re.DOTALL)
                if not content_text_match:
                    content_text_match = re.search(r'"content_text"\s*:\s*"(.*?)"\s*(?:,|\s*})', clean_output, re.DOTALL)
                
                requires_image_match = re.search(r'"requires_image"\s*:\s*(true|false)', clean_output, re.IGNORECASE)
                image_prompt_match = re.search(r'"image_prompt"\s*:\s*"(.*?)"\s*(?:,|\s*})', clean_output, re.DOTALL)
                
                if content_text_match:
                    parsed_data["content_text"] = content_text_match.group(1)
                if requires_image_match:
                     parsed_data["requires_image"] = requires_image_match.group(1).lower() == "true"
                if image_prompt_match:
                     parsed_data["image_prompt"] = image_prompt_match.group(1)
                
                if not parsed_data:
                    raise ValueError("Could not parse JSON even with robust regex extraction")
            
            generated_text = parsed_data.get("content_text", stage1_raw)
            requires_image = parsed_data.get("requires_image", False)
            image_prompt = parsed_data.get("image_prompt")
        except Exception as e:
            logger.error(f"Failed to parse Stage 1 JSON response: {e}. Falling back to raw text. Raw output: {stage1_raw}")
            generated_text = stage1_raw

        # 4. Stage 2: Cohere Command R (Humanized Tone & Style Editing)
        cohere_start = time.time()
        final_text = generated_text
        pipeline_model = "gemini-3.5-flash & cohere"
        try:
            import cohere
            cohere_key = self.cohere_api_key or os.getenv("COHERE_API_KEY") or "mock_cohere_key"
            
            # Initialize async client
            co = cohere.AsyncClient(api_key=cohere_key)
            
            response = await co.chat(
                message=generated_text,
                model="command-r",
                preamble=self.prompt_factory.COHERE_SYSTEM_TEMPLATE
            )
            final_text = response.text
            cohere_duration = time.time() - cohere_start
            logger.info(f"[STAGE 2 COMPLETE - Cohere] Tone refinement completed in {cohere_duration:.2f}s")
            pipeline_model = "gemini-3.5-flash & cohere"
        except Exception as e:
            logger.warning(f"[PIPELINE FALLBACK TRIGGERED] Cohere unavailable, defaulting to Gemini draft. Reason: {e}")
            final_text = generated_text

        # 5. Post-Process & Persist to Database
        # Format the refined output
        formatted_output = self.linkedin_formatter.format(final_text)
        # Violently crush 3 or more consecutive line breaks (including spaces/carriage returns) down to exactly two clean line breaks
        crushed_output = re.sub(r'(?:\r?\n\s*){2,}', '\n\n', formatted_output).strip()
        
        draft = ContentDraft(
            persona_id=persona.id,
            platform="linkedin",
            content_text=crushed_output,
            status="DRAFT",
            generated_at=datetime.now(timezone.utc),
            llm_metadata={
                "model": pipeline_model,
                "prompt_length": len(user_prompt) + len(system_prompt_gemini),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "requires_image": requires_image,
                "image_prompt": image_prompt
            }
        )
        
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        
        return draft
