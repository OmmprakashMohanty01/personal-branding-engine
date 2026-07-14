from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.client import LinkedInClient
from app.services.publishing.linkedin.crypto import encrypt_token

router = APIRouter(prefix="/publishing", tags=["Publishing"])
linkedin_client = LinkedInClient()

@router.get("/linkedin/status")
async def check_linkedin_status(db: AsyncSession = Depends(get_db)):
    """Check if any LinkedIn account is connected."""
    stmt = select(LinkedInAccount)
    res = await db.execute(stmt)
    account = res.scalars().first()
    if account:
        return {
            "connected": True,
            "is_linked": True,
            "linkedin_person_urn": account.linkedin_person_urn
        }
    return {
        "connected": False,
        "is_linked": False
    }

@router.post("/linkedin/connect")
async def connect_linkedin(
    code: str = Query(..., description="OAuth2 authorization code returned by LinkedIn redirect"),
    redirect_uri: str | None = Query(None, description="The registered redirect URI"),
    db: AsyncSession = Depends(get_db)
):
    """Callback endpoint to exchange authorization code for access/refresh tokens and connect account."""
    import os
    
    # 1. Sandbox Bypass check
    if code == "sandbox_dev_token_123":
        urn = "urn:li:person:sandbox"
        stmt = select(LinkedInAccount).where(LinkedInAccount.linkedin_person_urn == urn)
        res = await db.execute(stmt)
        account = res.scalars().first()
        now = datetime.now(timezone.utc)
        
        if not account:
            account = LinkedInAccount(
                linkedin_person_urn=urn,
                access_token=encrypt_token("mock_sandbox_access_token"),
                refresh_token=encrypt_token("mock_sandbox_refresh_token"),
                expires_at=now + timedelta(days=365),
                refresh_expires_at=now + timedelta(days=365)
            )
            db.add(account)
        else:
            account.access_token = encrypt_token("mock_sandbox_access_token")
            account.refresh_token = encrypt_token("mock_sandbox_refresh_token")
            account.expires_at = now + timedelta(days=365)
            account.refresh_expires_at = now + timedelta(days=365)
            
        await db.commit()
        return {
            "status": "connected",
            "linkedin_person_urn": urn,
            "message": "Sandbox mode engaged!"
        }

    # 2. For real tokens, resolve redirect URI and client credentials
    env_redirect = os.getenv("REDIRECT_URI")
    final_redirect_uri = env_redirect or redirect_uri
    if not final_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri must be provided in the query parameters or configured via the REDIRECT_URI environment variable."
        )

    try:
        # Exchange code for token pair
        tokens = await linkedin_client.exchange_code_for_tokens(code, final_redirect_uri)
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


