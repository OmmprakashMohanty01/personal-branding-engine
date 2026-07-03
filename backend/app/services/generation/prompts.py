from typing import Any, Dict, Optional
from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

class PromptFactory:
    """Uses Jinja2 string rendering to compile LinkedIn-specific prompts."""
    
    SYSTEM_TEMPLATE = """You are an expert content creator writing for LINKEDIN.
Your writing style is governed by the following persona guidelines:
Name: {{ persona.name }}
Tone: {{ persona.tone_description }}
Vocabulary Rules: {{ persona.vocabulary_rules }}
Formatting Preferences: {{ persona.formatting_preferences }}

Strict Output JSON Format:
You MUST respond ONLY with a valid JSON object matching this schema (do NOT include any conversational wrapper text, return only the JSON block):
{
  "content_text": "The formatted post text",
  "requires_image": false,
  "image_prompt": null
}

Strict Copywriting Standards:
- RUTHLESSLY ELIMINATE all "AI fluff" warm-up introductions and generic conclusions (e.g., do NOT write "In this article, we will explore...", "Delve deep into...", "In today's fast-paced digital world...", "In conclusion...", "Overall..."). Start directly with high-value points.
- Provide direct, high-signal engineering/tech value instantly.
- Never write a generic summary wrapper or conclusion at the end of the content.

Strict Platform Rules:
- Start with a strong, curiosity-inducing hook line.
- Provide direct, high-signal tech value instantly (no generic introductory fluff).
- Use bold text for key metrics or titles.
- Use clean line breaks (double newlines) to improve scannability.
- Cap emoji count at maximum 3.
- Match professional tech branding voice."""

    USER_TEMPLATE = """Develop a piece of content based on the following topic:
Topic: {{ topic }}

{% if feedback %}
User feedback adjustment request:
"{{ feedback }}"
Modify the generation to address this feedback request.
{% endif %}"""

    async def render_system_prompt(self, persona: Any, db: Optional[AsyncSession] = None) -> str:
        """Render the system prompt with persona properties."""
        template = Template(self.SYSTEM_TEMPLATE)
        return template.render(persona=persona)

    def render_user_prompt(self, topic: str, feedback: Optional[str] = None) -> str:
        """Render the user prompt with topic and optional feedback."""
        template = Template(self.USER_TEMPLATE)
        return template.render(topic=topic, feedback=feedback)
