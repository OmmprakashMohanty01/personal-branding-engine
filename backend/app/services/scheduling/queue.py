import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.models.scheduling import ScheduleConfig

logger = logging.getLogger("branding_engine.scheduling.queue")

class QueueManager:
    """Calculates and assigns timezone-safe publishing schedules to approved drafts."""
    
    async def assign_schedules(self, db: AsyncSession) -> int:
        """Scan APPROVED drafts with no scheduled_for timestamp and assign the next optimal slot.
        
        Returns:
            int: The number of drafts successfully scheduled.
        """
        # Fetch APPROVED drafts with no schedule
        stmt = (
            select(ContentDraft)
            .where(
                ContentDraft.status == "APPROVED",
                ContentDraft.scheduled_for == None
            )
            .order_by(ContentDraft.approved_at.asc() if hasattr(ContentDraft, "approved_at") else ContentDraft.created_at.asc())
        )
        res = await db.execute(stmt)
        unscheduled_drafts = res.scalars().all()
        
        if not unscheduled_drafts:
            logger.info("No unscheduled approved drafts found.")
            return 0
            
        scheduled_count = 0
        
        for draft in unscheduled_drafts:
            # 1. Fetch relevant ScheduleConfig
            config_stmt = (
                select(ScheduleConfig)
                .where(
                    ScheduleConfig.persona_id == draft.persona_id,
                    ScheduleConfig.platform == draft.platform.lower(),
                    ScheduleConfig.is_active == True
                )
            )
            config_res = await db.execute(config_stmt)
            config = config_res.scalars().first()
            
            # Default fallback if no config exists
            if not config:
                logger.info(f"No active ScheduleConfig found for persona {draft.persona_id} on {draft.platform}. Using default UTC slots.")
                posting_times = ["09:00", "12:00", "15:00", "18:00"]
                tz_name = "UTC"
            else:
                posting_times = config.posting_times_json or ["09:00", "12:00", "15:00", "18:00"]
                tz_name = config.timezone or "UTC"
                
            # 2. Get local timezone or fallback to UTC
            try:
                tz = ZoneInfo(tz_name)
            except ZoneInfoNotFoundError:
                logger.warning(f"Timezone '{tz_name}' not found. Falling back to UTC.")
                tz = ZoneInfo("UTC")
                
            # Compute next available slot
            now_utc = datetime.now(timezone.utc)
            slot_assigned = False
            days_offset = 0
            
            # Query all future scheduled times for this platform to prevent collisions
            scheduled_stmt = (
                select(ContentDraft.scheduled_for)
                .where(
                    ContentDraft.platform == draft.platform.lower(),
                    ContentDraft.scheduled_for > now_utc
                )
            )
            scheduled_res = await db.execute(scheduled_stmt)
            existing_schedules = {s.replace(tzinfo=timezone.utc) for s in scheduled_res.scalars().all() if s}
            
            # Loop day by day, slot by slot until we find an unoccupied future slot
            while not slot_assigned and days_offset < 30: # Limit lookup to 30 days to avoid infinite loops
                target_date = now_utc.astimezone(tz) + timedelta(days=days_offset)
                
                # Check each posting time configured
                for time_str in posting_times:
                    try:
                        hour, minute = map(int, time_str.split(":"))
                    except ValueError:
                        continue # Skip malformed times
                        
                    slot_local = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    slot_utc = slot_local.astimezone(timezone.utc)
                    
                    # Slot must be in the future
                    if slot_utc <= now_utc:
                        continue
                        
                    # Slot must not conflict with already scheduled posts on this platform (within 1 minute range)
                    conflict = False
                    for existing in existing_schedules:
                        if abs((existing - slot_utc).total_seconds()) < 60:
                            conflict = True
                            break
                            
                    if not conflict:
                        draft.scheduled_for = slot_utc
                        db.add(draft)
                        await db.flush()
                        
                        # Add newly scheduled slot to local cache to prevent scheduling two in-flight drafts for same slot
                        existing_schedules.add(slot_utc)
                        slot_assigned = True
                        scheduled_count += 1
                        logger.info(f"Draft {draft.id} scheduled for {slot_utc} (Local: {slot_local} {tz_name})")
                        break
                        
                days_offset += 1
                
        await db.commit()
        return scheduled_count
