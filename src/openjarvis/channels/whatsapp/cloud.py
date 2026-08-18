"""WhatsApp Cloud API adapter kept beside the Baileys domain namespace."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from openjarvis.channels._stubs import BaseChannel, ChannelHandler, ChannelStatus
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@ChannelRegistry.register("whatsapp")
class WhatsAppChannel(BaseChannel):
    """WhatsApp Cloud API channel adapter (send-only)."""

    channel_id = "whatsapp"

    def __init__(
        self,
        access_token: str = "",
        *,
        phone_number_id: str = "",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._token = access_token or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self._phone_number_id = phone_number_id or os.environ.get(
            "WHATSAPP_PHONE_NUMBER_ID", ""
        )
        self._bus = bus
        self._handlers: List[ChannelHandler] = []
        self._status = ChannelStatus.DISCONNECTED

    def connect(self) -> None:
        """Mark as connected when a Cloud API token is configured."""
        if not self._token:
            logger.warning("No WhatsApp access token configured")
            self._status = ChannelStatus.ERROR
            return
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        self._status = ChannelStatus.DISCONNECTED

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        """Send a text message through the WhatsApp Cloud API."""
        if not self._token:
            logger.warning("Cannot send: no WhatsApp access token")
            return False
        try:
            import httpx

            response = httpx.post(
                f"https://graph.facebook.com/v21.0/{self._phone_number_id}/messages",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": channel,
                    "type": "text",
                    "text": {"body": content},
                },
                timeout=10.0,
            )
            if response.status_code < 300:
                self._publish_sent(channel, content, conversation_id)
                return True
            logger.warning("WhatsApp API returned status %d", response.status_code)
            return False
        except Exception:
            logger.debug("WhatsApp Cloud send failed", exc_info=True)
            return False

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> List[str]:
        return ["whatsapp"]

    def on_message(self, handler: ChannelHandler) -> None:
        self._handlers.append(handler)

    def _publish_sent(self, channel: str, content: str, conversation_id: str) -> None:
        if self._bus is not None:
            self._bus.publish(
                EventType.CHANNEL_MESSAGE_SENT,
                {
                    "channel": channel,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )


__all__ = ["WhatsAppChannel"]
