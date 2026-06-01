import httpx
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("branding_engine.monitoring.alerts")

class AlertManager:
    """Dispatches real-time structured system alerts to Discord or Slack channels."""
    
    def __init__(self):
        self.webhook_url = settings.ALERT_WEBHOOK_URL
        self.provider = (settings.ALERT_PROVIDER or "discord").lower()

    async def send_alert(self, message: str, severity: str = "INFO") -> bool:
        """Asynchronously posts an alert message to the configured Discord or Slack webhook.
        
        Args:
            message: The alert body text.
            severity: ALERT severity levels ('INFO', 'WARNING', 'CRITICAL').
            
        Returns:
            bool: True if alert successfully triggered (or no-op skipped), False on failure.
        """
        if not self.webhook_url:
            logger.info("ALERT_WEBHOOK_URL is not configured. Alert dispatch skipped.")
            return True
            
        severity_upper = severity.upper()
        
        # Determine prefix emoji
        if severity_upper == "CRITICAL":
            emoji = "🚨 [CRITICAL]"
        elif severity_upper == "WARNING":
            emoji = "⚠️ [WARNING]"
        else:
            emoji = "📢 [INFO]"
            
        full_text = f"{emoji} {message}"
        
        # Build payload according to provider structure
        if self.provider == "slack":
            payload = {"text": full_text}
        else: # default to discord
            payload = {"content": full_text}
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.webhook_url, json=payload, timeout=5.0)
                resp.raise_for_status()
                logger.info(f"System alert successfully dispatched to {self.provider} ({severity_upper}).")
                return True
        except Exception as e:
            # Catch all exceptions (connection timeouts, bad status codes) gracefully 
            # to prevent alerts from crashing core workflow engines
            logger.error(f"Failed to post system alert to {self.provider}: {e}")
            return False
