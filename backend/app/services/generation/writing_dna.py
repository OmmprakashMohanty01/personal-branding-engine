"""
writing_dna.py
==============
Writing DNA Engine — hook strategies, ending strategies, paragraph rhythms,
content strategy (goal, audience, emotional intent).

Python-side randomization ensures structural diversity.
Prompt-side instructions use soft guidance ("vary", "prefer what fits")
rather than asking the LLM to generate randomness.
"""

import random
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("branding_engine.generation.writing_dna")


# ---------------------------------------------------------------------------
# Hook Strategy Pool
# ---------------------------------------------------------------------------
HOOK_STRATEGIES: List[str] = [
    "Open with a real bug, error message, or debugging story you encountered",
    "Lead with a sharp, specific technical observation most people overlook",
    "State an unpopular or contrarian technical take and defend it immediately",
    "Name a widely-held tech belief and explain why it's wrong or incomplete",
    "Open with something that broke, shipped wrong, or took too long",
    "Describe a technical experiment you ran and what you measured",
    "Open with a concrete number or statistic that reframes the topic",
    "Start with a hard-won engineering principle from shipping real software",
]

# ---------------------------------------------------------------------------
# Ending Strategy Pool
# ---------------------------------------------------------------------------
ENDING_STRATEGIES: List[str] = [
    "Close with a personal takeaway connecting the technical detail to a broader lesson",
    "End with a single memorable one-liner that captures the core insight",
    "Close by describing what you plan to try or build next",
    "Make a concrete prediction about where this technology is heading",
    "Leave the reader with an unresolved tension or question you're still thinking about",
    "Invite the reader to try a specific tool, technique, or experiment",
    "Circle back to the opening hook with a twist or resolution",
]

# ---------------------------------------------------------------------------
# Paragraph Rhythm Patterns
# ---------------------------------------------------------------------------
PARAGRAPH_RHYTHMS: List[str] = [
    "Use this rhythm: 1-sentence → 3-sentence → 2-sentence → 4-sentence → 1-sentence",
    "Use this rhythm: 2-sentence → 1-sentence → 3-sentence → 1-sentence → 2-sentence",
    "Use this rhythm: 3-sentence → 1-sentence → 2-sentence → 3-sentence → 1-sentence",
    "Use this rhythm: 1-sentence → 4-sentence → 1-sentence → 2-sentence → 1-sentence",
    "Use this rhythm: 2-sentence → 3-sentence → 1-sentence → 1-sentence → 3-sentence",
    "Use this rhythm: 4-sentence → 1-sentence → 1-sentence → 3-sentence → 2-sentence",
]

# ---------------------------------------------------------------------------
# Content Strategy Pools
# ---------------------------------------------------------------------------
CONTENT_GOALS: List[str] = [
    "Teach — share a specific, actionable technical concept the reader can use today",
    "Inspire — show what's possible when you build something from scratch",
    "Challenge assumptions — question conventional wisdom with evidence",
    "Tell a story — narrate a real engineering experience with a beginning, middle, and end",
    "Share an experiment — describe something you tested and what you learned",
    "Document progress — share a real update from a project you're building in public",
    "Build credibility — demonstrate deep expertise on a focused technical topic",
    "Generate discussion — pose a genuine question that engineers would debate",
    "Recruit opportunities — showcase skills and projects that attract collaborators or employers",
]

AUDIENCES: List[str] = [
    "Software engineers building production systems",
    "AI/ML engineers working with LLMs and automation",
    "Recruiters and hiring managers evaluating technical talent",
    "Startup founders making build-vs-buy technology decisions",
    "Computer science students exploring career paths",
    "Engineering managers leading technical teams",
]

EMOTIONAL_INTENTS: List[str] = [
    "Curiosity — make the reader want to explore this further",
    "Confidence — make the reader feel capable of tackling this themselves",
    "Respect — earn the reader's trust through demonstrated expertise",
    "Motivation — push the reader to start building or experimenting",
    "Reflection — make the reader reconsider something they took for granted",
    "Relief — validate a struggle the reader has silently experienced",
]


@dataclass
class WritingDNA:
    """Immutable snapshot of the writing DNA selected for a single generation."""

    hook_strategy: str
    ending_strategy: str
    paragraph_rhythm: str

    def to_dict(self) -> dict:
        return {
            "hook_strategy": self.hook_strategy,
            "ending_strategy": self.ending_strategy,
            "paragraph_rhythm": self.paragraph_rhythm,
        }


@dataclass
class ContentStrategy:
    """Content strategy selected for a single generation."""

    goal: str
    audience: str
    emotional_intent: str

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "audience": self.audience,
            "emotional_intent": self.emotional_intent,
        }


class WritingDNAEngine:
    """Selects writing DNA and content strategy, avoiding recent repeats."""

    def generate(
        self,
        recent_hooks: Optional[List[str]] = None,
        recent_endings: Optional[List[str]] = None,
    ) -> WritingDNA:
        """Select a fresh combination of hook, ending, and paragraph rhythm.

        Args:
            recent_hooks: Hook strategies used in recent posts (to avoid).
            recent_endings: Ending strategies used in recent posts (to avoid).

        Returns:
            A WritingDNA instance with the selected combination.
        """
        hook = self._pick_avoiding(HOOK_STRATEGIES, recent_hooks)
        ending = self._pick_avoiding(ENDING_STRATEGIES, recent_endings)
        rhythm = random.choice(PARAGRAPH_RHYTHMS)

        dna = WritingDNA(
            hook_strategy=hook,
            ending_strategy=ending,
            paragraph_rhythm=rhythm,
        )

        logger.info(
            "[WRITING DNA] Selected",
            extra={
                "hook_strategy": hook,
                "ending_strategy": ending,
                "paragraph_rhythm": rhythm,
            },
        )
        return dna

    def generate_strategy(self) -> ContentStrategy:
        """Select a content strategy (goal, audience, emotional intent).

        Returns:
            A ContentStrategy instance.
        """
        strategy = ContentStrategy(
            goal=random.choice(CONTENT_GOALS),
            audience=random.choice(AUDIENCES),
            emotional_intent=random.choice(EMOTIONAL_INTENTS),
        )

        logger.info(
            "[CONTENT STRATEGY] Selected",
            extra=strategy.to_dict(),
        )
        return strategy

    @staticmethod
    def _pick_avoiding(pool: List[str], avoid: Optional[List[str]] = None) -> str:
        """Pick a random item from pool, preferring items not in the avoid list."""
        if not avoid:
            return random.choice(pool)

        avoid_lower = [a.lower() for a in avoid]
        candidates = [item for item in pool if item.lower() not in avoid_lower]

        if not candidates:
            return random.choice(pool)

        return random.choice(candidates)
