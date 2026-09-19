"""
Skill 2 — Outbound Commenter
==============================
Generates a technically grounded, non-sycophantic LinkedIn comment on a
target post using the project's existing FallbackLLMProvider.

Usage::

    from app.services.generation.skills.commenter import generate_outbound_comment

    comment = await generate_outbound_comment(post_text, comment_type="contrarian")

This module is intentionally standalone — it does NOT interact with the
LinkedIn publishing client or the daily automation loop.
"""

import logging
from typing import Literal

from app.services.llm_provider import FallbackLLMProvider

logger = logging.getLogger("branding_engine.skills.commenter")

# Supported engagement modes
CommentType = Literal["contrarian", "additive", "question", "data"]

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a Senior Data Analyst with 10+ years of experience working with large-scale data infrastructure and machine learning systems.

Your task is to write a 2-3 sentence comment on a LinkedIn post.

STRICT RULES:
1. NEVER start with "Great post!", "Thanks for sharing", "Interesting perspective!", or any other hollow affirmation.
2. Every sentence must add substance — a specific data point, a counter-example, a nuanced caveat, or a concrete follow-up question.
3. Do NOT use buzzwords like "leverage", "synergy", "paradigm shift", "disruptive", or "innovative".
4. Write as a peer talking to a peer — confident, direct, and brief.
5. Output ONLY the comment text. No preamble, no labels, no quotation marks around the response.

Comment mode: {comment_type}
- contrarian: Gently push back on the central premise with a specific counter-data-point or overlooked nuance.
- additive: Extend the argument with a concrete related observation the author missed.
- question: Ask one precise, technical question that reveals a gap in the post's reasoning.
- data: Cite a real or plausible benchmark, statistic, or study that either confirms or complicates the post's claim.
"""

_USER_PROMPT_TEMPLATE = """Write a {comment_type} comment on the following LinkedIn post:

---
{post_text}
---

Comment (2-3 sentences only):"""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def generate_outbound_comment(
    target_post_text: str,
    comment_type: str = "contrarian",
) -> str:
    """
    Generate a technically grounded LinkedIn comment on *target_post_text*.

    Args:
        target_post_text: The full text of the target LinkedIn post.
        comment_type: Engagement style — one of 'contrarian', 'additive',
                      'question', or 'data'. Defaults to 'contrarian'.

    Returns:
        A 2-3 sentence comment string ready to post.

    Raises:
        RuntimeError: If all configured LLM providers are unavailable.
    """
    if not target_post_text or not target_post_text.strip():
        raise ValueError("target_post_text must not be empty.")

    # Normalise / validate comment_type
    valid_types = {"contrarian", "additive", "question", "data"}
    comment_type = comment_type.lower().strip()
    if comment_type not in valid_types:
        logger.warning(
            "Unknown comment_type '%s'; falling back to 'contrarian'.", comment_type
        )
        comment_type = "contrarian"

    provider = FallbackLLMProvider()


    system_prompt = _SYSTEM_PROMPT.format(comment_type=comment_type)
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        comment_type=comment_type,
        post_text=target_post_text.strip(),
    )

    logger.info(
        "Generating outbound comment [type=%s, post_len=%d chars]",
        comment_type,
        len(target_post_text),
    )

    comment = await provider.generate(
        prompt=user_prompt,
        system_instruction=system_prompt,
        temperature=0.65,   # Slightly creative but grounded
        max_tokens=200,     # 2-3 sentences → well within budget
    )

    comment = comment.strip()
    logger.info("Outbound comment generated (%d chars).", len(comment))
    return comment
