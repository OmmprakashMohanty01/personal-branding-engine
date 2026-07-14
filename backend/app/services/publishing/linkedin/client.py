import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import LinkedInAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token

logger = logging.getLogger("branding_engine.publishing.linkedin.client")

class LinkedInClient:
    """Async client wrapper for interacting with the LinkedIn Posts API and OAuth2 endpoints."""
    
    def __init__(self):
        self.client_id = os.getenv("LINKEDIN_CLIENT_ID", "mock_client_id")
        self.client_secret = os.getenv("LINKEDIN_CLIENT_SECRET", "mock_client_secret")
        self.api_url = "https://api.linkedin.com"
        self.oauth_url = "https://www.linkedin.com"

    async def check_and_refresh_token(self, db: AsyncSession, account: LinkedInAccount) -> str:
        """Evaluate token expiry and refresh via OAuth2 if required. Returns decrypted access token."""
        try:
            now = datetime.now(timezone.utc)
            # Ensure expires_at is timezone-aware for safe comparison (handling naive datetime from SQLite)
            expires_at = account.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            # Refresh if expired or expiring in less than 48 hours
            if expires_at <= now + timedelta(hours=48):
                logger.info(f"LinkedIn access token for account {account.id} is near expiration (within 48 hours). Refreshing...")
                
                # Retrieve encrypted refresh token
                decrypted_refresh = decrypt_token(account.refresh_token)
                if not decrypted_refresh:
                    raise ValueError("Cannot refresh access token: Refresh token is missing or empty.")
                    
                refresh_data = {
                    "grant_type": "refresh_token",
                    "refresh_token": decrypted_refresh,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
                
                url = f"{self.oauth_url}/oauth/v2/accessToken"
                
                # Direct post to exchange refresh token
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, data=refresh_data)
                    
                    # Graceful mock response handling during local testing if credentials are mock values
                    if resp.status_code != 200 and (self.client_id == "mock_client_id" or "mock" in decrypted_refresh):
                        logger.warning("Mock credentials found. Simulating successful token refresh.")
                        new_access = "mock_refreshed_access_token"
                        new_refresh = "mock_refreshed_refresh_token"
                        expires_in = 3600
                        refresh_expires_in = 86400
                    else:
                        resp.raise_for_status()
                        payload = resp.json()
                        new_access = payload.get("access_token")
                        new_refresh = payload.get("refresh_token") or decrypted_refresh
                        expires_in = int(payload.get("expires_in", 3600))
                        refresh_expires_in = int(payload.get("refresh_token_expires_in", 86400))
                
                # Save updated values to database
                account.access_token = encrypt_token(new_access)
                account.refresh_token = encrypt_token(new_refresh)
                account.expires_at = now + timedelta(seconds=expires_in)
                account.refresh_expires_at = now + timedelta(seconds=refresh_expires_in)
                
                await db.commit()
                return new_access
                
            return decrypt_token(account.access_token)
        except Exception as e:
            from cryptography.fernet import InvalidToken
            if isinstance(e, InvalidToken) or e.__class__.__name__ == "InvalidToken":
                logger.warning("Corrupted LinkedIn token detected and wiped from the database.")
                await db.delete(account)
                await db.commit()
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=401,
                    detail="LinkedIn session expired or corrupted. Please re-link your account."
                )
            raise e

    async def publish_post(self, db: AsyncSession, account: LinkedInAccount, text: str) -> str:
        """Publish commentary content to LinkedIn's modern /v2/posts endpoint.
        
        Args:
            db: AsyncSession database handle.
            account: The LinkedInAccount record to publish with.
            text: Post body content text.
            
        Returns:
            The created post URN string.
        """
        access_token = await self.check_and_refresh_token(db, account)
        
        url = f"{self.api_url}/v2/posts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        payload = {
            "author": account.linkedin_person_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": []
            },
            "lifecycleState": "PUBLISHED"
        }
        
        logger.info(f"Dispatched LinkedIn post request for URN: {account.linkedin_person_urn}")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            

            if resp.status_code not in (200, 201):
                raise httpx.HTTPStatusError(
                    f"LinkedIn publishing API returned non-strict success status {resp.status_code}.",
                    request=resp.request,
                    response=resp
                )
                
            resp.raise_for_status()
            # LinkedIn returns the post URN in the location or x-restli-id headers
            post_urn = resp.headers.get("x-restli-id") or resp.json().get("id") or "urn:li:share:unknown"
            return post_urn
            
    async def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> dict:
        """Exchange redirect code for initial access and refresh tokens."""
        url = f"{self.oauth_url}/oauth/v2/accessToken"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
            if resp.status_code != 200 and self.client_id == "mock_client_id":
                # Mock fallback
                return {
                    "access_token": "mock_initial_access_token",
                    "refresh_token": "mock_initial_refresh_token",
                    "expires_in": 3600,
                    "refresh_token_expires_in": 86400
                }
            resp.raise_for_status()
            return resp.json()

    async def fetch_profile_urn(self, access_token: str) -> str:
        """Fetch authenticated user profile URN using me endpoint."""
        url = f"{self.api_url}/v2/userinfo" # standard OpenID Userinfo
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200 and "mock" in access_token:
                return "urn:li:person:mock_person_urn"
            resp.raise_for_status()
            # Standard sub field or id contains the principal identifier
            profile_id = resp.json().get("sub") or resp.json().get("id", "mock_id")
            return f"urn:li:person:{profile_id}"
