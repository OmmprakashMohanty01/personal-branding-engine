"""
API v1 — Skills Router
========================
Exposes the three agent skills as lightweight POST endpoints.

Mounted at /api/v1/skills:

    POST /api/v1/skills/humanize   — deterministic AI-slop removal
    POST /api/v1/skills/comment    — LLM outbound comment generator
    POST /api/v1/skills/reply      — LLM inbound thread replier

Design constraints (enforced):
  - No interaction with the LinkedIn publishing API.
  - No database reads or writes.
  - Each endpoint is a pure function over text.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.generation.skills.humanizer import TextHumanizer
from app.services.generation.skills.commenter import generate_outbound_comment
from app.services.generation.skills.replier import generate_thread_reply

logger = logging.getLogger("branding_engine.api.skills")

router = APIRouter(prefix="/skills", tags=["Agent Skills"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class HumanizeRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="Raw LLM-generated text to be cleaned.",
        examples=["We need to leverage robust solutions to delve into this paradigm shift."],
    )


class HumanizeResponse(BaseModel):
    humanized_text: str = Field(description="The cleaned, humanised output.")
    original_length: int = Field(description="Character count of the original input.")
    humanized_length: int = Field(description="Character count after processing.")


class CommentRequest(BaseModel):
    post_text: str = Field(
        ...,
        min_length=10,
        description="The full text of the LinkedIn post to comment on.",
    )
    comment_type: Optional[str] = Field(
        default="contrarian",
        description=(
            "Engagement style: 'contrarian', 'additive', 'question', or 'data'. "
            "Defaults to 'contrarian'."
        ),
        examples=["contrarian", "additive", "question", "data"],
    )


class CommentResponse(BaseModel):
    comment: str = Field(description="The generated 2-3 sentence LinkedIn comment.")
    comment_type: str = Field(description="The engagement style that was applied.")


class ReplyRequest(BaseModel):
    original_post: str = Field(
        ...,
        min_length=10,
        description="The full text of your original LinkedIn post.",
    )
    user_comment: str = Field(
        ...,
        min_length=1,
        description="The text of the inbound comment to reply to.",
    )


class ReplyResponse(BaseModel):
    reply: str = Field(
        description=(
            "The generated reply. May be the literal string '[SKIP]' when the "
            "comment is categorised as Noise — callers should check for this."
        )
    )
    is_skip: bool = Field(
        description="True when the reply is '[SKIP]' (Noise category). Do not post."
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/humanize",
    response_model=HumanizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove AI-slop patterns from text",
    description=(
        "Deterministically replaces AI buzzwords, normalises typography, "
        "and strips invisible Unicode fingerprint characters. No LLM is invoked."
    ),
)
async def humanize_text(payload: HumanizeRequest) -> HumanizeResponse:
    """Clean raw LLM output through the TextHumanizer pipeline."""
    logger.debug("POST /skills/humanize — input length %d", len(payload.text))

    humanized = TextHumanizer.process(payload.text)

    return HumanizeResponse(
        humanized_text=humanized,
        original_length=len(payload.text),
        humanized_length=len(humanized),
    )


@router.post(
    "/comment",
    response_model=CommentResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a LinkedIn outbound comment",
    description=(
        "Uses the configured LLM (with provider fallback) to generate a technically "
        "grounded 2-3 sentence comment on a target LinkedIn post. "
        "Never produces hollow affirmations like 'Great post!'."
    ),
)
async def comment_on_post(payload: CommentRequest) -> CommentResponse:
    """Generate an outbound LinkedIn comment."""
    logger.info(
        "POST /skills/comment — type=%s post_len=%d",
        payload.comment_type,
        len(payload.post_text),
    )

    try:
        comment = await generate_outbound_comment(
            target_post_text=payload.post_text,
            comment_type=payload.comment_type or "contrarian",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        logger.error("Comment generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="All LLM providers are currently unavailable. Please retry later.",
        )

    return CommentResponse(
        comment=comment,
        comment_type=payload.comment_type or "contrarian",
    )


@router.post(
    "/reply",
    response_model=ReplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a LinkedIn thread reply",
    description=(
        "Categorises the inbound comment (Substance / Peer / Support / Noise) "
        "and drafts an appropriate professional reply. Returns '[SKIP]' for Noise."
    ),
)
async def reply_to_comment(payload: ReplyRequest) -> ReplyResponse:
    """Generate an inbound thread reply."""
    logger.info(
        "POST /skills/reply — post_len=%d comment_len=%d",
        len(payload.original_post),
        len(payload.user_comment),
    )

    try:
        reply = await generate_thread_reply(
            original_post=payload.original_post,
            user_comment=payload.user_comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        logger.error("Reply generation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="All LLM providers are currently unavailable. Please retry later.",
        )

    return ReplyResponse(reply=reply, is_skip=(reply == "[SKIP]"))
