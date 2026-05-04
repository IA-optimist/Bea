"""
Email notification client
Sends notifications via SMTP
"""
from __future__ import annotations
import os
import smtplib
import structlog
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .models import NotificationPayload

log = structlog.get_logger()


class EmailNotificationClient:
    """
    SMTP email notification client
    
    Configuration via environment variables:
    - SMTP_HOST: SMTP server host
    - SMTP_PORT: SMTP server port (default: 587)
    - SMTP_USER: SMTP username
    - SMTP_PASSWORD: SMTP password
    - EMAIL_FROM: Sender email address
    """
    
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.email_from = os.getenv("EMAIL_FROM", "noreply@jarvismax.ai")
        
        self.enabled = bool(self.smtp_host and self.smtp_user and self.smtp_password)
        
        if not self.enabled:
            log.warning("email_notifications_disabled",
                        reason="SMTP credentials not configured")
    
    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Send notification via email
        
        Args:
            destination: Email address
            payload: NotificationPayload with message content
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            log.debug("email_notification_skipped", reason="not_enabled")
            return False
        
        try:
            subject = f"[JarvisMax] Mission {payload.status}: {payload.title[:50]}"
            html_body = self._format_html(payload)
            text_body = self._format_text(payload)
            
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.email_from
            msg["To"] = destination
            
            # Attach text and HTML parts
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            
            # Send via SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            log.info("email_notification_sent",
                     to=destination,
                     mission_id=payload.mission_id)
            return True
        
        except smtplib.SMTPException as e:
            log.error("smtp_error",
                      error=str(e),
                      mission_id=payload.mission_id,
                      to=destination)
            return False
        except Exception as e:
            log.error("email_send_error",
                      error=str(e),
                      mission_id=payload.mission_id,
                      to=destination)
            return False
    
    def _format_text(self, payload: NotificationPayload) -> str:
        """Format notification as plain text email"""
        emoji = {
            "DONE": "✓",
            "FAILED": "✗",
            "CANCELLED": "⊗",
            "COMPLETED": "✓",
        }.get(payload.status, "•")
        
        lines = [
            f"{emoji} Mission {payload.status}",
            "",
            f"Mission ID: {payload.mission_id}",
            f"Goal: {payload.title}",
            "",
        ]
        
        if payload.status in ("DONE", "COMPLETED") and payload.result:
            lines.append("Result:")
            lines.append(payload.result[:1000])
            if len(payload.result) > 1000:
                lines.append("... (truncated)")
        
        elif payload.status == "FAILED" and payload.error:
            lines.append("Error:")
            lines.append(payload.error[:1000])
            if len(payload.error) > 1000:
                lines.append("... (truncated)")
        
        lines.append("")
        lines.append("---")
        lines.append("JarvisMax Notification System")
        
        return "\n".join(lines)
    
    def _format_html(self, payload: NotificationPayload) -> str:
        """Format notification as HTML email"""
        status_color = {
            "DONE": "#28a745",
            "COMPLETED": "#28a745",
            "FAILED": "#dc3545",
            "CANCELLED": "#6c757d",
        }.get(payload.status, "#007bff")
        
        emoji = {
            "DONE": "✅",
            "FAILED": "❌",
            "CANCELLED": "⛔",
            "COMPLETED": "✅",
        }.get(payload.status, "ℹ️")
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: {status_color}; color: white; padding: 15px; border-radius: 5px; }}
                .content {{ padding: 20px; background-color: #f8f9fa; border-radius: 5px; margin-top: 10px; }}
                .mission-id {{ font-family: monospace; background-color: #e9ecef; padding: 5px; border-radius: 3px; }}
                .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>{emoji} Mission {payload.status}</h2>
                </div>
                <div class="content">
                    <p><strong>Mission ID:</strong> <span class="mission-id">{payload.mission_id}</span></p>
                    <p><strong>Goal:</strong> {self._escape_html(payload.title)}</p>
        """
        
        if payload.status in ("DONE", "COMPLETED") and payload.result:
            result_preview = payload.result[:1000]
            if len(payload.result) > 1000:
                result_preview += "..."
            html += f"""
                    <p><strong>Result:</strong></p>
                    <pre style="background-color: white; padding: 10px; border-radius: 5px; overflow-x: auto;">{self._escape_html(result_preview)}</pre>
            """
        
        elif payload.status == "FAILED" and payload.error:
            error_preview = payload.error[:1000]
            if len(payload.error) > 1000:
                error_preview += "..."
            html += f"""
                    <p><strong>Error:</strong></p>
                    <pre style="background-color: #ffe6e6; padding: 10px; border-radius: 5px; overflow-x: auto;">{self._escape_html(error_preview)}</pre>
            """
        
        html += """
                </div>
                <div class="footer">
                    <p>JarvisMax Notification System</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))
