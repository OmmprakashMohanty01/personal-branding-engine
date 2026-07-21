"""
deduplication.py
================
ContentDeduplicationStage — calculates objective metrics and checks text
similarity against historical drafts to prevent repetitive content.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.generation.prompt_memory import PromptMemoryService

logger = logging.getLogger("branding_engine.generation.deduplication")


@dataclass
class ContentMetrics:
    """Objective structural and quality metrics for a post text."""

    character_count: int
    word_count: int
    paragraph_count: int
    avg_sentence_length: float
    emoji_count: int
    has_metric: bool
    has_tool_name: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_count": self.character_count,
            "word_count": self.word_count,
            "paragraph_count": self.paragraph_count,
            "avg_sentence_length": round(self.avg_sentence_length, 1),
            "emoji_count": self.emoji_count,
            "has_metric": self.has_metric,
            "has_tool_name": self.has_tool_name,
        }


class ContentDeduplicationStage:
    """Computes text similarity against recent posts and calculates structural metrics."""

    @staticmethod
    def calculate_metrics(text: str) -> ContentMetrics:
        """Extract objective text metrics from post text."""
        char_count = len(text)
        words = text.split()
        word_count = len(words)

        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        paragraph_count = len(paragraphs)

        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        avg_sentence_length = (word_count / len(sentences)) if sentences else 0.0

        # Count emojis via unicode regex pattern
        emoji_matches = re.findall(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF]",
            text,
        )
        emoji_count = len(emoji_matches)

        # Check for numbers/metrics (e.g. 50%, 100ms, 3.5x, 10,000)
        has_metric = bool(re.search(r"\b\d+(?:\.\d+)?%?|\b\d+[xkmb]\b", text.lower()))

        # Check for tool/technology mentions
        common_tools = ["python", "fastapi", "postgres", "gemini", "cohere", "docker", "render", "yolo", "pytorch", "rag", "git", "sql"]
        text_lower = text.lower()
        has_tool_name = any(tool in text_lower for tool in common_tools)

        return ContentMetrics(
            character_count=char_count,
            word_count=word_count,
            paragraph_count=paragraph_count,
            avg_sentence_length=avg_sentence_length,
            emoji_count=emoji_count,
            has_metric=has_metric,
            has_tool_name=has_tool_name,
        )

    @staticmethod
    def jaccard_similarity(text1: str, text2: str) -> float:
        """Compute word 3-gram Jaccard similarity between two texts."""
        def get_ngrams(text: str, n: int = 3) -> Set[str]:
            tokens = re.findall(r"\w+", text.lower())
            if len(tokens) < n:
                return set(tokens)
            return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}

        set1 = get_ngrams(text1)
        set2 = get_ngrams(text2)

        if not set1 or not set2:
            return 0.0

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / union if union > 0 else 0.0

    async def check_duplicate(
        self,
        new_text: str,
        db: AsyncSession,
        similarity_threshold: float = 0.75,
    ) -> Tuple[bool, float, Optional[str]]:
        """Check if new_text is overly similar to recent published posts in DB.

        Returns:
            Tuple of (is_duplicate_bool, highest_similarity_score, matching_snippet).
        """
        memory_service = PromptMemoryService()
        memory_context = await memory_service.get_recent_context(db, limit=10)

        if memory_context.is_empty:
            return False, 0.0, None

        max_sim = 0.0
        match_snippet = None

        for draft in memory_context.recent_drafts:
            sim = self.jaccard_similarity(new_text, draft.content_text)
            if sim > max_sim:
                max_sim = sim
                match_snippet = draft.content_text[:100]

        is_duplicate = max_sim >= similarity_threshold
        if is_duplicate:
            logger.warning(
                f"[DEDUPLICATION ALERT] High similarity ({max_sim:.2f}) with past draft: '{match_snippet}'"
            )

        return is_duplicate, max_sim, match_snippet
