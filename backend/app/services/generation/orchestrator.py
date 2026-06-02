import logging
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.trend import Trend
from app.models.content import Persona, ContentDraft
from app.services.llm_provider import FallbackLLMProvider
from app.services.generation.prompts import PromptFactory
from app.services.generation.formatters import (
    XFormatter,
    LinkedInFormatter,
    ThreadsFormatter,
    SubstackFormatter
)

logger = logging.getLogger("branding_engine.generation.orchestrator")

class GenerationOrchestrator:
    """Manages the lifecycle of content draft generation from trends and personas."""
    
    def __init__(self):
        self.prompt_factory = PromptFactory()
        self.x_formatter = XFormatter()
        self.linkedin_formatter = LinkedInFormatter()
        self.threads_formatter = ThreadsFormatter()
        self.substack_formatter = SubstackFormatter()
        
        # Instantiate fallback LLM provider
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
        trend_id: str,
        platform: str,
        persona_id: Optional[str] = None,
        feedback: Optional[str] = None
    ) -> ContentDraft:
        """Generate and persist a platform-specific draft content piece.
        
        Args:
            db: SQLAlchemy AsyncSession.
            trend_id: The ID of the trend.
            platform: Target social platform ('linkedin', 'x', 'threads', 'substack').
            persona_id: Optional UUID override for persona guidelines.
            feedback: Optional adjustment feedback for regeneration.
            
        Returns:
            The saved ContentDraft database model.
        """
        # 1. Fetch Trend
        trend_stmt = select(Trend).where(Trend.id == trend_id)
        trend_res = await db.execute(trend_stmt)
        trend = trend_res.scalars().first()
        if not trend:
            raise ValueError(f"Trend with ID {trend_id} not found.")
            
        # 2. Fetch Persona
        if persona_id:
            persona_stmt = select(Persona).where(Persona.id == persona_id)
            persona_res = await db.execute(persona_stmt)
            persona = persona_res.scalars().first()
            if not persona:
                raise ValueError(f"Persona with ID {persona_id} not found.")
        else:
            persona = await self._get_default_persona(db)
            
        # 3. Render Prompts
        system_prompt = await self.prompt_factory.render_system_prompt(platform, persona, db=db)
        user_prompt = self.prompt_factory.render_user_prompt(trend, feedback)
        
        # 4. Invoke LLM Provider
        logger.info(f"Generating content for {platform} on trend: {trend.title}")
        try:
            raw_output = await self.llm_provider.generate(
                prompt=user_prompt,
                system_instruction=system_prompt,
                temperature=0.7
            )
        except Exception as e:
            import asyncio
            from app.services.monitoring.alerts import AlertManager
            asyncio.create_task(
                AlertManager().send_alert(
                    f"LLM Generation Failed on trend '{trend.title}': {e}",
                    "WARNING"
                )
            )
            raise e
        
        # Parse LLM JSON Output
        import json
        import re
        import urllib.parse

        generated_text = raw_output
        requires_image = False
        image_prompt = None

        try:
            clean_output = raw_output.strip()
            # Strip markdown json code blocks if present
            code_block_match = re.search(r"```json\s*(.*?)\s*```", clean_output, re.DOTALL)
            if code_block_match:
                clean_output = code_block_match.group(1)
            
            parsed_data = json.loads(clean_output)
            generated_text = parsed_data.get("content_text", "")
            requires_image = parsed_data.get("requires_image", False)
            image_prompt = parsed_data.get("image_prompt")
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON response: {e}. Falling back to treating entire output as plain text. Raw output: {raw_output}")
            generated_text = raw_output

        # 5. Post-Process via Platform Formatter
        formatted_output = generated_text
        plat_lower = platform.lower()
        if plat_lower == "x":
            formatted_output = self.x_formatter.format(generated_text)
        elif plat_lower == "linkedin":
            formatted_output = self.linkedin_formatter.format(generated_text)
        elif plat_lower == "threads":
            formatted_output = self.threads_formatter.format(generated_text)
        elif plat_lower == "substack":
            formatted_output = self.substack_formatter.format(generated_text)
            
        # Dynamic Media Decision Engine URL Construction
        image_url = None
        if requires_image and image_prompt:
            encoded_prompt = urllib.parse.quote(image_prompt)
            image_url = f"https://image.pollinations.ai/p/{encoded_prompt}?width=1024&height=1024&nologo=true"

        # 6. Persist to Database
        draft = ContentDraft(
            trend_id=trend.id,
            persona_id=persona.id,
            platform=plat_lower,
            content_text=formatted_output,
            status="DRAFT",
            image_url=image_url,
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
