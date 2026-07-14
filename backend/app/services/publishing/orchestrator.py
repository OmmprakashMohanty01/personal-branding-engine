import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.client import LinkedInClient

logger = logging.getLogger("branding_engine.publishing.orchestrator")

class PublishingOrchestrator:
    """Orchestrates draft payload extraction, LinkedIn account lookup, and client dispatch."""
    
    def __init__(self):
        self.linkedin_client = LinkedInClient()

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

    async def publish_draft(self, db: AsyncSession, draft_id: str) -> ContentDraft:
        """Dispatch a draft directly to LinkedIn.
        
        Args:
            db: AsyncSession database handle.
            draft_id: The UUID of the draft to publish.
            
        Returns:
            The updated ContentDraft model with PUBLISHED or FAILED status.
        """
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")
            
        # Verify draft is not already published
        if draft.status == "PUBLISHED":
            raise ValueError(
                f"Cannot publish draft {draft_id}: Already published."
            )
            
        # Pre-flight Length Validation (LinkedIn limit is 3,000 characters)
        post_text = draft.content_text
        if len(post_text) > 3000:
            draft.status = "FAILED"
            await db.commit()
            await db.refresh(draft)
            raise ValueError(f"Pre-flight validation failed: LinkedIn post exceeds 3,000-character limit ({len(post_text)} characters).")

        try:
            account = await self._get_default_linkedin_account(db)
            
            image_url = (draft.llm_metadata or {}).get("image_url")
            # Dispatch to LinkedIn Post API
            post_urn = await self.linkedin_client.publish_post(db, account, post_text, image_url=image_url)
            
            # Mark status as PUBLISHED and log resulting share URN
            draft.status = "PUBLISHED"
            metadata = dict(draft.llm_metadata or {})
            metadata["linkedin_post_id"] = post_urn
            metadata["published_url"] = f"https://www.linkedin.com/feed/update/{post_urn}"
            draft.llm_metadata = metadata
            
            logger.info(f"Successfully published draft {draft_id} to LinkedIn. URN: {post_urn}")
        except Exception as e:
            logger.error(f"Failed to publish draft {draft_id} to LinkedIn: {e}")
            draft.status = "FAILED"
            raise e
        finally:
            await db.commit()
            await db.refresh(draft)
            
        return draft
