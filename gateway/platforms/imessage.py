"""iMessage platform adapter.

Connects to macOS Messages.app via the imsg CLI tool.
Uses SQLite polling on chat.db for inbound messages and imsg send for outbound.

Prerequisites:
  - macOS with Messages.app signed in
  - imsg CLI installed: brew install steipete/tap/imsg
  - Full Disk Access for terminal (System Settings → Privacy → Full Disk Access)
  - Automation permission for Messages.app

Gateway env vars:
  - IMESSAGE_ALLOWED_USERS   (comma-separated contact identifiers)
  - IMESSAGE_ALLOW_ALL_USERS (true/false)
  - IMESSAGE_HOME_CHANNEL    (contact identifier for cron delivery)
  - IMESSAGE_POLL_INTERVAL   (seconds between polls, default: 2)
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    cache_image_from_bytes,
)

logger = logging.getLogger(__name__)

# chat.db location
MESSAGES_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# imsg CLI path (Homebrew default location on Apple Silicon)
# Also check Intel Mac location as fallback
IMSG_PATHS = [
    Path("/opt/homebrew/bin/imsg"),  # Apple Silicon
    Path("/usr/local/bin/imsg"),     # Intel Mac
]

# Polling configuration
DEFAULT_POLL_INTERVAL = 2.0  # seconds
MAX_MESSAGE_LENGTH = 16000  # iMessage supports long messages

# Contact/phone pattern for redaction
_PHONE_RE = re.compile(r"\+[1-9]\d{6,14}")


def _get_imsg_path() -> Optional[str]:
    """Find the imsg CLI binary, checking common Homebrew locations."""
    # First try PATH (works in interactive shells)
    import shutil
    path = shutil.which("imsg")
    if path:
        return path
    
    # Then check known Homebrew locations (works in launchd)
    for imsg_path in IMSG_PATHS:
        if imsg_path.exists():
            return str(imsg_path)
    
    return None


def _redact_phone(phone: str) -> str:
    """Redact a phone number for logging."""
    if not phone:
        return "<none>"
    if len(phone) <= 8:
        return phone[:2] + "***" + phone[-2:] if len(phone) > 4 else "****"
    return phone[:5] + "***" + phone[-4:]


def check_imessage_requirements() -> bool:
    """Check if iMessage adapter dependencies are available."""
    # Check imsg CLI exists (using full path search for launchd compatibility)
    imsg_path = _get_imsg_path()
    if not imsg_path:
        logger.warning("[imessage] imsg CLI not found in PATH or Homebrew locations")
        return False
    
    # Check chat.db exists
    if not MESSAGES_DB_PATH.exists():
        logger.warning("[imessage] Messages database not found at %s", MESSAGES_DB_PATH)
        return False
    
    # Check environment
    if not os.getenv("IMESSAGE_ALLOWED_USERS"):
        logger.warning("[imessage] IMESSAGE_ALLOWED_USERS not set")
        return False
    
    return True


@dataclass
class SeenMessage:
    """Track seen messages to avoid duplicates."""
    row_id: int
    timestamp: float
    text: str
    is_from_me: bool


class IMessageAdapter(BasePlatformAdapter):
    """
    iMessage <-> Hermes gateway adapter.
    
    Uses imsg CLI for sending and direct chat.db polling for receiving.
    Each contact/chat gets its own Hermes session.
    """
    
    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
    
    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.IMESSAGE)
        self._poll_interval = float(os.getenv("IMESSAGE_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))
        self._allowed_users = self._parse_allowed_users()
        
        # State tracking
        self._seen_messages: Dict[str, SeenMessage] = {}  # chat_id -> last seen
        self._recent_sent: List[Tuple[str, float]] = []  # (chat_id, timestamp) to filter echoes
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Contact cache
        self._contact_cache: Dict[str, str] = {}  # chat_id -> display name
        
        logger.info("[imessage] Adapter initialized, poll interval: %.1fs", self._poll_interval)
    
    def _parse_allowed_users(self) -> List[str]:
        """Parse allowed users from environment."""
        allowed_str = os.getenv("IMESSAGE_ALLOWED_USERS", "")
        if allowed_str.strip():
            return [u.strip() for u in allowed_str.split(",") if u.strip()]
        return []
    
    def _is_user_allowed(self, chat_id: str) -> bool:
        """Check if a user/chat is allowed."""
        if os.getenv("IMESSAGE_ALLOW_ALL_USERS", "").lower() == "true":
            return True
        if not self._allowed_users:
            return False
        return chat_id in self._allowed_users
    
    def _filter_echo(self, chat_id: str, text: str, timestamp: float) -> bool:
        """Check if this message is an echo of something we just sent."""
        # Clean old entries (older than 5 seconds)
        cutoff = time.time() - 5.0
        self._recent_sent = [(cid, ts) for cid, ts in self._recent_sent if ts > cutoff]
        
        # Check if we sent something identical to this chat recently
        for sent_chat_id, sent_ts in self._recent_sent:
            if sent_chat_id == chat_id and abs(timestamp - sent_ts) < 3.0:
                return True
        return False
    
    def _record_sent(self, chat_id: str, timestamp: float) -> None:
        """Record a message we sent to filter echoes."""
        self._recent_sent.append((chat_id, timestamp))
        # Keep only last 20 entries
        if len(self._recent_sent) > 20:
            self._recent_sent = self._recent_sent[-20:]
    
    async def _poll_messages(self) -> None:
        """Poll chat.db for new messages."""
        import sqlite3
        
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error("[imessage] Poll error: %s", e)
            await asyncio.sleep(self._poll_interval)
    
    async def _poll_once(self) -> None:
        """Single poll iteration."""
        if not MESSAGES_DB_PATH.exists():
            return
        
        try:
            # Connect to chat.db (read-only)
            conn = sqlite3.connect(f"file:{MESSAGES_DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get recent messages (last 50)
            # message table schema: rowid, guid, text, handle_id, is_from_me, date, chat_id
            cursor.execute("""
                SELECT 
                    m.rowid,
                    m.text,
                    m.is_from_me,
                    m.date,
                    h.id as handle,
                    c.chat_identifier,
                    c.display_name
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.rowid
                LEFT JOIN chat_message_join cmj ON m.rowid = cmj.message_id
                LEFT JOIN chat c ON cmj.chat_id = c.rowid
                WHERE m.text IS NOT NULL 
                  AND m.text != ''
                  AND m.is_from_me = 0
                ORDER BY m.date DESC
                LIMIT 50
            """)
            
            rows = cursor.fetchall()
            conn.close()
            
            for row in rows:
                chat_id = row["chat_identifier"] or row["handle"] or "unknown"
                text = row["text"] or ""
                timestamp = row["date"]  # iMessage timestamp (seconds since 2001)
                handle = row["handle"] or ""
                display_name = row["display_name"] or ""
                
                # Convert iMessage timestamp to Unix timestamp
                # iMessage uses seconds since 2001-01-01
                unix_timestamp = timestamp + 978307200 if timestamp else time.time()
                
                # Skip if we've seen this message
                if chat_id in self._seen_messages:
                    if self._seen_messages[chat_id].row_id >= row["rowid"]:
                        continue
                
                # Skip if not allowed
                if not self._is_user_allowed(chat_id):
                    continue
                
                # Skip echoes
                if self._filter_echo(chat_id, text, unix_timestamp):
                    logger.debug("[imessage] Skipping echo from %s", _redact_phone(chat_id))
                    continue
                
                # Build session source
                source = self.build_source(
                    chat_id=chat_id,
                    chat_name=display_name or handle or chat_id,
                    chat_type="dm",
                    user_id=handle or chat_id,
                    user_name=display_name or handle or chat_id,
                )
                
                # Build message event
                event = MessageEvent(
                    text=text,
                    message_type=MessageType.TEXT,
                    source=source,
                    message_id=str(row["rowid"]),
                )
                
                # Dispatch to gateway
                await self.handle_message(event)
                
                # Update seen tracking
                self._seen_messages[chat_id] = SeenMessage(
                    row_id=row["rowid"],
                    timestamp=unix_timestamp,
                    text=text,
                    is_from_me=False,
                )
                
                logger.debug(
                    "[imessage] Received from %s: %s",
                    _redact_phone(chat_id),
                    text[:50] + "..." if len(text) > 50 else text
                )
                
        except sqlite3.Error as e:
            logger.error("[imessage] Database error: %s", e)
        except Exception as e:
            logger.error("[imessage] Poll error: %s", e)
    
    async def connect(self) -> bool:
        """Start the polling loop."""
        if not check_imessage_requirements():
            logger.error("[imessage] Requirements not met")
            return False
        
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_messages())
        
        logger.info("[imessage] Connected, polling every %.1fs", self._poll_interval)
        return True
    
    async def disconnect(self) -> None:
        """Stop polling."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        
        logger.info("[imessage] Disconnected")
    
    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send an iMessage using imsg CLI."""
        formatted = self.format_message(content)
        chunks = self.truncate_message(formatted)
        
        last_result = SendResult(success=True)
        
        for chunk in chunks:
            try:
                # Use imsg send command with full path for launchd compatibility
                imsg_path = _get_imsg_path() or "imsg"
                cmd = [imsg_path, "send", "--to", chat_id, "--text", chunk]
                
                # Determine service (imessage vs sms)
                # Default to "auto" to let Messages.app choose (iMessage for Apple devices, SMS for Android)
                if metadata and metadata.get("service") == "sms":
                    cmd.extend(["--service", "sms"])
                elif metadata and metadata.get("service") == "imessage":
                    cmd.extend(["--service", "imessage"])
                else:
                    # Auto-detect: iMessage for Apple devices, SMS for others
                    cmd.extend(["--service", "auto"])
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                
                if result.returncode != 0:
                    logger.error(
                        "[imessage] Send failed to %s: %s",
                        _redact_phone(chat_id),
                        result.stderr.strip() if result.stderr else "unknown error"
                    )
                    last_result = SendResult(success=False, error=result.stderr)
                else:
                    # Record sent message for echo filtering
                    self._record_sent(chat_id, time.time())
                    logger.debug(
                        "[imessage] Sent to %s: %s",
                        _redact_phone(chat_id),
                        chunk[:50] + "..." if len(chunk) > 50 else chunk
                    )
                    
            except subprocess.TimeoutExpired:
                logger.error("[imessage] Send timeout to %s", _redact_phone(chat_id))
                last_result = SendResult(success=False, error="timeout")
            except Exception as e:
                logger.error("[imessage] Send error to %s: %s", _redact_phone(chat_id), e)
                last_result = SendResult(success=False, error=str(e))
        
        return last_result
    
    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """iMessage doesn't support programmatic typing indicators via imsg."""
        pass
    
    def get_chat_info(self, chat_id: str) -> dict:
        """Get chat information."""
        return {
            "name": self._contact_cache.get(chat_id, chat_id),
            "type": "direct",  # Could detect groups
            "chat_id": chat_id,
        }
    
    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Send an image (not fully supported by imsg)."""
        # imsg supports --file but requires local path
        # For now, send caption only
        if caption:
            return await self.send(chat_id, caption)
        return SendResult(success=False, error="Image sending not supported")
