from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.integration import LinkedInAccount, XAccount, ThreadsAccount, SubstackAccount
from app.schemas.generation import DraftResponse
from app.services.publishing.linkedin.client import LinkedInClient
from app.services.publishing.linkedin.crypto import encrypt_token
from app.services.publishing.orchestrator import PublishingOrchestrator
from app.services.publishing.x.client import XClient
from app.services.publishing.threads.client import ThreadsClient
from app.services.publishing.substack.client import SubstackClient
from pydantic import BaseModel

class SubstackConfigPayload(BaseModel):
    newsletter_name: str
    secret_email_address: str
    author_email: str

router = APIRouter(prefix="/publishing", tags=["publishing"])
linkedin_client = LinkedInClient()
x_client = XClient()
threads_client = ThreadsClient()
substack_client = SubstackClient()
orchestrator = PublishingOrchestrator()

@router.post("/linkedin/connect")
async def connect_linkedin(
    code: str = Query(..., description="OAuth2 authorization code returned by LinkedIn redirect"),
    redirect_uri: str = Query("https://localhost:8000/api/v1/publishing/linkedin/connect", description="The registered redirect URI"),
    db: AsyncSession = Depends(get_db)
):
    """Callback endpoint to exchange authorization code for access/refresh tokens and connect account."""
    try:
        # Exchange code for token pair
        tokens = await linkedin_client.exchange_code_for_tokens(code, redirect_uri)
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = int(tokens.get("expires_in", 3600))
        refresh_expires_in = int(tokens.get("refresh_token_expires_in", 86400))
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Invalid code exchange: Access token is missing.")
            
        # Fetch user URN
        urn = await linkedin_client.fetch_profile_urn(access_token)
        
        # Save or update account integration in database
        stmt = select(LinkedInAccount).where(LinkedInAccount.linkedin_person_urn == urn)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        now = datetime.now(timezone.utc)
        
        if not account:
            account = LinkedInAccount(
                linkedin_person_urn=urn,
                access_token=encrypt_token(access_token),
                refresh_token=encrypt_token(refresh_token) if refresh_token else None,
                expires_at=now + timedelta(seconds=expires_in),
                refresh_expires_at=now + timedelta(seconds=refresh_expires_in) if refresh_token else None
            )
            db.add(account)
        else:
            account.access_token = encrypt_token(access_token)
            if refresh_token:
                account.refresh_token = encrypt_token(refresh_token)
                account.refresh_expires_at = now + timedelta(seconds=refresh_expires_in)
            account.expires_at = now + timedelta(seconds=expires_in)
            
        await db.commit()
        return {
            "status": "connected",
            "linkedin_person_urn": urn,
            "message": "LinkedIn account successfully connected."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth exchange failed: {str(e)}"
        )


@router.post("/x/connect")
async def connect_x(
    code: str = Query(..., description="OAuth2 authorization code returned by X redirect"),
    code_verifier: str = Query("mock_code_verifier", description="The PKCE code verifier matching the authorize request"),
    redirect_uri: str = Query("https://localhost:8000/api/v1/publishing/x/connect", description="The registered redirect URI"),
    db: AsyncSession = Depends(get_db)
):
    """Callback endpoint to exchange X authorization code for access/refresh tokens and connect account."""
    try:
        # Exchange code and verifier for token pair
        tokens = await x_client.exchange_code_for_tokens(code, redirect_uri, code_verifier)
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = int(tokens.get("expires_in", 7200))
        
        if not access_token:
            raise HTTPException(status_code=400, detail="Invalid code exchange: Access token is missing.")
            
        # Fetch user profile details
        profile = await x_client.fetch_user_profile(access_token)
        twitter_id = profile.get("id")
        username = profile.get("username")
        
        if not twitter_id or not username:
            raise HTTPException(status_code=400, detail="Failed to fetch user profile details from X.")
            
        # Save or update account integration in database
        stmt = select(XAccount).where(XAccount.twitter_id == twitter_id)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        now = datetime.now(timezone.utc)
        
        if not account:
            account = XAccount(
                twitter_id=twitter_id,
                username=username,
                access_token=encrypt_token(access_token),
                refresh_token=encrypt_token(refresh_token) if refresh_token else None,
                expires_at=now + timedelta(seconds=expires_in)
            )
            db.add(account)
        else:
            account.username = username
            account.access_token = encrypt_token(access_token)
            if refresh_token:
                account.refresh_token = encrypt_token(refresh_token)
            account.expires_at = now + timedelta(seconds=expires_in)
            
        await db.commit()
        return {
            "status": "connected",
            "twitter_id": twitter_id,
            "username": username,
            "message": "X (Twitter) account successfully connected."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth exchange failed: {str(e)}"
        )


@router.post("/threads/connect")
async def connect_threads(
    code: str = Query(..., description="OAuth2 authorization code returned by Threads redirect"),
    redirect_uri: str = Query("https://localhost:8000/api/v1/publishing/threads/connect", description="The registered redirect URI"),
    db: AsyncSession = Depends(get_db)
):
    """Callback endpoint to exchange Threads authorization code for long-lived access tokens and connect account."""
    try:
        # Step 1: Exchange code for short-lived access token
        short_token_payload = await threads_client.exchange_code_for_short_token(code, redirect_uri)
        short_token = short_token_payload.get("access_token")
        if not short_token:
            raise HTTPException(status_code=400, detail="Invalid code exchange: Short-lived access token is missing.")
            
        # Step 2: Exchange short-lived token for long-lived access token
        long_token_payload = await threads_client.exchange_short_for_long_token(short_token)
        long_token = long_token_payload.get("access_token")
        expires_in = int(long_token_payload.get("expires_in", 5184000))
        
        if not long_token:
            raise HTTPException(status_code=400, detail="Invalid token exchange: Long-lived access token is missing.")
            
        # Step 3: Fetch profile username and user ID
        profile = await threads_client.fetch_user_profile(long_token)
        threads_user_id = profile.get("id")
        username = profile.get("username")
        
        if not threads_user_id or not username:
            raise HTTPException(status_code=400, detail="Failed to fetch user profile details from Threads.")
            
        # Save or update account integration in database
        stmt = select(ThreadsAccount).where(ThreadsAccount.threads_user_id == threads_user_id)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        now = datetime.now(timezone.utc)
        
        if not account:
            account = ThreadsAccount(
                threads_user_id=threads_user_id,
                username=username,
                access_token=encrypt_token(long_token),
                expires_at=now + timedelta(seconds=expires_in)
            )
            db.add(account)
        else:
            account.username = username
            account.access_token = encrypt_token(long_token)
            account.expires_at = now + timedelta(seconds=expires_in)
            
        await db.commit()
        return {
            "status": "connected",
            "threads_user_id": threads_user_id,
            "username": username,
            "message": "Threads account successfully connected."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth exchange failed: {str(e)}"
        )


@router.post("/substack/config")
async def config_substack(
    payload: SubstackConfigPayload,
    db: AsyncSession = Depends(get_db)
):
    """Save or update Substack newsletter integration details."""
    try:
        # Check if there is an existing configured integration
        stmt = select(SubstackAccount)
        res = await db.execute(stmt)
        account = res.scalars().first()
        
        if not account:
            account = SubstackAccount(
                newsletter_name=payload.newsletter_name,
                secret_email_address=payload.secret_email_address,
                author_email=payload.author_email
            )
            db.add(account)
        else:
            account.newsletter_name = payload.newsletter_name
            account.secret_email_address = payload.secret_email_address
            account.author_email = payload.author_email
            
        await db.commit()
        await db.refresh(account)
        return {
            "status": "configured",
            "newsletter_name": account.newsletter_name,
            "message": "Substack integration configured successfully."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration failed: {str(e)}"
        )


@router.post("/drafts/{draft_id}/publish-now", response_model=DraftResponse)
async def publish_draft_now(
    draft_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Trigger the instant publication workflow for an approved content draft."""
    try:
        draft = await orchestrator.publish_draft(db, draft_id)
        if draft.status == "FAILED_PUBLISHING":
            # If publishing client execution failed, raise a Bad Request containing the notes
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Publishing failed. Details: {draft.feedback_notes}"
            )
        return draft
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal publishing failure: {str(e)}"
        )
