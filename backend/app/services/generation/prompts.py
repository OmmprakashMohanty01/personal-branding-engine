from typing import Any, Dict, Optional
from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

class PromptFactory:
    """Uses Jinja2 string rendering to compile platform-specific prompts with persona templates."""
    
    SYSTEM_TEMPLATE = """You are an expert content creator writing for {{ platform.upper() }}.
Your writing style is governed by the following persona guidelines:
Name: {{ persona.name }}
Tone: {{ persona.tone_description }}
Vocabulary Rules: {{ persona.vocabulary_rules }}
Formatting Preferences: {{ persona.formatting_preferences }}

Strict Platform Rules:
{% if platform == 'x' %}
- Write a short, punchy post. If the content requires deep explanation, write it in a structured thread format where each post in the thread is separated by a new line with "---thread-split---".
- Keep individual thread parts strictly under 250 characters.
- Minimal hashtags (max 1).
{% elif platform == 'linkedin' %}
- Start with a strong, curiosity-inducing hook line.
- Use clean line breaks (double newlines) to improve scannability.
- Cap emoji count at maximum 3.
- Match professional tech branding voice.
{% elif platform == 'threads' %}
- Write in a casual, conversational, and friendly manner.
- Keep it engaging and interactive (end with an open question).
{% elif platform == 'substack' %}
- Formatted as a long-form, comprehensive article in markdown.
- Include bold headers (##, ###) and clear introductory/concluding paragraphs.
{% endif %}"""

    USER_TEMPLATE = """Develop a piece of content based on the following trending topic:
Title: {{ trend.title }}
Summary: {{ trend.summary }}
Topic Category: {{ trend.topic }}
Source Metadata: {{ trend.metadata_json }}

{% if feedback %}
User feedback adjustment request:
"{{ feedback }}"
Modify the generation to address this feedback request.
{% endif %}"""

    async def render_system_prompt(self, platform: str, persona: Any, db: Optional[AsyncSession] = None) -> str:
        """Render the system prompt with persona properties and historical corrections."""
        template = Template(self.SYSTEM_TEMPLATE)
        base_prompt = template.render(platform=platform.lower(), persona=persona)
        
        if db is not None:
            try:
                from app.models.optimization import OptimizationFeedback
                stmt = select(OptimizationFeedback).where(
                    OptimizationFeedback.persona_id == persona.id,
                    OptimizationFeedback.platform == platform.lower(),
                    OptimizationFeedback.is_active == True
                )
                res = await db.execute(stmt)
                opt = res.scalars().first()
                if opt and opt.optimized_system_prompt:
                    base_prompt += f"\n\n{opt.optimized_system_prompt}"
            except Exception as e:
                import logging
                logging.getLogger("branding_engine.generation.prompts").error(
                    f"Error reading optimized system prompt: {e}"
                )
                
        return base_prompt

    def render_user_prompt(self, trend: Any, feedback: Optional[str] = None) -> str:
        """Render the user prompt with trend context and optional tweak feedback."""
        template = Template(self.USER_TEMPLATE)
        return template.render(trend=trend, feedback=feedback)
