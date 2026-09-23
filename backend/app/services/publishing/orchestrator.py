"""
orchestrator.py
===============
Omni-Channel Publishing Orchestrator with asyncio.gather parallel fan-out.

Publishes simultaneously to LinkedIn, Reddit, X (Twitter), Medium, and Dev.to.
Each platform is failure-isolated: a crash on one never blocks the others.
"""

import asyncio
import copy
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified

from app.models.content import ContentDraft
from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.client import LinkedInClient
from app.services.publishing.reddit.client import RedditClient
from app.services.publishing.x.client import XClient
from app.services.publishing.medium.client import MediumClient
from app.services.publishing.devto.client import DevToClient
from app.services.publishing.base import AuthenticationError

logger = logging.getLogger("branding_engine.publishing.orchestrator")


async def _publish_single_platform(name: str, coro) -> tuple[str, dict]:
    """Execute a single platform publish coroutine with full error isolation."""
    try:
        url = await coro
        logger.info(f"Successfully published to {name}: {url}")
        return name, {"status": "SUCCESS", "url": url}
    except AuthenticationError as e:
        logger.error(f"[{name}] auth failed: {e}")
        return name, {"status": "AUTH_EXPIRED", "error": str(e)}
    except Exception as e:
        logger.error(f"[{name}] publish failed: {e}")
        return name, {"status": "FAILED", "error": str(e)}


class PublishingOrchestrator:
    """Orchestrates draft payload extraction and multi-platform client dispatch."""

    def __init__(self):
        self.linkedin_client = LinkedInClient()
        self.reddit_client = RedditClient()
        self.x_client = XClient()
        self.medium_client = MediumClient()
        self.devto_client = DevToClient()

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

    async def publish_draft(self, db: AsyncSession, draft_id: str, trace_id: str | None = None) -> ContentDraft:
        """Dispatch a draft to all connected platforms simultaneously using asyncio.gather."""
        stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
        res = await db.execute(stmt)
        draft = res.scalars().first()
        if not draft:
            raise ValueError(f"Draft with ID {draft_id} not found.")

        if draft.status == "PUBLISHED":
            raise ValueError(f"Cannot publish draft {draft_id}: Already published.")

        metadata = draft.llm_metadata or {}
        image_url = metadata.get("image_url")
        requires_image = metadata.get("requires_image")

        if image_url and ("localhost" in image_url or "127.0.0.1" in image_url):
            logger.warning("[PUBLISH PRE-FLIGHT] Local image URL detected. Falling back to text-only publish.")
            image_url = None

        if requires_image and not image_url:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Image generated but not saved to database. Please click 'Save Changes' before publishing."
            )

        # LinkedIn Pre-flight Length Validation
        post_text = draft.content_text
        text_len = len(post_text) if post_text else 0
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

        platform_drafts = metadata.get("platform_drafts", {})
        parsed_data = metadata.get("parsed_llm_output", {})
        target_subreddit = parsed_data.get("target_subreddit") or "ExperiencedDevs"
        tags = parsed_data.get("tags") or ["python", "devops", "programming"]

        # Resolve LinkedIn account (needed for LinkedIn publishing)
        linkedin_account = None
        try:
            linkedin_account = await self._get_default_linkedin_account(db)
        except Exception as e:
            logger.warning(f"Could not load LinkedIn account: {e}")

        # ── Build the coroutine tasks for each active platform ──
        tasks = []

        # 1. LinkedIn
        linkedin_text = platform_drafts.get("linkedin") or draft.content_text
        if linkedin_account:
            async def _publish_linkedin():
                await self.linkedin_client.validate_auth(db=db, account=linkedin_account)
                media_id = await self.linkedin_client.upload_media(image_url, db=db, account=linkedin_account)
                return await self.linkedin_client.publish(
                    linkedin_text, media_id, db=db, account=linkedin_account, idempotency_key=draft_id
                )
            tasks.append(_publish_single_platform("linkedin", _publish_linkedin()))
        else:
            logger.info("[linkedin] No linked account. Skipping.")

        # 2. Reddit
        reddit_title = platform_drafts.get("reddit_title", "")
        reddit_body = platform_drafts.get("reddit_body") or platform_drafts.get("reddit", "")
        if self.reddit_client.is_connected() and (reddit_title or reddit_body):
            # Build the text: title as first line, body as rest
            if reddit_title and reddit_body:
                reddit_full = reddit_body  # publish() will use title from first line or we pass it
            elif reddit_body:
                reddit_full = reddit_body
            else:
                reddit_full = reddit_title

            async def _publish_reddit():
                await self.reddit_client.validate_auth()
                # Override the target subreddit from LLM output
                self.reddit_client.target_subreddit = target_subreddit
                return await self.reddit_client.publish(
                    f"{reddit_title}\n{reddit_full}" if reddit_title else reddit_full
                )
            tasks.append(_publish_single_platform("reddit", _publish_reddit()))
        else:
            logger.info("[reddit] Not connected or no draft. Skipping.")

        # 3. X (Twitter)
        x_text = platform_drafts.get("x", "")
        if self.x_client.is_connected() and x_text:
            async def _publish_x():
                await self.x_client.validate_auth()
                media_id = await self.x_client.upload_media(image_url)
                return await self.x_client.publish(x_text, media_id)
            tasks.append(_publish_single_platform("x", _publish_x()))
        else:
            logger.info("[x] Not connected or no draft. Skipping.")

        # 4. Medium
        medium_title = platform_drafts.get("medium_title", "")
        medium_body = platform_drafts.get("medium_body", "")
        if self.medium_client.is_connected() and (medium_title or medium_body):
            async def _publish_medium():
                await self.medium_client.validate_auth()
                return await self.medium_client.publish(
                    medium_body or medium_title,
                    title=medium_title,
                    tags=tags,
                )
            tasks.append(_publish_single_platform("medium", _publish_medium()))
        else:
            logger.info("[medium] Not connected or no draft. Skipping.")

        # 5. Dev.to
        devto_title = platform_drafts.get("dev_to_title", "")
        devto_body = platform_drafts.get("dev_to_body", "")
        if self.devto_client.is_connected() and (devto_title or devto_body):
            async def _publish_devto():
                await self.devto_client.validate_auth()
                return await self.devto_client.publish(
                    devto_body or devto_title,
                    title=devto_title,
                    tags=tags,
                )
            tasks.append(_publish_single_platform("dev_to", _publish_devto()))
        else:
            logger.info("[dev_to] Not connected or no draft. Skipping.")

        # ── Fire all network requests concurrently ──
        if tasks:
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            results = {}
            for res in results_list:
                if isinstance(res, tuple) and len(res) == 2:
                    results[res[0]] = res[1]
                elif isinstance(res, Exception):
                    logger.error(f"[ORCHESTRATOR] Unhandled exception in gather: {res}")
        else:
            results = {}
            logger.warning("[ORCHESTRATOR] No platforms are connected. Nothing to publish.")

        # ── Update metadata ──
        metadata["publish_statuses"] = results
        draft.llm_metadata = metadata

        # Determine overall status
        statuses = [res.get("status") for res in results.values() if res.get("status") != "SKIPPED"]
        if "SUCCESS" in statuses:
            draft.status = "PUBLISHED"
            # Backward compatibility for existing UI
            if "linkedin" in results and results["linkedin"].get("status") == "SUCCESS":
                metadata["linkedin_post_id"] = results["linkedin"].get("url")
                metadata["published_url"] = f"https://www.linkedin.com/feed/update/{results['linkedin'].get('url')}"
        elif all(s == "AUTH_EXPIRED" for s in statuses) and statuses:
            draft.status = "AUTH_EXPIRED"
        elif not statuses:
            draft.status = "SKIPPED"
        else:
            draft.status = "FAILED"

        flag_modified(draft, "llm_metadata")
        await db.commit()
        await db.refresh(draft)

        if draft.status == "AUTH_EXPIRED":
            raise AuthenticationError("Authentication expired for all platforms. Please re-authenticate.")

        return draft
