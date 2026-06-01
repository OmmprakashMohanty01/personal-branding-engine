import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.services.approval.state_machine import ApprovalStateMachine

logger = logging.getLogger("branding_engine.approval.service")

class ApprovalService:
    """Manages business operations for approving, rejecting, and revising content drafts."""
    
    async def get_pending(self, db: AsyncSession, platform: Optional[str] = None) -> List[ContentDraft]:
        """Fetch drafts awaiting review (DRAFT or PENDING_APPROVAL), sorted by generation date."""
        stmt = select(ContentDraft).where(ContentDraft.status.in_(["DRAFT", "PENDING_APPROVAL"]))
        
        if platform:
            stmt = stmt.where(ContentDraft.platform == platform.lower())
            
        stmt = stmt.order_by(ContentDraft.generated_at.desc())
        res = await db.execute(stmt)
        return res.scalars().all()

    async def approve_draft(self, db: AsyncSession, draft_id: str, edited_text: Optional[str] = None) -> ContentDraft:
        """Approve a draft post and record the final content text."""
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")
            
        # Verify transition rules
        ApprovalStateMachine.validate_transition(draft.status, "APPROVED")
        
        # Save edited content, fallback to original if not overridden by human editor
        draft.final_content = edited_text if edited_text is not None else draft.content_text
        draft.status = "APPROVED"
        draft.approved_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(draft)
        logger.info(f"Draft {draft_id} successfully approved.")
        return draft

    async def reject_draft(self, db: AsyncSession, draft_id: str, reason: str) -> ContentDraft:
        """Reject a draft post, logging the feedback reason."""
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")
            
        # Verify transition rules
        ApprovalStateMachine.validate_transition(draft.status, "REJECTED")
        
        draft.status = "REJECTED"
        draft.feedback_notes = reason
        
        await db.commit()
        await db.refresh(draft)
        logger.info(f"Draft {draft_id} successfully rejected. Reason: {reason}")
        return draft

    async def request_revision(self, db: AsyncSession, draft_id: str, feedback: str) -> ContentDraft:
        """Request a fresh draft revision based on feedback notes."""
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")
            
        # Verify transition rules: DRAFT/PENDING_APPROVAL/REJECTED -> PENDING_APPROVAL
        ApprovalStateMachine.validate_transition(draft.status, "PENDING_APPROVAL")
        
        # Local import to prevent circular import issues
        from app.services.generation.orchestrator import GenerationOrchestrator
        orchestrator = GenerationOrchestrator()
        
        # Generate new draft variant using feedback notes
        new_variant = await orchestrator.generate_draft(
            db=db,
            trend_id=draft.trend_id,
            platform=draft.platform,
            persona_id=draft.persona_id,
            feedback=feedback
        )
        
        # Update existing record and delete the newly generated duplicate record
        draft.content_text = new_variant.content_text
        draft.llm_metadata = new_variant.llm_metadata
        draft.status = "PENDING_APPROVAL"
        draft.feedback_notes = feedback
        draft.generated_at = datetime.now(timezone.utc)
        
        await db.delete(new_variant)
        await db.commit()
        await db.refresh(draft)
        
        logger.info(f"Draft {draft_id} successfully revised based on feedback.")
        return draft
