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

Strict Output JSON Format:
You MUST respond ONLY with a valid JSON object matching this schema (do NOT include any conversational wrapper text, return only the JSON block):
{
  "content_text": "The formatted post/thread/article text",
  "requires_image": true/false,
  "image_prompt": "Detailed graphic prompt description if requires_image is true, otherwise null"
}

Dynamic Media Art Director Guidelines:
- Set `requires_image` to false for pure metrics, thought-leadership, or strong contrarian opinions (Atomic Essay style).
- Set `requires_image` to true for complex architectures, visual tools, or deep abstract concepts.
- If `requires_image` is true, write a highly detailed, dark-mode, minimalist tech graphic prompt in `image_prompt` (optimized for AI image generation: specify a dark background, neon blueprint/circuit accents, abstract minimal layout, 8k resolution, vector style).

Strict Copywriting Standards:
- RUTHLESSLY ELIMINATE all "AI fluff" warm-up introductions and generic conclusions (e.g., do NOT write "In this article, we will explore...", "Delve deep into...", "In today's fast-paced digital world...", "In conclusion...", "Overall..."). Start directly with high-value points.
- Provide direct, high-signal engineering/tech value instantly.
- Never write a generic summary wrapper or conclusion at the end of the content.

Strict Platform Rules:
{% if platform == 'x' %}
- Start with a powerful hook line (Contrarian or Value-driven).
- Utilize single-sentence line breaks for ultimate mobile scannability and high whitespace.
- If the content requires deep explanation, write it in a structured thread format where each post in the thread is separated by a new line with "---thread-split---".
- Keep individual thread parts strictly under 250 characters.
- Minimal hashtags (max 1).
{% elif platform == 'linkedin' %}
- Start with a strong, curiosity-inducing hook line.
- Provide direct, high-signal tech value instantly (no generic introductory fluff).
- Use bold text for key metrics or titles.
- Use clean line breaks (double newlines) to improve scannability.
- Cap emoji count at maximum 3.
- Match professional tech branding voice.
{% elif platform == 'threads' %}
- Start with a powerful hook line (Contrarian or Value-driven).
- Utilize single-sentence line breaks for ultimate mobile scannability and high whitespace.
- Write in a casual, conversational, and friendly manner.
- Keep it engaging and interactive (end with an open question).
{% elif platform == 'substack' %}
- Formatted as a long-form, comprehensive article in markdown.
- Provide direct, high-signal tech value instantly.
- Use bold text for key metrics or titles.
- Include bold headers (##, ###).
- DO NOT use generic concluding paragraphs or summary wraps at the end.
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
