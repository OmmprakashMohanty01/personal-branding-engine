"""
Skill 3 — Inbound Thread Replier
===================================
Categorises an inbound LinkedIn comment and drafts a concise, professional
reply using the project's existing FallbackLLMProvider.

Usage::

    from app.services.generation.skills.replier import generate_thread_reply

    reply = await generate_thread_reply(original_post, user_comment)

This module is intentionally standalone — it does NOT interact with the
LinkedIn publishing client or the daily automation loop.
"""

import logging

from app.services.llm_provider import FallbackLLMProvider

logger = logging.getLogger("branding_engine.skills.replier")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a professional LinkedIn content creator and subject matter expert.

Your task is to draft a concise, high-quality reply to a comment on one of your posts.

STEP 1 — Categorise the comment into exactly one of these four types:
  • Substance  — The commenter asks a genuine technical question or raises a substantive point worth addressing.
  • Peer       — The commenter is a fellow practitioner sharing their own related experience or insight.
  • Support    — The commenter is expressing agreement, encouragement, or gratitude ("Love this!", "So true!").
  • Noise      — The commenter is off-topic, spammy, promotional, or adds no value.

STEP 2 — Draft a reply according to these rules:
  • Substance → Answer the technical question directly and concisely (2-4 sentences). Cite a specific fact, mechanism, or example.
  • Peer      → Acknowledge their experience and add one complementary insight that builds a dialogue (2-3 sentences).
  • Support   → A brief, warm, and genuine thank-you. One sentence only. No hollow filler.
  • Noise     → Reply with exactly the string: [SKIP] — do not engage.

STRICT RULES:
  - NEVER use "Great comment!", "Thanks for sharing!", or any hollow opener.
  - Output ONLY the reply text (or [SKIP]). No category label, no preamble.
  - Keep the tone confident, collegial, and human.
"""

_USER_PROMPT_TEMPLATE = """Original post:
---
{original_post}
---

Comment to reply to:
---
{user_comment}
---

Reply:"""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def generate_thread_reply(
    original_post: str,
    user_comment: str,
) -> str:
    """
    Categorise *user_comment* and generate an appropriate reply.

    Args:
        original_post: The full text of the original LinkedIn post.
        user_comment:  The text of the inbound comment to reply to.

    Returns:
        A reply string. Returns the literal string "[SKIP]" when the LLM
        categorises the comment as Noise — callers may inspect this value
        and choose not to post a reply.

    Raises:
        ValueError:   If either argument is empty.
        RuntimeError: If all configured LLM providers are unavailable.
    """
    if not original_post or not original_post.strip():
        raise ValueError("original_post must not be empty.")
    if not user_comment or not user_comment.strip():
        raise ValueError("user_comment must not be empty.")

    provider = FallbackLLMProvider()

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        original_post=original_post.strip(),
        user_comment=user_comment.strip(),
    )

    logger.info(
        "Generating thread reply [post_len=%d, comment_len=%d]",
        len(original_post),
        len(user_comment),
    )

    reply = await provider.generate(
        prompt=user_prompt,
        system_instruction=_SYSTEM_PROMPT,
        temperature=0.55,   # Factual and controlled — this is a professional reply
        max_tokens=250,
    )

    reply = reply.strip()
    logger.info(
        "Thread reply generated (%d chars). Skip=%s",
        len(reply),
        reply == "[SKIP]",
    )
    return reply
