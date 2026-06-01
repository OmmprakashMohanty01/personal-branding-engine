import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import ThreadsAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token

logger = logging.getLogger("branding_engine.publishing.threads.client")

class ThreadsPublishingError(Exception):
    """Exception raised when publishing to Threads fails, carrying successfully posted post IDs and optional creation_id."""
    def __init__(self, message: str, published_post_ids: List[str], creation_id: Optional[str] = None):
        super().__init__(message)
        self.published_post_ids = published_post_ids
        self.creation_id = creation_id


class ThreadsClient:
    """Async client wrapper for interacting with the Threads Graph API and OAuth2 endpoints."""
    
    def __init__(self):
        self.client_id = os.getenv("THREADS_CLIENT_ID", "mock_threads_client_id")
        self.client_secret = os.getenv("THREADS_CLIENT_SECRET", "mock_threads_client_secret")
        self.api_url = "https://graph.threads.net"

    async def check_and_refresh_token(self, db: AsyncSession, account: ThreadsAccount) -> str:
        """Evaluate token expiry and refresh via roll over if within 7 days. Returns decrypted access token."""
        now = datetime.now(timezone.utc)
        # Refresh if expiring in less than 7 days
        if account.expires_at <= now + timedelta(days=7):
            logger.info(f"Threads access token for account {account.id} is near expiration. Refreshing...")
            
            decrypted_token = decrypt_token(account.access_token)
            if not decrypted_token:
                raise ValueError("Cannot refresh access token: Existing access token is missing or empty.")
                
            url = f"{self.api_url}/refresh_access_token"
            params = {
                "grant_type": "th_refresh_token",
                "access_token": decrypted_token
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params)
                
                # Graceful mock response handling during local testing
                if resp.status_code != 200 and (self.client_id == "mock_threads_client_id" or "mock" in decrypted_token):
                    logger.warning("Mock credentials found. Simulating successful token refresh.")
                    new_access = "mock_refreshed_long_lived_token"
                    expires_in = 5184000 # 60 days
                else:
                    resp.raise_for_status()
                    payload = resp.json()
                    new_access = payload.get("access_token")
                    expires_in = int(payload.get("expires_in", 5184000))
            
            # Save updated values to database
            account.access_token = encrypt_token(new_access)
            account.expires_at = now + timedelta(seconds=expires_in)
            
            await db.commit()
            return new_access
            
        return decrypt_token(account.access_token)

    async def publish_post(self, db: AsyncSession, account: ThreadsAccount, text: str) -> List[str]:
        """Publish text or thread of text posts to Threads API v1.0 using the Two-Step container flow.
        
        Args:
            db: AsyncSession database handle.
            account: The ThreadsAccount record.
            text: Post body content text.
            
        Returns:
            List of published post IDs.
        """
        access_token = await self.check_and_refresh_token(db, account)
        
        # Split using formatter's standard thread split marker if present
        if "---thread-split---" in text:
            parts = [p.strip() for p in text.split("---thread-split---") if p.strip()]
        else:
            parts = [text.strip()]
            
        published_ids = []
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        for idx, part in enumerate(parts):
            # Step 1: Containerization (POST /v1.0/{threads_user_id}/threads)
            container_url = f"{self.api_url}/v1.0/{account.threads_user_id}/threads"
            container_payload = {
                "media_type": "TEXT",
                "text": part
            }
            if idx > 0:
                container_payload["reply_to_id"] = published_ids[-1]
                
            logger.info(f"Creating Threads container (part {idx + 1}): {part[:30]}...")
            
            async with httpx.AsyncClient() as client:
                resp1 = await client.post(container_url, json=container_payload, headers=headers)
                
                # Mock fallback
                if resp1.status_code != 200 and "mock" in access_token:
                    logger.warning("Mock access token used. Simulating successful container creation.")
                    creation_id = f"mock_creation_id_{idx + 1}"
                else:
                    try:
                        resp1.raise_for_status()
                        creation_id = resp1.json().get("id")
                        if not creation_id:
                            raise ValueError("Threads container creation response missing 'id'")
                    except Exception as e:
                        error_msg = f"Containerization failed (Step 1) for part {idx + 1}: {str(e)}"
                        if resp1.status_code == 429:
                            error_msg = f"Rate limit exceeded (429) on Step 1: {resp1.text}"
                        elif resp1.status_code in (401, 403):
                            error_msg = f"Auth/Tier error ({resp1.status_code}) on Step 1: {resp1.text}"
                        raise ThreadsPublishingError(error_msg, published_ids)
                        
            # Step 2: Publishing (POST /v1.0/{threads_user_id}/threads_publish)
            publish_url = f"{self.api_url}/v1.0/{account.threads_user_id}/threads_publish"
            publish_payload = {
                "creation_id": creation_id
            }
            
            logger.info(f"Publishing Threads container {creation_id} (part {idx + 1})...")
            
            async with httpx.AsyncClient() as client:
                resp2 = await client.post(publish_url, json=publish_payload, headers=headers)
                
                # Mock fallback
                if resp2.status_code != 200 and "mock" in access_token:
                    logger.warning("Mock access token used. Simulating successful publication.")
                    post_id = f"mock_threads_post_id_{idx + 1}"
                else:
                    try:
                        resp2.raise_for_status()
                        post_id = resp2.json().get("id")
                        if not post_id:
                            raise ValueError("Threads publishing response missing 'id'")
                    except Exception as e:
                        # Orphan container scenario
                        error_msg = f"Publishing failed (Step 2) for part {idx + 1} (creation_id: {creation_id}): {str(e)}"
                        if resp2.status_code == 429:
                            error_msg = f"Rate limit exceeded (429) on Step 2 (creation_id: {creation_id}): {resp2.text}"
                        elif resp2.status_code in (401, 403):
                            error_msg = f"Auth/Tier error ({resp2.status_code}) on Step 2 (creation_id: {creation_id}): {resp2.text}"
                        raise ThreadsPublishingError(error_msg, published_ids, creation_id=creation_id)
                        
            published_ids.append(post_id)
            
        return published_ids

    async def exchange_code_for_short_token(self, code: str, redirect_uri: str) -> dict:
        """Exchange redirect code for initial short-lived access token."""
        url = f"{self.api_url}/oauth/access_token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
            if resp.status_code != 200 and self.client_id == "mock_threads_client_id":
                logger.warning("Mock credentials found. Simulating successful short-lived token retrieval.")
                return {
                    "access_token": "mock_short_lived_token",
                    "user_id": "mock_threads_user_id"
                }
            resp.raise_for_status()
            return resp.json()

    async def exchange_short_for_long_token(self, short_token: str) -> dict:
        """Exchange short-lived access token for a 60-day long-lived access token."""
        url = f"{self.api_url}/access_token"
        params = {
            "grant_type": "th_exchange_token",
            "client_secret": self.client_secret,
            "access_token": short_token
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200 and "mock" in short_token:
                logger.warning("Mock token found. Simulating successful long-lived token retrieval.")
                return {
                    "access_token": "mock_long_lived_token",
                    "expires_in": 5184000
                }
            resp.raise_for_status()
            return resp.json()

    async def fetch_user_profile(self, access_token: str) -> dict:
        """Fetch authenticated user profile details from Threads Graph API (GET /v1.0/me)."""
        url = f"{self.api_url}/v1.0/me"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"fields": "id,username"}
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200 and "mock" in access_token:
                return {
                    "id": "mock_threads_user_id",
                    "username": "mock_threads_username"
                }
            resp.raise_for_status()
            return resp.json()
