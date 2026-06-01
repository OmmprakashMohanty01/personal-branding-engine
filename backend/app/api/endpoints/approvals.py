from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.generation import DraftResponse
from app.schemas.approvals import ApproveRequest, RejectRequest, ReviseRequest
from app.services.approval import ApprovalService

router = APIRouter(prefix="/approvals", tags=["approvals"])
approval_service = ApprovalService()

@router.get("/pending", response_model=List[DraftResponse])
async def get_pending_drafts(
    platform: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve drafts awaiting curation review (status DRAFT or PENDING_APPROVAL)."""
    return await approval_service.get_pending(db, platform)

@router.post("/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(
    draft_id: str,
    payload: ApproveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Approve a content draft with optional edited content overrides."""
    try:
        return await approval_service.approve_draft(db, draft_id, payload.edited_content)
    except ValueError as e:
        # Invalid state transitions raise ValueError. Raise 409 Conflict if disallowed.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(
    draft_id: str,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db)
):
    """Reject a content draft with rejection reason comments."""
    try:
        return await approval_service.reject_draft(db, draft_id, payload.reason)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{draft_id}/revise", response_model=DraftResponse)
async def request_revision(
    draft_id: str,
    payload: ReviseRequest,
    db: AsyncSession = Depends(get_db)
):
    """Request a dynamic LLM rewrite iteration utilizing feedback notes."""
    try:
        return await approval_service.request_revision(db, draft_id, payload.feedback_notes)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
