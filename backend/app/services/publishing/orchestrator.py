import logging
import smtplib
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount, XAccount, ThreadsAccount, SubstackAccount
from app.services.publishing.linkedin.client import LinkedInClient
from app.services.publishing.x.client import XClient, XPublishingError
from app.services.publishing.threads.client import ThreadsClient, ThreadsPublishingError
from app.services.publishing.substack.client import SubstackClient
from app.services.monitoring.alerts import AlertManager

logger = logging.getLogger("branding_engine.publishing.orchestrator")

class PublishingOrchestrator:
    """Orchestrates draft payload extraction, integration account lookup, client dispatch, and state tracking."""
    
    def __init__(self):
        self.linkedin_client = LinkedInClient()
        self.x_client = XClient()
        self.threads_client = ThreadsClient()
        self.substack_client = SubstackClient()
        self.alert_manager = AlertManager()

    async def _get_default_linkedin_account(self, db: AsyncSession) -> LinkedInAccount:
        """Fetch the default connected LinkedInAccount integration from DB."""
        stmt = select(LinkedInAccount)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        if not account:
            raise ValueError(
                "No connected LinkedIn integration account found. Please link your account first."
            )
        return account

    async def _get_default_x_account(self, db: AsyncSession) -> XAccount:
        """Fetch the default connected XAccount integration from DB."""
        stmt = select(XAccount)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        if not account:
            raise ValueError(
                "No connected X integration account found. Please link your account first."
            )
        return account

    async def _get_default_threads_account(self, db: AsyncSession) -> ThreadsAccount:
        """Fetch the default connected ThreadsAccount integration from DB."""
        stmt = select(ThreadsAccount)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        if not account:
            raise ValueError(
                "No connected Threads integration account found. Please link your account first."
            )
        return account

    async def _get_default_substack_account(self, db: AsyncSession) -> SubstackAccount:
        """Fetch the default configured SubstackAccount integration from DB."""
        stmt = select(SubstackAccount)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        if not account:
            raise ValueError(
                "No configured Substack integration account found. Please configure your newsletter integration first."
            )
        return account

    async def publish_draft(self, db: AsyncSession, draft_id: str) -> ContentDraft:
        """Dispatch an approved draft to its target publication network.
        
        Args:
            db: AsyncSession database handle.
            draft_id: The UUID of the draft to publish.
            
        Returns:
            The updated ContentDraft model with PUBLISHED or FAILED_PUBLISHING status.
        """
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")
            
        # Verify draft is in APPROVED status
        if draft.status != "APPROVED":
            raise ValueError(
                f"Cannot publish draft {draft_id}: Current status is '{draft.status}', must be 'APPROVED'."
            )
            
        # Validate platform support
        platform_lower = draft.platform.lower()
        if platform_lower not in ("linkedin", "x", "threads", "substack"):
            raise ValueError(
                f"Platform '{draft.platform}' publishing is not implemented yet. Only 'linkedin', 'x', 'threads', and 'substack' are active."
            )
            
        # Determine draft copy, falling back to content_text if final_content edit is empty
        post_text = draft.final_content if draft.final_content else draft.content_text

        if platform_lower == "linkedin":
            try:
                account = await self._get_default_linkedin_account(db)
                
                # Dispatch to LinkedIn Post API
                post_urn = await self.linkedin_client.publish_post(db, account, post_text)
                
                # Mark status as PUBLISHED and log resulting share URN
                draft.status = "PUBLISHED"
                metadata = dict(draft.llm_metadata or {})
                metadata["linkedin_post_id"] = post_urn
                metadata["published_url"] = f"https://www.linkedin.com/feed/update/{post_urn}"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                logger.info(f"Successfully published draft {draft_id} to LinkedIn. Post URN: {post_urn}")
                return draft
                
            except Exception as e:
                # Capture error, transition state, and save stack trace/message for review
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} to LinkedIn: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"Publishing failed: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed: LinkedIn post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                await db.commit()
                await db.refresh(draft)
                return draft
        elif platform_lower == "x":
            try:
                account = await self._get_default_x_account(db)
                
                # Dispatch to X Tweets API
                tweet_ids = await self.x_client.publish_post(db, account, post_text)
                
                # Mark status as PUBLISHED and log resulting tweet IDs
                draft.status = "PUBLISHED"
                metadata = dict(draft.llm_metadata or {})
                metadata["x_tweet_ids"] = tweet_ids
                if tweet_ids:
                    metadata["published_url"] = f"https://x.com/i/web/status/{tweet_ids[0]}"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                logger.info(f"Successfully published draft {draft_id} to X. Tweet IDs: {tweet_ids}")
                return draft
                
            except XPublishingError as e:
                # Capture partial thread failure
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} completely to X: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"Publishing failed mid-way: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed (Partial Thread): X post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                # Log any successfully posted tweet IDs
                metadata = dict(draft.llm_metadata or {})
                metadata["x_tweet_ids"] = e.published_tweet_ids
                if e.published_tweet_ids:
                    metadata["published_url"] = f"https://x.com/i/web/status/{e.published_tweet_ids[0]}"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                return draft
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} to X: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"Publishing failed: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed: X post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                await db.commit()
                await db.refresh(draft)
                return draft
        elif platform_lower == "threads":
            try:
                account = await self._get_default_threads_account(db)
                
                # Dispatch to Threads Graph API
                post_ids = await self.threads_client.publish_post(db, account, post_text)
                
                # Mark status as PUBLISHED and log resulting post IDs
                draft.status = "PUBLISHED"
                metadata = dict(draft.llm_metadata or {})
                metadata["threads_post_ids"] = post_ids
                if post_ids:
                    metadata["published_url"] = f"https://www.threads.net/@{account.username}/post/{post_ids[0]}"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                logger.info(f"Successfully published draft {draft_id} to Threads. Post IDs: {post_ids}")
                return draft
                
            except ThreadsPublishingError as e:
                # Capture partial thread and/or orphan container failure
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} completely to Threads: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                if e.creation_id:
                    draft.feedback_notes = f"Publishing failed mid-way: {error_msg}. Orphan container creation_id: {e.creation_id}"
                else:
                    draft.feedback_notes = f"Publishing failed mid-way: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed (Partial Thread): Threads post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                # Log any successfully posted post IDs
                metadata = dict(draft.llm_metadata or {})
                metadata["threads_post_ids"] = e.published_post_ids
                if e.published_post_ids:
                    metadata["published_url"] = f"https://www.threads.net/@{account.username}/post/{e.published_post_ids[0]}"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                return draft
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} to Threads: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"Publishing failed: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed: Threads post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                await db.commit()
                await db.refresh(draft)
                return draft
        else: # platform_lower == "substack"
            try:
                account = await self._get_default_substack_account(db)
                
                # Dispatch to Substack via SMTP email
                await self.substack_client.publish_post(db, account, post_text)
                
                # Mark status as PUBLISHED
                draft.status = "PUBLISHED"
                metadata = dict(draft.llm_metadata or {})
                metadata["substack_dispatch"] = "Successfully sent post via email-to-publish draft ingestion."
                metadata["published_url"] = "https://substack.com"
                draft.llm_metadata = metadata
                
                await db.commit()
                await db.refresh(draft)
                logger.info(f"Successfully published draft {draft_id} to Substack via email-to-publish.")
                return draft
                
            except smtplib.SMTPException as e:
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} to Substack (SMTP Exception): {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"SMTP publishing failed: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed (SMTP Substack): Draft {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                await db.commit()
                await db.refresh(draft)
                return draft
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Failed to publish draft {draft_id} to Substack: {error_msg}")
                
                draft.status = "FAILED_PUBLISHING"
                draft.feedback_notes = f"Publishing failed: {error_msg}"
                
                # Trigger fire-and-forget critical alert
                asyncio.create_task(
                    self.alert_manager.send_alert(
                        f"Publishing Failed: Substack post {draft_id} failed: {error_msg}",
                        "CRITICAL"
                    )
                )
                
                await db.commit()
                await db.refresh(draft)
                return draft
