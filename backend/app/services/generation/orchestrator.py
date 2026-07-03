import logging
import json
import re
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import Persona, ContentDraft
from app.services.llm_provider import FallbackLLMProvider
from app.services.generation.prompts import PromptFactory
from app.services.generation.formatters import LinkedInFormatter

logger = logging.getLogger("branding_engine.generation.orchestrator")

class GenerationOrchestrator:
    """Manages the lifecycle of content draft generation from user-supplied topics and personas."""
    
    def __init__(self):
        self.prompt_factory = PromptFactory()
        self.linkedin_formatter = LinkedInFormatter()
        self.llm_provider = FallbackLLMProvider()

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
        system_prompt = await self.prompt_factory.render_system_prompt(persona, db=db)
        user_prompt = self.prompt_factory.render_user_prompt(topic, feedback)
        
        # 3. Invoke LLM Provider
        logger.info(f"Generating LinkedIn content for topic: {topic}")
        raw_output = await self.llm_provider.generate(
            prompt=user_prompt,
            system_instruction=system_prompt,
            temperature=0.7
        )
        
        generated_text = raw_output
        requires_image = False
        image_prompt = None

        # Parse LLM JSON Output
        try:
            clean_output = raw_output.strip()
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
            
            generated_text = parsed_data.get("content_text", "")
            requires_image = parsed_data.get("requires_image", False)
            image_prompt = parsed_data.get("image_prompt")
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON response: {e}. Falling back to treating entire output as plain text. Raw output: {raw_output}")
            generated_text = raw_output

        # 4. Post-Process via LinkedIn Formatter
        formatted_output = self.linkedin_formatter.format(generated_text)
            
        # 5. Persist to Database
        draft = ContentDraft(
            persona_id=persona.id,
            content_text=formatted_output,
            status="DRAFT",
            generated_at=datetime.now(timezone.utc),
            llm_metadata={
                "model": getattr(self.llm_provider, "primary_name", "unknown"),
                "prompt_length": len(user_prompt) + len(system_prompt),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "requires_image": requires_image,
                "image_prompt": image_prompt
            }
        )
        
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        
        return draft
