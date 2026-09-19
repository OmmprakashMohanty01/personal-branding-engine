"""
Skill 1 — Humanizer Filter
===========================
A deterministic, zero-dependency utility that strips AI-slop patterns
from LLM-generated text before it is written to the database.

Usage::

    from app.services.generation.skills.humanizer import TextHumanizer

    clean = TextHumanizer.process(raw_llm_output)
"""

import re
import logging
from typing import ClassVar

logger = logging.getLogger("branding_engine.skills.humanizer")


class TextHumanizer:
    """
    Stateless class that applies three deterministic passes over raw LLM text:

    1. **Lexicon purge** — replace over-used AI buzzwords with plain alternatives.
    2. **Typography fixes** — normalise punctuation and quote marks.
    3. **Fingerprint eraser** — strip invisible Unicode control characters.
    """

    # ---------------------------------------------------------------------------
    # Pass 1 — Lexicon purge
    # Ordered longest-phrase-first so multi-word phrases match before sub-words.
    # ---------------------------------------------------------------------------
    _LEXICON: ClassVar[list[tuple[str, str]]] = [
        # Multi-word phrases first
        ("in today's fast-paced world", ""),
        ("in today's rapidly evolving world", ""),
        ("it is important to note that", ""),
        ("it's important to note that", ""),
        ("testament to", "proof of"),
        ("it's worth noting that", "notably,"),
        # Single words / short phrases
        ("delve into", "explore"),
        ("delve", "explore"),
        ("leverage", "use"),
        ("leveraging", "using"),
        ("leveraged", "used"),
        ("robust", "strong"),
        ("seamless", "smooth"),
        ("seamlessly", "smoothly"),
        ("game-changer", "major shift"),
        ("game changer", "major shift"),
        ("paradigm shift", "major change"),
        ("synergy", "collaboration"),
        ("synergies", "collaborative benefits"),
        ("holistic", "comprehensive"),
        ("impactful", "effective"),
        ("actionable insights", "practical tips"),
        ("actionable", "practical"),
        ("at the end of the day", "ultimately"),
        ("cutting-edge", "advanced"),
        ("cutting edge", "advanced"),
        ("state-of-the-art", "advanced"),
        ("state of the art", "advanced"),
        ("disruptive", "new"),
        ("innovative", "new"),
        ("transformative", "significant"),
        ("groundbreaking", "notable"),
        ("empower", "help"),
        ("empowers", "helps"),
        ("empowering", "helping"),
        ("utilize", "use"),
        ("utilizes", "uses"),
        ("utilizing", "using"),
        ("utilized", "used"),
        ("ensure", "make sure"),
        ("ensuring", "making sure"),
        ("foster", "build"),
        ("fosters", "builds"),
        ("fostering", "building"),
        ("facilitate", "help"),
        ("facilitates", "helps"),
        ("facilitating", "helping"),
        ("navigate", "handle"),
        ("navigating", "handling"),
        ("unlock", "access"),
        ("unlocks", "gives access to"),
        ("pivotal", "key"),
        ("crucial", "key"),
        ("comprehensive", "thorough"),
        ("streamline", "simplify"),
        ("streamlines", "simplifies"),
        ("streamlining", "simplifying"),
        ("boilerplate", "standard"),
        ("thriving", "growing"),
    ]

    # Pre-compiled (case-insensitive) patterns — built once at class definition.
    _PATTERNS: ClassVar[list[tuple[re.Pattern, str]]] = [
        (re.compile(re.escape(phrase), re.IGNORECASE), replacement)
        for phrase, replacement in _LEXICON
    ]

    # ---------------------------------------------------------------------------
    # Pass 2 — Typography normalisations
    # ---------------------------------------------------------------------------
    # Em/en dash variants → comma-space (preserves sentence rhythm).
    _EM_DASH_RE: ClassVar[re.Pattern] = re.compile(r"\s*[—–]\s*")

    # Curly / "smart" quote pairs → straight equivalents.
    _CURLY_QUOTE_MAP: ClassVar[list[tuple[str, str]]] = [
        ("\u2018", "'"),   # '  LEFT SINGLE QUOTATION MARK
        ("\u2019", "'"),   # '  RIGHT SINGLE QUOTATION MARK
        ("\u201c", '"'),   # "  LEFT DOUBLE QUOTATION MARK
        ("\u201d", '"'),   # "  RIGHT DOUBLE QUOTATION MARK
        ("\u201a", "'"),   # ‚  SINGLE LOW-9 QUOTATION MARK
        ("\u201e", '"'),   # „  DOUBLE LOW-9 QUOTATION MARK
        ("\u2039", "'"),   # ‹  SINGLE LEFT-POINTING ANGLE QUOTATION MARK
        ("\u203a", "'"),   # ›  SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
        ("\u00ab", '"'),   # «  LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
        ("\u00bb", '"'),   # »  RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
    ]

    # ---------------------------------------------------------------------------
    # Pass 3 — Fingerprint / invisible character erasure
    # ---------------------------------------------------------------------------
    _INVISIBLE_CHARS: ClassVar[str] = (
        "\u200b"  # ZERO WIDTH SPACE
        "\u200c"  # ZERO WIDTH NON-JOINER
        "\u200d"  # ZERO WIDTH JOINER
        "\u2060"  # WORD JOINER
        "\ufeff"  # BYTE ORDER MARK / ZERO WIDTH NO-BREAK SPACE
        "\u00ad"  # SOFT HYPHEN
        "\u200e"  # LEFT-TO-RIGHT MARK
        "\u200f"  # RIGHT-TO-LEFT MARK
    )
    _FINGERPRINT_RE: ClassVar[re.Pattern] = re.compile(
        f"[{re.escape(_INVISIBLE_CHARS)}]"
    )

    # ---------------------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------------------

    @classmethod
    def process(cls, text: str) -> str:
        """
        Run all three cleansing passes on *text* and return the cleaned result.

        Args:
            text: Raw LLM-generated string.

        Returns:
            Cleaned string — never raises, degrades gracefully.
        """
        if not text:
            return text

        original_len = len(text)
        text = cls._lexicon_purge(text)
        text = cls._typography_fix(text)
        text = cls._fingerprint_erase(text)

        logger.debug(
            "TextHumanizer: %d chars in → %d chars out", original_len, len(text)
        )
        return text

    # ---------------------------------------------------------------------------
    # Private passes
    # ---------------------------------------------------------------------------

    @classmethod
    def _lexicon_purge(cls, text: str) -> str:
        """Replace AI buzzwords with plain alternatives (case-preserving prefix)."""
        for pattern, replacement in cls._PATTERNS:
            text = pattern.sub(replacement, text)
        # Collapse double spaces created by empty-string replacements.
        text = re.sub(r"  +", " ", text).strip()
        return text

    @classmethod
    def _typography_fix(cls, text: str) -> str:
        """Normalise dashes and curly/smart quotes."""
        # Em/en dash → ", " so the sentence still flows.
        text = cls._EM_DASH_RE.sub(", ", text)

        # Curly quotes → ASCII straight equivalents.
        for curly, straight in cls._CURLY_QUOTE_MAP:
            text = text.replace(curly, straight)

        return text

    @classmethod
    def _fingerprint_erase(cls, text: str) -> str:
        """Strip invisible Unicode control characters used as AI fingerprints."""
        return cls._FINGERPRINT_RE.sub("", text)
