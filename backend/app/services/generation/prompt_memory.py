"""
prompt_memory.py
================
PromptMemoryService — tracks recent posts, hooks, endings, and topics
to prevent repetition across generated content.

Uses the existing ContentDraft table for database retrieval.
Gracefully degrades to empty context if the DB is unavailable.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

logger = logging.getLogger("branding_engine.generation.prompt_memory")


@dataclass
class MemoryContext:
    """Recent content patterns to avoid repeating."""

    recent_hooks: List[str] = field(default_factory=list)
    recent_endings: List[str] = field(default_factory=list)
    recent_topics: List[str] = field(default_factory=list)
    recent_drafts: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.recent_hooks and not self.recent_endings and not self.recent_topics and not self.recent_drafts


class PromptMemoryService:
    """Retrieves recent post patterns from the database to inform diversity.

    Uses the existing ContentDraft model — no new tables or migrations required.
    """

    async def get_recent_context(
        self,
        db: Optional[AsyncSession],
        limit: int = 5,
    ) -> MemoryContext:
        """Query last N published drafts and extract hooks/endings/topics.

        Args:
            db: SQLAlchemy async session (may be None).
            limit: Number of recent drafts to retrieve.

        Returns:
            MemoryContext with extracted patterns, or empty context on failure.
        """
        if db is None:
            return MemoryContext()

        try:
            from app.models.content import ContentDraft

            stmt = (
                select(ContentDraft)
                .where(ContentDraft.status.in_(["DRAFT", "PUBLISHED"]))
                .order_by(ContentDraft.generated_at.desc())
                .limit(limit)
            )
            result = await db.execute(stmt)
            drafts = result.scalars().all()

            if not drafts:
                return MemoryContext()

            recent_hooks: List[str] = []
            recent_endings: List[str] = []
            recent_topics: List[str] = []
            recent_drafts: List[str] = []

            for draft in drafts:
                text = draft.content_text or ""
                metadata = draft.llm_metadata or {}

                # Extract hook (first line/sentence)
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                if lines:
                    hook_text = lines[0][:120]  # Cap at 120 chars
                    recent_hooks.append(hook_text)

                # Extract ending (last non-empty line)
                if len(lines) > 1:
                    ending_text = lines[-1][:120]
                    recent_endings.append(ending_text)

                # Extract topic from metadata if available
                if "topic" in metadata:
                    recent_topics.append(metadata["topic"])

                # Also check hook_strategy from metadata for better diversity
                if "hook_strategy" in metadata:
                    recent_hooks.append(metadata["hook_strategy"])

                if text:
                    recent_drafts.append(text)

            context = MemoryContext(
                recent_hooks=recent_hooks,
                recent_endings=recent_endings,
                recent_topics=recent_topics,
                recent_drafts=recent_drafts,
            )

            logger.info(
                "[PROMPT MEMORY] Context loaded",
                extra={
                    "drafts_retrieved": len(drafts),
                    "hooks_count": len(recent_hooks),
                    "endings_count": len(recent_endings),
                    "topics_count": len(recent_topics),
                },
            )
            return context

        except Exception as e:
            logger.warning(f"[PROMPT MEMORY] Failed to load memory context: {e}")
            return MemoryContext()
