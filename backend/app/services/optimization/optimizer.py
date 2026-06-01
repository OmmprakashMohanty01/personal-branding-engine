import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import Persona
from app.models.optimization import OptimizationFeedback
from app.services.llm_provider import FallbackLLMProvider
from app.services.optimization.analyzer import FeedbackAnalyzer

logger = logging.getLogger("branding_engine.optimization.optimizer")

class PromptOptimizer:
    """Orchestrates analysis of historical metrics and revision histories to optimize persona generation prompts."""
    
    def __init__(self):
        self.analyzer = FeedbackAnalyzer()
        # Initialize fallback provider to reach Groq or Gemini models
        self.llm_provider = FallbackLLMProvider()

    async def optimize_prompt(self, db: AsyncSession, persona_id: str, platform: str) -> OptimizationFeedback:
        """Processes historical metrics and revisions, generates optimized rules, and saves them.
        
        Args:
            db: AsyncSession database handle.
            persona_id: Target Persona UUID.
            platform: Platform name ('x', 'linkedin', 'threads', 'substack').
            
        Returns:
            OptimizationFeedback: The newly created active optimization prompt record.
        """
        plat_lower = platform.lower()
        
        # 1. Fetch the Persona
        persona_stmt = select(Persona).where(Persona.id == persona_id)
        persona_res = await db.execute(persona_stmt)
        persona = persona_res.scalars().first()
        if not persona:
            raise ValueError(f"Persona with ID {persona_id} not found.")
            
        # 2. Gather feedback metrics/deltas
        data = await self.analyzer.gather_feedback_data(db, persona_id, plat_lower)
        
        human_corrections = data.get("human_corrections", [])
        rejections = data.get("rejections", [])
        viral_successes = data.get("viral_successes", [])
        
        # If there is absolutely no feedback, edits, or successes, return an empty/default optimization block
        if not human_corrections and not rejections and not viral_successes:
            logger.info(f"No historical revision or engagement data found for persona {persona_id} on {platform}. Skipping LLM optimization.")
            # Still save a default note to prevent repetitive optimizer executions
            optimized_prompt = (
                f"\n\n### Historical Style Adjustments for {platform.upper()}:\n"
                "- (No style corrections applied yet. Standard persona instructions are fully active.)"
            )
        else:
            # 3. Compile meta-prompt context
            corrections_str = ""
            for idx, c in enumerate(human_corrections):
                corrections_str += f"Correction #{idx + 1}:\n- Original Text Generated: {c['original']}\n- Human Corrected To: {c['edited']}\n\n"
                
            rejections_str = ""
            for idx, r in enumerate(rejections):
                rejections_str += f"Rejection #{idx + 1} Feedback Notes: {r}\n"
                
            successes_str = ""
            for idx, s in enumerate(viral_successes):
                successes_str += f"Viral Post #{idx + 1} (Likes: {s['likes']}, Views: {s['views']}):\n{s['content']}\n\n"
                
            meta_prompt = f"""You are a meta-prompt engineering agent. Analyze the historical performance, rejections, and human edits for platform {platform.upper()} and Persona guidelines below.

BASE PERSONA GUIDELINES:
Name: {persona.name}
Tone: {persona.tone_description}
Vocabulary Rules: {persona.vocabulary_rules}
Formatting Preferences: {persona.formatting_preferences}

We need to optimize the system prompt by creating a set of concise, actionable, imperative style rules. These rules must guide future generations to match the human editor's exact corrections, avoid rejections, and mimic viral success structures.

Here is the historical performance data:

--- HUMAN CORRECTIONS (What style/text the human editor keeps correcting in our drafts) ---
{corrections_str or "No corrections recorded yet."}

--- REJECTED DRAFTS (Negative feedback notes to avoid) ---
{rejections_str or "No rejections recorded yet."}

--- VIRAL SUCCESS POSTS (High engagement structures to emulate) ---
{successes_str or "No high engagement metrics recorded yet."}

---
Based on this raw feedback, generate a clear, concise instruction block labeled "### Historical Style Adjustments for {platform.upper()}:".
It must contain:
1. List of strictly imperative style constraints to guide the LLM's next content generation run (e.g. "Stop using hashtags", "Keep headlines under 5 words", "Ensure the first line has exactly one emoji").
2. Explicit formatting rules based on human corrections and rejections.

Keep your response extremely focused and professional. Do NOT include pleasantries, preambles, or conversational commentary. Start directly with the markdown header "### Historical Style Adjustments for {platform.upper()}:".
"""
            
            # 4. Invoke LLM
            logger.info(f"Invoking LLM to generate optimized system prompt for persona {persona_id} on {platform}.")
            optimized_prompt = await self.llm_provider.generate(
                prompt=meta_prompt,
                system_instruction="You are a professional prompt engineering optimizer. You respond strictly with rule-based markdown prompt extensions.",
                temperature=0.3,
                max_tokens=800
            )
            
        # 5. Mark older optimization feedback records for this persona & platform as inactive
        deactivate_stmt = (
            select(OptimizationFeedback)
            .where(
                OptimizationFeedback.persona_id == persona_id,
                OptimizationFeedback.platform == plat_lower,
                OptimizationFeedback.is_active == True
            )
        )
        deactivate_res = await db.execute(deactivate_stmt)
        old_feedbacks = deactivate_res.scalars().all()
        for old in old_feedbacks:
            old.is_active = False
            
        # 6. Save the new active OptimizationFeedback
        feedback_record = OptimizationFeedback(
            persona_id=persona_id,
            platform=plat_lower,
            optimized_system_prompt=optimized_prompt.strip(),
            generated_at=datetime.now(timezone.utc),
            is_active=True
        )
        db.add(feedback_record)
        await db.commit()
        await db.refresh(feedback_record)
        
        logger.info(f"Successfully saved new active optimized prompt for persona {persona_id} on {platform}.")
        return feedback_record
