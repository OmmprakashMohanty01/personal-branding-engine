import logging
import random
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.services.publishing.orchestrator import PublishingOrchestrator

# Configure the log output timestamps to use Asia/Kolkata (IST) timezone
def ist_converter(*args):
    tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz).timetuple()

logging.Formatter.converter = ist_converter

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
        tz_ist = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(tz_ist)
        
        logger.info(f"Scanning mature scheduled drafts at {now_ist.isoformat()} (IST).")
        
        # Normalize to UTC for SQL query to guarantee timezone string comparison safety in SQLite
        now_utc = now_ist.astimezone(timezone.utc)
        
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
        
        for idx, draft in enumerate(mature_drafts):
            # API Throttling: randomized sleep delay (2 to 7 seconds) between external network requests
            if idx > 0:
                delay = random.uniform(2.0, 7.0)
                logger.info(f"API Throttling: Sleeping for {delay:.2f} seconds before dispatching next draft...")
                await asyncio.sleep(delay)

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
