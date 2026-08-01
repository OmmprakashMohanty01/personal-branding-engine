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
    "start with an intrusive thought about a contrarian industry thesis",
    "start with a realization about a systemic failure in software",
    "start with a raw mid-development observation about team velocity",
    "start with an intrusive thought challenging a widely accepted practice",
    "start with a realization about the business impact of a technical choice",
]

# ---------------------------------------------------------------------------
# Ending Strategy Pool
# ---------------------------------------------------------------------------
ENDING_STRATEGIES: List[str] = [
    "Deliver an abrupt, strong concluding thesis. Do not ask a question.",
    "State the definitive business outcome of this approach.",
    "End abruptly with the strategic lesson learned.",
    "Conclude by rejecting the false dichotomy often associated with this topic.",
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
    "Establish thought leadership by challenging conventional industry wisdom",
    "Align technical architecture with business strategy and team velocity",
    "Provide a high-level systemic analysis of an emerging technology trend",
    "Demonstrate authoritative expertise on a complex engineering problem",
    "Critique the hidden costs or scalability limits of popular paradigms",
]

AUDIENCES: List[str] = [
    "C-Suite executives and VP-level engineering leadership",
    "Startup founders and technical co-founders",
    "Senior engineering managers making strategic build-vs-buy decisions",
    "Directors of Engineering focusing on team velocity and cost",
]

EMOTIONAL_INTENTS: List[str] = [
    "Authority — establish undeniable expertise and strategic vision",
    "Clarity — cut through industry noise and hype",
    "Respect — command attention through concise business pragmatism",
    "Conviction — state a definitive truth without hesitation",
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
        import datetime
        day_of_week = datetime.datetime.utcnow().weekday()
        day_themes = {
            0: "Contrarian insight",
            1: "Technical deep dive",
            2: "Story + lesson",
            3: "Data/statistic/opinion",
            4: "Career/Prediction",
            5: "Build in public / Project update",
            6: "Reflection / Rest"
        }
        theme = day_themes.get(day_of_week, "General insight")

        base_hook = self._pick_avoiding(HOOK_STRATEGIES, recent_hooks)
        hook = f"[{theme}] {base_hook}"
        
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
