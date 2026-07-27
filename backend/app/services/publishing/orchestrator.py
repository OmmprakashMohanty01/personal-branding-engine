import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.client import LinkedInClient
from app.services.generation.circuit_breaker import execute_with_retry

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
        logger.info(
            "Publishing with LinkedIn account",
            extra={
                "account_id": account.id,
                "person_urn": account.linkedin_person_urn,
            },
        )
        return account

    async def publish_draft(self, db: AsyncSession, draft_id: str, trace_id: str | None = None) -> ContentDraft:
        """Dispatch a draft directly to LinkedIn.
        
        Args:
            db: AsyncSession database handle.
            draft_id: The UUID of the draft to publish.
            trace_id: Optional trace identifier for logging.
            
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
            
        # Pre-flight Length Validation (LinkedIn limit is 3,000 characters, min 10)
        post_text = draft.content_text
        text_len = len(post_text) if post_text else 0
        
        logger.info(f"[PUBLISH PRE-FLIGHT] Draft {draft_id} text length: {text_len} chars. trace_id={trace_id}")
        
        if text_len > 3000:
            draft.status = "FAILED"
            await db.commit()
            await db.refresh(draft)
            raise ValueError(f"Pre-flight validation failed: LinkedIn post exceeds 3,000-character limit ({text_len} characters).")
            
        if text_len < 10:
            draft.status = "FAILED"
            await db.commit()
            await db.refresh(draft)
            raise ValueError(f"Pre-flight validation failed: LinkedIn post is suspiciously short or empty ({text_len} characters).")

        metadata = draft.llm_metadata or {}
        requires_image = metadata.get("requires_image")
        image_url = metadata.get("image_url")
        
        if requires_image and not image_url:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Image generated but not saved to database. Please click 'Save Changes' before publishing."
            )

        try:
            account = await self._get_default_linkedin_account(db)
            
            # Dispatch to LinkedIn Post API with selective retry policy and idempotency key
            async def _publish():
                return await self.linkedin_client.publish_post(
                    db=db,
                    account=account,
                    text=post_text,
                    image_url=image_url,
                    idempotency_key=draft_id
                )
            
            post_urn = await execute_with_retry(
                _publish,
                max_retries=3,
                initial_backoff=2.0
            )
            
            if not post_urn:
                logger.error(f"[ASSERTION FAILED] LinkedIn publish returned no post_urn for draft {draft_id}.")
                raise RuntimeError("Publish succeeded but no post ID was returned.")
            
            # Mark status as PUBLISHED and log resulting share URN
            draft.status = "PUBLISHED"
            metadata = dict(draft.llm_metadata or {})
            metadata["linkedin_post_id"] = post_urn
            metadata["published_url"] = f"https://www.linkedin.com/feed/update/{post_urn}"
            draft.llm_metadata = metadata
            
            logger.info(f"Successfully published draft {draft_id} to LinkedIn. URN: {post_urn} trace_id={trace_id}")
        except Exception as e:
            logger.error(f"Failed to publish draft {draft_id} to LinkedIn: {e} trace_id={trace_id}")
            draft.status = "FAILED"
            raise e
        finally:
            await db.commit()
            await db.refresh(draft)
            
        return draft
