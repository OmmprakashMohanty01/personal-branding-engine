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

### CRITICAL RULE
The image must visualize the IDEA. It must NOT simply visualize the CATEGORY.
BAD: topic = FastAPI → generate computer
BAD: topic = cybersecurity → generate hacker
BAD: topic = AI → generate robot
BAD: topic = software → generate laptop
These are generic category associations and are NOT acceptable.

GOOD: Post: "External dependency shutdown broke our production architecture."
Visual concept: A production automation system continuing to operate after an external service connection has been severed.
GOOD: Post: "Platforms locking out privacy-focused operating systems."
Visual concept: A smartphone representing a privacy-focused operating system facing a closed platform gate / infrastructure dependency.

### NO TEXT-HEAVY IMAGES
For normal LinkedIn editorial images DO NOT generate:
- quote cards
- screenshots
- browser windows
- fake LinkedIn posts
- fake dashboards
- fake terminal screenshots
- giant typography
- paragraphs
- presentation slides
- text posters
Default image should contain ZERO readable text.

### NO GENERIC TECH STOCK PHOTOGRAPHY
Reject generic:
- laptop on desk
- monitor on desk
- programmer at computer
- server rack
- keyboard
- generic office
- random circuit board
unless that object is genuinely central to the story.

### VISUAL CATEGORIES
Implement semantic visual categories:
EDITORIAL_PHOTOGRAPHY
CONCEPTUAL_SCENE
TECHNOLOGY_ARTIFACT
ARCHITECTURE
PROCESS_DIAGRAM
DATA_VISUALIZATION
COMPARISON
PORTRAIT
PRODUCT_SCENE
The Director must select the category based on the actual post.

### EXAMPLES
Example A:
Post: "Platforms locking out privacy focused operating systems..."
visual_type: CONCEPTUAL_SCENE
core_subject: modern smartphone representing a privacy focused mobile operating system
visual_metaphor: a privacy focused device facing a closed digital platform boundary
scene: premium dark technology environment
style: editorial technology photography
negative_prompt: generic laptop, computer monitor, programmer, hacker, text, typography, screenshot, UI, browser window

Example B:
Post: "We stopped using manual workers and built autonomous fallback logic..."
visual_type: CONCEPTUAL_SCENE
core_subject: automated production pipeline
visual_metaphor: a central automated system continuing after an external dependency has been disconnected
scene: modern cloud infrastructure environment
style: premium enterprise technology editorial photography
negative_prompt: generic laptop, office desk, programmer, text, typography, screenshot, stock photo

Example C:
Post: "Why our PostgreSQL database became the source of truth..."
visual_type: TECHNOLOGY_ARTIFACT
core_subject: centralized data system
visual_metaphor: multiple services converging into one authoritative data layer
style: high-end technical editorial visualization

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{
  "visual_type": "Selected category",
  "core_subject": "The primary focus of the image",
  "visual_metaphor": "The metaphorical action or relationship",
  "scene": "The setting and context",
  "composition": "How the elements are arranged",
  "lighting": "Lighting details",
  "style": "Overall aesthetic",
  "negative_prompt": "Specific things to avoid"
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
            visual_type="EDITORIAL_PHOTOGRAPHY",
            core_subject="Abstract modern technology server room",
            visual_metaphor="Data flow and interconnected systems",
            scene="Clean, sophisticated data center",
            composition="Cinematic wide shot with depth of field",
            lighting="Subtle blue and teal ambient lighting",
            style="Premium editorial photography, realistic",
            negative_prompt="text, typography, logos, watermarks, UI, screenshots, cartoons, illustrations"
        )
