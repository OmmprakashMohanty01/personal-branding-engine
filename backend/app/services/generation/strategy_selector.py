"""
strategy_selector.py
====================
Deterministic StrategySelector combining day-of-week content schedule
with historical memory lookback to prevent repetitive patterns.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from app.services.generation.prompt_memory import MemoryContext
from app.services.generation.writing_dna import (
    ContentStrategy,
    WritingDNA,
    WritingDNAEngine,
)

logger = logging.getLogger("branding_engine.generation.strategy_selector")

WEEKDAY_STRATEGY_MAP: Dict[int, str] = {
    0: "Write an engaging post analyzing breaking AI news or emerging industry model architectures.",
    1: "Write a 'Build in Public' post about a concrete coding challenge, optimization, or benchmark result.",
    2: "Write a Technical Tutorial or architectural deep-dive analyzing production system patterns.",
    3: "Write a Career or Productivity Insight tailored for senior software engineers and AI builders.",
    4: "Write an objective Tool or Framework Review evaluating performance, Developer Experience (DX), and trade-offs.",
    5: "Write a Weekly Wins or Lessons Learned retrospective analyzing an engineering failure or breakthrough.",
    6: "Sunday: Architectural Reflection & High-Level System Engineering Thought Experiment.",
}


@dataclass
class StrategySelectionResult:
    """Complete strategic configuration for a single daily content generation."""

    weekday: int
    topic_prompt: str
    writing_dna: WritingDNA
    content_strategy: ContentStrategy

    def to_dict(self) -> dict:
        return {
            "weekday": self.weekday,
            "topic_prompt": self.topic_prompt,
            "writing_dna": self.writing_dna.to_dict(),
            "content_strategy": self.content_strategy.to_dict(),
        }


class StrategySelector:
    """Selects daily topic prompts and non-overlapping writing strategies using DB memory."""

    def __init__(self):
        self.dna_engine = WritingDNAEngine()

    def select_strategy_for_day(
        self,
        weekday: int,
        topic_override: Optional[str] = None,
        memory_context: Optional[MemoryContext] = None,
    ) -> StrategySelectionResult:
        """Select a complete generation strategy for a given weekday and memory context.

        Args:
            weekday: Day of week (0=Monday, 6=Sunday).
            topic_override: Explicit topic override if provided by user/cron.
            memory_context: Historical memory context of recent posts.

        Returns:
            A StrategySelectionResult instance.
        """
        base_prompt = topic_override or WEEKDAY_STRATEGY_MAP.get(
            weekday, WEEKDAY_STRATEGY_MAP[0]
        )

        recent_hooks = (
            memory_context.recent_hooks
            if (memory_context and not memory_context.is_empty)
            else None
        )
        recent_endings = (
            memory_context.recent_endings
            if (memory_context and not memory_context.is_empty)
            else None
        )

        writing_dna = self.dna_engine.generate(
            recent_hooks=recent_hooks,
            recent_endings=recent_endings,
        )

        content_strategy = self.dna_engine.generate_strategy()

        logger.info(
            f"[STRATEGY SELECTOR] Strategy selected for weekday {weekday}",
            extra={
                "weekday": weekday,
                "hook_strategy": writing_dna.hook_strategy,
                "ending_strategy": writing_dna.ending_strategy,
                "goal": content_strategy.goal,
                "audience": content_strategy.audience,
            },
        )

        return StrategySelectionResult(
            weekday=weekday,
            topic_prompt=base_prompt,
            writing_dna=writing_dna,
            content_strategy=content_strategy,
        )
