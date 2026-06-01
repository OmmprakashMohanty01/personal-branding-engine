import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.services.publishing.orchestrator import PublishingOrchestrator

logger = logging.getLogger("branding_engine.scheduling.dispatch")

class DispatchService:
    """Scans and publishes mature approved drafts scheduled for distribution."""
    
    def __init__(self):
        self.orchestrator = PublishingOrchestrator()

    async def dispatch_mature_posts(self, db: AsyncSession) -> int:
        """Query and publish all drafts scheduled for publication in the past or present.
        
        Returns:
            int: The number of posts dispatched.
        """
        now_utc = datetime.now(timezone.utc)
        
        # Select APPROVED drafts scheduled for publication
        stmt = (
            select(ContentDraft)
            .where(
                ContentDraft.status == "APPROVED",
                ContentDraft.scheduled_for <= now_utc
            )
        )
        res = await db.execute(stmt)
        mature_drafts = res.scalars().all()
        
        if not mature_drafts:
            logger.info("No mature scheduled drafts require dispatch.")
            return 0
            
        logger.info(f"Found {len(mature_drafts)} mature drafts requiring dispatch.")
        dispatched_count = 0
        
        for draft in mature_drafts:
            # Optimistic Locking: Clear the scheduled_for time immediately to prevent concurrent triggers
            draft.scheduled_for = None
            db.add(draft)
            await db.flush()
            await db.commit() # Commit locking state before dispatching
            
            # Dispatch via PublishingOrchestrator
            try:
                logger.info(f"Dispatching draft {draft.id} for publishing on {draft.platform}.")
                # Hand off draft to PublishingOrchestrator
                await self.orchestrator.publish_draft(db, draft.id)
                dispatched_count += 1
            except Exception as e:
                logger.error(f"Failed to publish scheduled draft {draft.id}: {e}", exc_info=True)
                
        return dispatched_count
