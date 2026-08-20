import logging
from typing import Optional
from app.services.llm_provider import GeminiProvider

logger = logging.getLogger("branding_engine.generation.image_director")

class ImageDirector:
    """
    Dedicated LLM prompt stage that translates a post's core thesis into a realistic 
    corporate-grade editorial photo concept.
    """
    
    def __init__(self, provider: Optional[GeminiProvider] = None):
        # We instantiate a GeminiProvider dynamically if none is provided.
        self.llm = provider or GeminiProvider()
        
        self.system_instruction = (
            "You are an Art Director for a high-end technology publication (like Wired or Bloomberg). "
            "Your job is to convert a software engineering post into a physical, realistic editorial photography prompt. \n"
            "STRICT RULES:\n"
            "- NO fantasy, NO cartoons, NO glowing cyberpunk neon, NO floating holographic cubes.\n"
            "- NO literal robots or humanoid AI figures.\n"
            "- Focus on realistic, tangible subjects: high-end data infrastructure, precision architectural lines, "
            "minimalist workspaces with natural light, physical networking gear, or clean industrial engineering.\n"
            "- Color palette: Restrained graphite, slate, navy, brushed aluminum, and natural daylight.\n\n"
            "Output Format: Return ONLY the finalized prompt string wrapped in the editorial style prefix:\n"
            "Editorial corporate technology photography, [CONCEPTUAL_PHYSICAL_SCENE], natural daylight, 35mm lens, depth of field, minimalist composition, 8k resolution"
        )

    async def generate_prompt(self, core_topic: str) -> str:
        """
        Generates an editorial photography brief for a given core topic.
        """
        logger.info(f"[IMAGE DIRECTOR] Formulating editorial brief for topic: {core_topic[:50]}...")
        try:
            # We enforce a smaller token limit as it's just a short image prompt.
            prompt = await self.llm.generate(
                prompt=f"Topic: {core_topic}", 
                system_instruction=self.system_instruction,
                max_tokens=150,
                temperature=0.4
            )
            return prompt.strip()
        except Exception as e:
            logger.warning(f"[IMAGE DIRECTOR] Failed to generate brief: {e}. Falling back to default.")
            return "Editorial corporate technology photography, minimalist workspaces with natural light, physical networking gear, natural daylight, 35mm lens, depth of field, minimalist composition, 8k resolution"
