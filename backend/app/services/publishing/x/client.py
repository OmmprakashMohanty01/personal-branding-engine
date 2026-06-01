import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import XAccount
from app.services.publishing.linkedin.crypto import encrypt_token, decrypt_token

logger = logging.getLogger("branding_engine.publishing.x.client")

class XPublishingError(Exception):
    """Exception raised when publishing to X fails, carrying successfully posted tweet IDs."""
    def __init__(self, message: str, published_tweet_ids: List[str]):
        super().__init__(message)
        self.published_tweet_ids = published_tweet_ids


class XClient:
    """Async client wrapper for interacting with the X (Twitter) API v2 and OAuth2 endpoints."""
    
    def __init__(self):
        self.client_id = os.getenv("X_CLIENT_ID", "mock_x_client_id")
        self.client_secret = os.getenv("X_CLIENT_SECRET", "mock_x_client_secret")
        self.api_url = "https://api.twitter.com"

    async def check_and_refresh_token(self, db: AsyncSession, account: XAccount) -> str:
        """Evaluate token expiry and refresh via OAuth2 if required. Returns decrypted access token."""
        now = datetime.now(timezone.utc)
        # Refresh if expired or expiring in less than 5 minutes
        if account.expires_at <= now + timedelta(minutes=5):
            logger.info(f"X access token for account {account.id} is near expiration. Refreshing...")
            
            # Retrieve encrypted refresh token
            decrypted_refresh = decrypt_token(account.refresh_token)
            if not decrypted_refresh:
                raise ValueError("Cannot refresh access token: Refresh token is missing or empty.")
                
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": decrypted_refresh,
                "client_id": self.client_id,
            }
            if self.client_secret and self.client_secret != "mock_x_client_secret":
                refresh_data["client_secret"] = self.client_secret
                
            url = f"{self.api_url}/2/oauth2/token"
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=refresh_data)
                
                # Graceful mock response handling during local testing if credentials are mock values
                if resp.status_code != 200 and (self.client_id == "mock_x_client_id" or "mock" in decrypted_refresh):
                    logger.warning("Mock credentials found. Simulating successful token refresh.")
                    new_access = "mock_refreshed_x_access_token"
                    new_refresh = "mock_refreshed_x_refresh_token"
                    expires_in = 7200
                else:
                    resp.raise_for_status()
                    payload = resp.json()
                    new_access = payload.get("access_token")
                    new_refresh = payload.get("refresh_token") or decrypted_refresh
                    expires_in = int(payload.get("expires_in", 7200))
            
            # Save updated values to database
            account.access_token = encrypt_token(new_access)
            account.refresh_token = encrypt_token(new_refresh)
            account.expires_at = now + timedelta(seconds=expires_in)
            
            await db.commit()
            return new_access
            
        return decrypt_token(account.access_token)

    async def publish_post(self, db: AsyncSession, account: XAccount, text: str) -> List[str]:
        """Publish tweet or thread of tweets to X's v2 /2/tweets endpoint.
        
        Args:
            db: AsyncSession database handle.
            account: The XAccount record to publish with.
            text: Post body content text.
            
        Returns:
            List of posted tweet IDs.
        """
        access_token = await self.check_and_refresh_token(db, account)
        
        # Split using formatter's standard thread split marker if present
        if "---thread-split---" in text:
            parts = [p.strip() for p in text.split("---thread-split---") if p.strip()]
        else:
            parts = [text.strip()]
            
        posted_ids = []
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        url = f"{self.api_url}/2/tweets"
        
        for idx, part in enumerate(parts):
            payload = {"text": part}
            if idx > 0:
                payload["reply"] = {
                    "in_reply_to_tweet_id": posted_ids[-1]
                }
                
            logger.info(f"Dispatched X tweet request (part {idx + 1}): {part[:30]}...")
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
                
                # Fallback simulator for testing
                if resp.status_code != 201 and "mock" in access_token:
                    logger.warning("Mock access token used. Simulating successful publication.")
                    tweet_id = f"mock_tweet_id_{idx + 1}"
                else:
                    try:
                        resp.raise_for_status()
                        tweet_id = resp.json().get("data", {}).get("id")
                        if not tweet_id:
                            raise ValueError("X response missing tweet id in 'data'")
                    except Exception as e:
                        # Construct informative error message
                        error_msg = f"Failed to post part {idx + 1}: {str(e)}"
                        if resp.status_code == 429:
                            error_msg = f"Rate limit exceeded (429) posting part {idx + 1}: {resp.text}"
                        elif resp.status_code in (401, 403):
                            error_msg = f"Auth/Tier error ({resp.status_code}) posting part {idx + 1}: {resp.text}"
                        raise XPublishingError(error_msg, posted_ids)
                        
                posted_ids.append(tweet_id)
                
        return posted_ids

    async def exchange_code_for_tokens(self, code: str, redirect_uri: str, code_verifier: str) -> dict:
        """Exchange redirect code and code verifier for initial access and refresh tokens (OAuth 2.0 PKCE)."""
        url = f"{self.api_url}/2/oauth2/token"
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self.client_id,
        }
        if self.client_secret and self.client_secret != "mock_x_client_secret":
            data["client_secret"] = self.client_secret
            
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data)
            if resp.status_code != 200 and self.client_id == "mock_x_client_id":
                logger.warning("Mock credentials found. Simulating successful OAuth token exchange.")
                return {
                    "access_token": "mock_x_access_token",
                    "refresh_token": "mock_x_refresh_token",
                    "expires_in": 7200,
                }
            resp.raise_for_status()
            return resp.json()

    async def fetch_user_profile(self, access_token: str) -> dict:
        """Fetch authenticated user profile details using users/me endpoint."""
        url = f"{self.api_url}/2/users/me"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200 and "mock" in access_token:
                return {
                    "id": "mock_twitter_id",
                    "username": "mock_username"
                }
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return {
                "id": str(data.get("id")),
                "username": data.get("username")
            }

    async def fetch_tweet_metrics(self, db: AsyncSession, account: XAccount, tweet_ids: List[str]) -> dict:
        """Fetch public metrics (likes, retweets, replies, impressions) for a batch of tweet IDs."""
        access_token = await self.check_and_refresh_token(db, account)
        
        url = f"{self.api_url}/2/tweets"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        params = {
            "ids": ",".join(tweet_ids),
            "tweet.fields": "public_metrics"
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, params=params)
            
            # Mock fallback
            if resp.status_code != 200 and "mock" in access_token:
                logger.warning("Mock access token used. Simulating tweet metrics response.")
                return {
                    "data": [
                        {
                            "id": tid,
                            "public_metrics": {
                                "retweet_count": 10,
                                "reply_count": 2,
                                "like_count": 25,
                                "quote_count": 1,
                                "impression_count": 500
                            }
                        } for tid in tweet_ids
                    ]
                }
                
            resp.raise_for_status()
            return resp.json()
