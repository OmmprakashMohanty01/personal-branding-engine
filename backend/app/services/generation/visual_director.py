import logging
import json
import litellm
from app.schemas.generation import VisualDirection

logger = logging.getLogger("branding_engine.generation.visual_director")

# Model cascade similar to pipeline.py
PROVIDER_CHAIN = [
    "gemini/gemini-3.5-flash-lite",
    "gemini/gemini-3.5-flash",
]

VISUAL_DIRECTOR_PROMPT = """You are an elite Art Director and Visual Strategist for a high-end personal branding engine on LinkedIn.
Your job is to read the LinkedIn post and determine the EXACT visual imagery that should accompany it.

You must return a structured JSON response describing what the image should be. 
Do NOT describe what the post says. Describe what the IMAGE should visually show.

### VISUAL TYPE RULES
1. For normal technology posts: Use 'editorial_photo' (cinematic, realistic, professional tech editorial).
2. For posts that genuinely benefit from explaining a system, architecture, or workflow: Use 'diagram'.
3. DO NOT use 'quote_card' unless specifically requested by the user, as we want to avoid text screenshots.

### CONTENT RULES
- One clear visual subject.
- Strong visual hierarchy and premium technology publication aesthetic.
- Realistic materials and lighting.
- For Privacy/Cybersecurity: Use realistic devices, technical environments, subtle security symbolism. AVOID clichés like giant padlocks, hackers in hoodies, or Matrix rain.
- For Code/Developer: Use realistic workstations, server architectures, or cinematic engineering environments. AVOID rendering LinkedIn text on a fake terminal.

### ABSOLUTE PROHIBITIONS (NEVER DO THESE)
You MUST NOT instruct the image generator to create:
- quote cards or text posters
- screenshots containing the entire post
- fake browser windows or social media posts
- paragraphs of text
- presentation slides or UI dashboards
- watermarks, decorative filler, or giant typography

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{
  "visual_type": "editorial_photo | diagram | quote_card",
  "subject": "The primary focus of the image",
  "scene": "The setting and context",
  "concept": "The underlying technical or emotional concept",
  "composition": "How the elements are arranged (e.g., cinematic three quarter perspective, strong negative space)",
  "lighting": "Lighting details (e.g., subtle blue ambient lighting)",
  "style": "Overall aesthetic (e.g., premium technology editorial photography)",
  "negative_prompt": "Specific things to avoid (e.g., text, quotes, paragraphs, UI, logos, watermarks)"
}
"""

class VisualDirector:
    """Uses LLM to evaluate a draft and produce a structured VisualDirection."""

    @classmethod
    async def generate_direction(cls, topic: str, content: str) -> VisualDirection:
        """Call LiteLLM with provider cascade to generate VisualDirection."""
        litellm.suppress_debug_info = True

        user_message = f"Topic: {topic}\n\nPost Content:\n{content}"

        messages = [
            {"role": "system", "content": VISUAL_DIRECTOR_PROMPT},
            {"role": "user", "content": user_message},
        ]

        last_error = None
        for i, model in enumerate(PROVIDER_CHAIN):
            try:
                logger.info(f"[VISUAL_DIRECTOR] Attempting model {model} ({i+1}/{len(PROVIDER_CHAIN)})...")
                response = await litellm.acompletion(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=800,
                    response_format={"type": "json_object"},
                )
                
                raw_response = response.choices[0].message.content
                
                # Parse JSON
                cleaned = raw_response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

                return VisualDirection.model_validate_json(cleaned)

            except Exception as exc:
                last_error = exc
                logger.warning(f"[VISUAL_DIRECTOR] Model {model} failed: {exc}")
                continue

        # All providers exhausted - fallback to a generic tech photo
        logger.error(f"[VISUAL_DIRECTOR] All providers failed. Returning default direction. Last error: {last_error}")
        return VisualDirection(
            visual_type="editorial_photo",
            subject="Abstract modern technology server room",
            scene="Clean, sophisticated data center",
            concept="Technology and engineering",
            composition="Cinematic wide shot with depth of field",
            lighting="Subtle blue and teal ambient lighting",
            style="Premium editorial photography, realistic",
            negative_prompt="text, typography, logos, watermarks, UI, screenshots, cartoons, illustrations"
        )
