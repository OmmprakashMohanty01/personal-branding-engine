import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft, PostAnalytics
from app.models.integration import XAccount
from app.services.publishing.x.client import XClient

logger = logging.getLogger("branding_engine.analytics.syncer")

class EngagementSyncer:
    """Synchronizes external platform engagement metrics (likes, shares, comments, views) for published posts."""
    
    def __init__(self):
        self.x_client = XClient()

    async def sync_engagement(self, db: AsyncSession) -> int:
        """Fetch and synchronize engagement metrics for posts published in the last 7 days.
        
        Sync conditions:
            - ContentDraft.status == 'PUBLISHED'
            - ContentDraft.updated_at >= 7 days ago
            - PostAnalytics record doesn't exist OR was last synced > 6 hours ago.
            
        Returns:
            int: The number of posts synchronized.
        """
        now_time = datetime.now(timezone.utc)
        cutoff = now_time - timedelta(days=7)
        sync_threshold = now_time - timedelta(hours=6)
        
        # Query drafts that meet criteria
        stmt = (
            select(ContentDraft)
            .outerjoin(PostAnalytics, PostAnalytics.draft_id == ContentDraft.id)
            .where(
                ContentDraft.status == "PUBLISHED",
                ContentDraft.updated_at >= cutoff
            )
            .where(
                (PostAnalytics.id == None) | (PostAnalytics.last_synced_at <= sync_threshold)
            )
            .order_by(ContentDraft.updated_at.desc())
            .limit(50)
        )
        
        res = await db.execute(stmt)
        drafts = res.scalars().all()
        
        if not drafts:
            logger.info("No published posts meet the synchronization criteria.")
            return 0
            
        logger.info(f"Found {len(drafts)} published posts requiring engagement synchronization.")
        
        # Group by platform
        x_drafts = [d for d in drafts if d.platform.lower() == "x"]
        non_x_drafts = [d for d in drafts if d.platform.lower() in ("linkedin", "threads", "substack")]
        
        synced_count = 0
        
        # 1. Sync X Platform Posts in Batch
        if x_drafts:
            try:
                # Retrieve default XAccount
                acc_stmt = select(XAccount)
                acc_res = await db.execute(acc_stmt)
                x_account = acc_res.scalars().first()
                
                if not x_account:
                    logger.warning("No connected X account found. Skipping API sync for X posts.")
                    # Fallback to stubbing/updating timestamp for X drafts so we don't loop forever
                    for draft in x_drafts:
                        await self._stub_or_update_timestamp(db, draft)
                        synced_count += 1
                else:
                    # Gather all tweet IDs and link them back to their drafts
                    tweet_id_to_draft = {}
                    all_tweet_ids = []
                    
                    for draft in x_drafts:
                        metadata = draft.llm_metadata or {}
                        tids = metadata.get("x_tweet_ids", [])
                        if isinstance(tids, list):
                            for tid in tids:
                                tweet_id_to_draft[tid] = draft
                                all_tweet_ids.append(str(tid))
                        elif isinstance(tids, str) and tids:
                            tweet_id_to_draft[tids] = draft
                            all_tweet_ids.append(tids)
                            
                    if all_tweet_ids:
                        logger.info(f"Batch querying {len(all_tweet_ids)} tweet IDs from X API.")
                        metrics_res = await self.x_client.fetch_tweet_metrics(db, x_account, all_tweet_ids)
                        
                        # Aggregate metrics by draft_id
                        # (A single draft could be a thread with multiple tweet IDs; we sum metrics for threads)
                        draft_metrics = {} # draft_id -> dict
                        
                        tweets_data = metrics_res.get("data", [])
                        for tweet_data in tweets_data:
                            tid = str(tweet_data.get("id"))
                            public_metrics = tweet_data.get("public_metrics", {})
                            draft = tweet_id_to_draft.get(tid)
                            if draft:
                                if draft.id not in draft_metrics:
                                    draft_metrics[draft.id] = {"likes": 0, "shares": 0, "comments": 0, "views": 0}
                                    
                                draft_metrics[draft.id]["likes"] += public_metrics.get("like_count", 0)
                                draft_metrics[draft.id]["shares"] += (
                                    public_metrics.get("retweet_count", 0) + 
                                    public_metrics.get("quote_count", 0)
                                )
                                draft_metrics[draft.id]["comments"] += public_metrics.get("reply_count", 0)
                                draft_metrics[draft.id]["views"] += public_metrics.get("impression_count", 0)
                                
                        # Update database for X drafts
                        for draft in x_drafts:
                            m = draft_metrics.get(draft.id, {"likes": 0, "shares": 0, "comments": 0, "views": 0})
                            pa_stmt = select(PostAnalytics).where(PostAnalytics.draft_id == draft.id)
                            pa_res = await db.execute(pa_stmt)
                            pa = pa_res.scalars().first()
                            
                            if not pa:
                                pa = PostAnalytics(
                                    draft_id=draft.id,
                                    likes=m["likes"],
                                    shares=m["shares"],
                                    comments=m["comments"],
                                    views=m["views"],
                                    last_synced_at=datetime.now(timezone.utc)
                                )
                                db.add(pa)
                            else:
                                pa.likes = m["likes"]
                                pa.shares = m["shares"]
                                pa.comments = m["comments"]
                                pa.views = m["views"]
                                pa.last_synced_at = datetime.now(timezone.utc)
                            await db.flush()
                            synced_count += 1
                    else:
                        logger.warning("No tweet IDs found in metadata for X drafts requiring sync.")
                        # Stub to avoid loop
                        for draft in x_drafts:
                            await self._stub_or_update_timestamp(db, draft)
                            synced_count += 1
            except Exception as e:
                logger.error(f"Error occurred during X engagement sync (OAuth/API issues): {str(e)}")
                # We update timestamps for X drafts to prevent sync loop crash
                for draft in x_drafts:
                    await self._stub_or_update_timestamp(db, draft)
                    synced_count += 1
                    
        # 2. Sync Non-X Platforms (LinkedIn, Threads, Substack)
        # Free-tier APIs are stubbed to prevent sync loops and log warnings.
        for draft in non_x_drafts:
            logger.info(f"Skipping external API sync for {draft.platform} draft {draft.id}. Stubbing/updating metrics.")
            await self._stub_or_update_timestamp(db, draft)
            synced_count += 1
            
        await db.commit()
        logger.info(f"Successfully synchronized {synced_count} published posts.")
        return synced_count

    async def _stub_or_update_timestamp(self, db: AsyncSession, draft: ContentDraft):
        """Helper to create initial 0 metrics or update last_synced_at on skipped/failed platforms."""
        pa_stmt = select(PostAnalytics).where(PostAnalytics.draft_id == draft.id)
        pa_res = await db.execute(pa_stmt)
        pa = pa_res.scalars().first()
        
        if not pa:
            pa = PostAnalytics(
                draft_id=draft.id,
                likes=0,
                shares=0,
                comments=0,
                views=0,
                last_synced_at=datetime.now(timezone.utc)
            )
            db.add(pa)
        else:
            pa.last_synced_at = datetime.now(timezone.utc)
        await db.flush()
