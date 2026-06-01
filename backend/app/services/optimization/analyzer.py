import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft, PostAnalytics

logger = logging.getLogger("branding_engine.optimization.analyzer")

class FeedbackAnalyzer:
    """Processes historical draft edits, rejections, and analytics to extract improvement insights."""
    
    async def gather_feedback_data(self, db: AsyncSession, persona_id: str, platform: str) -> dict:
        """Query and filter historical content records for optimization inputs.
        
        Args:
            db: AsyncSession database handle.
            persona_id: Target Persona UUID.
            platform: Targeted social network platform ('x', 'linkedin', 'threads', 'substack').
            
        Returns:
            dict containing:
                - human_corrections: list of dicts with {"original": str, "edited": str}
                - rejections: list of strings (feedback notes)
                - viral_successes: list of dicts with {"content": str, "likes": int, "views": int}
        """
        plat_lower = platform.lower()
        
        # 1. Gather Human Corrections: Drafts where the editor corrected style/details before publishing.
        corrections_stmt = (
            select(ContentDraft)
            .where(
                ContentDraft.persona_id == persona_id,
                ContentDraft.platform == plat_lower,
                ContentDraft.final_content.is_not(None),
                ContentDraft.final_content != "",
                ContentDraft.final_content != ContentDraft.content_text
            )
            .order_by(ContentDraft.updated_at.desc())
            .limit(10)
        )
        corrections_res = await db.execute(corrections_stmt)
        corrections = corrections_res.scalars().all()
        
        human_corrections = [
            {"original": c.content_text, "edited": c.final_content}
            for c in corrections
        ]
        
        # 2. Gather Rejections: Feedbacks notes explaining what not to write.
        rejections_stmt = (
            select(ContentDraft)
            .where(
                ContentDraft.persona_id == persona_id,
                ContentDraft.platform == plat_lower,
                ContentDraft.status == "REJECTED",
                ContentDraft.feedback_notes.is_not(None),
                ContentDraft.feedback_notes != ""
            )
            .order_by(ContentDraft.updated_at.desc())
            .limit(10)
        )
        rejections_res = await db.execute(rejections_stmt)
        rejections = rejections_res.scalars().all()
        
        rejection_notes = [r.feedback_notes for r in rejections]
        
        # 3. Gather Viral Successes: Top 10% highest likes or views.
        successes_stmt = (
            select(ContentDraft, PostAnalytics)
            .join(PostAnalytics, PostAnalytics.draft_id == ContentDraft.id)
            .where(
                ContentDraft.persona_id == persona_id,
                ContentDraft.platform == plat_lower,
                ContentDraft.status == "PUBLISHED"
            )
        )
        successes_res = await db.execute(successes_stmt)
        pairs = successes_res.all()
        
        viral_successes = []
        if pairs:
            likes = [p[1].likes for p in pairs]
            views = [p[1].views for p in pairs]
            
            likes.sort(reverse=True)
            views.sort(reverse=True)
            
            # Identify cutoff for top 10%
            n = len(pairs)
            idx = max(0, int(n * 0.1) - 1)
            
            likes_cutoff = likes[idx] if likes else 0
            views_cutoff = views[idx] if views else 0
            
            for draft, analytics in pairs:
                # Include if it has non-zero engagement and is at/above top 10% cutoff
                if (analytics.likes > 0 or analytics.views > 0) and (analytics.likes >= likes_cutoff or analytics.views >= views_cutoff):
                    viral_successes.append({
                        "content": draft.final_content or draft.content_text,
                        "likes": analytics.likes,
                        "views": analytics.views
                    })
                    
        logger.info(
            f"Feedback Aggregated for Persona {persona_id} on {platform}: "
            f"{len(human_corrections)} corrections, {len(rejection_notes)} rejections, {len(viral_successes)} successes."
        )
        
        return {
            "human_corrections": human_corrections,
            "rejections": rejection_notes,
            "viral_successes": viral_successes
        }
