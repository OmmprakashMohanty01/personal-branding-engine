import os
import logging
import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import SubstackAccount

logger = logging.getLogger("branding_engine.publishing.substack.client")

class SubstackClient:
    """Publishing client wrapper that converts markdown to HTML and dispatches it to Substack via SMTP email."""
    
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")

    def _send_email_sync(self, author_email: str, target_email: str, subject: str, html_content: str) -> None:
        """Synchronous SMTP email dispatch wrapper."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = author_email
        msg["To"] = target_email
        
        # Attach HTML content
        part_html = MIMEText(html_content, "html")
        msg.attach(part_html)
        
        # Connection setup
        if self.smtp_port == 465:
            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
            
        try:
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(author_email, target_email, msg.as_string())
        finally:
            server.quit()

    async def publish_post(self, db: AsyncSession, account: SubstackAccount, text: str) -> None:
        """Parse markdown post, extract subject title, parse rest to HTML, and send asynchronously."""
        if not text.strip():
            raise ValueError("Draft content is empty.")
            
        all_lines = text.split("\n")
        
        # Extract title from the first non-empty line
        try:
            first_line_idx = next(i for i, line in enumerate(all_lines) if line.strip())
            subject_raw = all_lines[first_line_idx]
            subject = subject_raw.lstrip("#").strip().strip("*").strip()
            rest_content = "\n".join(all_lines[first_line_idx + 1:])
        except StopIteration:
            subject = "Weekly Newsletter"
            rest_content = text

        # Parse rest of markdown to HTML with standard extensions (tables, fenced code)
        import markdown
        html_body = markdown.markdown(rest_content, extensions=['fenced_code', 'tables'])
        
        # Dispatch SMTP call in a non-blocking thread pool
        await asyncio.to_thread(
            self._send_email_sync,
            author_email=account.author_email,
            target_email=account.secret_email_address,
            subject=subject,
            html_content=html_body
        )
