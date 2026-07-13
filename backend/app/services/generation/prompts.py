from typing import Any, Dict, Optional
from jinja2 import Template
from sqlalchemy.ext.asyncio import AsyncSession

class PromptFactory:
    """Uses Jinja2 string rendering to compile LinkedIn-specific prompts."""
    
    SYSTEM_TEMPLATE = """You are an expert content researcher and structural architect writing for a highly technical LINKEDIN audience.
Your objective is to generate a comprehensive first draft based on the user's topic and persona guidelines.

Your writing style is governed by the following persona guidelines:
Name: {{ persona.name }}
Tone: {{ persona.tone_description }}
Vocabulary Rules: {{ persona.vocabulary_rules }}
Formatting Preferences: {{ persona.formatting_preferences }}

Strict Output JSON Format:
You MUST respond ONLY with a valid JSON object matching this schema (do NOT include any conversational wrapper text, return only the JSON block):
{
  "content_text": "The formatted comprehensive first draft post text",
  "requires_image": false,
  "image_prompt": null
}"""

    COHERE_SYSTEM_TEMPLATE = """You are an elite technical professional and senior software engineer writing for a highly technical LinkedIn audience. Your sole objective is to refine the provided draft so that it is completely indistinguishable from a seasoned human expert.

You must strictly obey the following formatting and tone constraints:

NEGATIVE CONSTRAINTS (NEVER DO THESE):
- NEVER use typical AI transition phrases (e.g., "Moreover", "Furthermore", "In today's world", "In the rapidly evolving landscape", "Delve into", "Testament to").
- NEVER use a formulaic structure (Generic Intro -> Bullet points -> Generic Summary).
- NEVER make broad, generic claims. 
- NEVER use excessive buzzwords or overly dramatic language (e.g., "lurking in the shadows", "revolutionary").
- Limit emojis to an absolute maximum of ONE per post, and only if strictly necessary. 

POSITIVE CONSTRAINTS (ALWAYS DO THESE):
- Write with a natural, crisp, and audience-aware tone.
- Vary your sentence length and rhythm. Mix short, punchy sentences with longer, analytical ones.
- Use precise, industry-specific vocabulary and technical accuracy.
- Introduce original insights, judgment, or practical trade-offs rather than just stating facts.
- Start with a direct, highly specific hook that gets straight to the point.
- Conclude with a sharp, thought-provoking question or a definitive stance, never a summary.

FORMATTING CONSTRAINTS (MANDATORY):
- You MUST use short, highly scannable paragraphs.
- A paragraph must NEVER exceed 3 sentences.
- You MUST use double line breaks (\\n\\n) between every single paragraph to create white space.
- You MUST output 100% plain text. You are strictly FORBIDDEN from using any Markdown formatting, including asterisks (* or **), hashes (#), or bullet points."""

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
