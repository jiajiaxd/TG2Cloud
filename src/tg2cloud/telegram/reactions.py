"""Report transfer states on the incoming Telegram messages."""
from __future__ import annotations

import asyncio
import time

from telethon.errors import FloodWaitError, MessageNotModifiedError
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

from tg2cloud.domain.states import FAILED_STATES

RECEIVED = "👀"
REJECTED = "👎"
PENDING = "🤔"
DUPLICATE = "🤝"
CANCELLED = "🫡"

STATE_REACTIONS = {
    "queued": RECEIVED,
    "reserved": RECEIVED,
    "downloading": "⚡",
    "streaming": "🔥",
    "downloaded": "👌",
    "waiting_upload": "👌",
    "uploading": "👨‍💻",
    "verifying": "👨‍💻",
    "finalizing": "👨‍💻",
    "cleanup_pending": "👨‍💻",
    "completed": "👍",
    "confirmed": "👍",
    "cancelled": CANCELLED,
    **dict.fromkeys(FAILED_STATES, "😢"),
}


class MessageReactions:
    def __init__(self, service):
        self.service = service
        self.pending: dict[tuple[int, int], str] = {}
        self.ready = asyncio.Event()
        self.retry_at = 0.0

    def queue(self, chat_id: int, message_id: int, emoji: str) -> None:
        self.pending[chat_id, message_id] = emoji
        self.ready.set()

    async def flush(self, cursor: int) -> int:
        if time.monotonic() < self.retry_at:
            return cursor
        owner = self.service
        events = owner.db.task_state_changes(cursor)
        for event in events:
            cursor = event["event_id"]
            if (event["read_identity"] != "bot" or event["chat_id"] != event["sender_id"]
                    or not owner._authorized(event["sender_id"])):
                continue
            emoji = STATE_REACTIONS.get(event["state"])
            if emoji and STATE_REACTIONS.get(event["old_state"]) != STATE_REACTIONS.get(event["new_state"]):
                self.pending[event["chat_id"], event["message_id"]] = emoji

        for chat_id, message_id in list(self.pending):
            if not owner._authorized(chat_id):
                self.pending.pop((chat_id, message_id), None)
                continue
            # Pop before I/O so a newer update can replace this one during the request.
            emoji = self.pending.pop((chat_id, message_id))
            try:
                request = SendReactionRequest(peer=chat_id, msg_id=message_id, reaction=[ReactionEmoji(emoji)])
                await asyncio.wait_for(owner.client(request, flood_sleep_threshold=0), timeout=5)
            except MessageNotModifiedError:
                pass
            except FloodWaitError as exc:
                self.pending.setdefault((chat_id, message_id), emoji)
                self.retry_at = time.monotonic() + exc.seconds
                break
            except Exception as exc:  # noqa: BLE001 - reactions are best-effort Telegram I/O
                owner.log.warning("更新 Telegram 消息 %s 的表情回应失败：%s", message_id, type(exc).__name__)
        return cursor

    async def run(self, cursor: int) -> None:
        while not self.service._stop.is_set():
            self.ready.clear()
            cursor = await self.flush(cursor)
            delay = self.retry_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
            try:
                await asyncio.wait_for(self.ready.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
