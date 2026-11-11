from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from telethon import events

from tg2cloud.domain.actors import current_user, user_event
from tg2cloud.domain.naming import (
    album_file_name,
    caption_candidate,
    clean_promotional_affixes,
    media_file_name,
    safe_file_name,
    video_extension,
    video_file_name,
)
from tg2cloud.domain.states import FAILED_STATES
from tg2cloud.telegram.reactions import CANCELLED, DUPLICATE, RECEIVED, REJECTED


class TelegramHandlers:
    def _register_handlers(self) -> None:
        self.client.add_event_handler(self._on_message, events.NewMessage(incoming=True))
        self.client.add_event_handler(self._on_callback, events.CallbackQuery())
        self.client.add_event_handler(self._on_album, events.Album())

    def _authorized(self, sender_id: int | None) -> bool:
        if sender_id == self.settings.allowed_user_id:
            return True
        if type(sender_id) is not int or sender_id <= 0:
            return False
        try:
            members = self.db.family_users(self.settings.allowed_user_id)["users"]
            return any(member["id"] == sender_id and member["enabled"] for member in members)
        except Exception:  # noqa: BLE001 - unreadable grants must never authorize members
            # Unknown/corrupt grants never expand access; the original owner remains.
            return False

    @staticmethod
    def _media_key(message: Any) -> str | None:
        document = getattr(message, "document", None)
        document_id = getattr(document, "id", None)
        if document_id is not None:
            return f"document:{document_id}"
        photo = getattr(message, "photo", None)
        photo_id = getattr(photo, "id", None)
        if photo_id is not None:
            return f"photo:{photo_id}"
        return None

    @staticmethod
    def _media_kind(message: Any) -> str:
        mime = str(getattr(getattr(message, "file", None), "mime_type", ""))
        if getattr(message, "video", None) or mime.startswith("video/"):
            return "视频"
        if getattr(message, "photo", None) or mime.startswith("image/"):
            return "图片"
        return ""

    @staticmethod
    def _album_extension(message: Any, kind: str) -> str:
        file = getattr(message, "file", None)
        if not file:
            return ".bin"
        extension = (video_extension(file.name or "", getattr(file, "ext", None) or "")
                     if kind == "视频" else file.ext or Path(file.name or "").suffix or ".jpg")
        # Use the same validation as the final name before deciding whether two
        # suffixes really distinguish a pair (unknown/invalid types become bin).
        return Path(album_file_name("media", kind, None, extension)).suffix

    @staticmethod
    def _media_caption(message: Any, fallback: str = "") -> str:
        # Only text actually delivered with this message. Forwarding metadata,
        # reply ids and channel names are not a license to fetch other messages.
        for field in ("raw_text", "message"):
            value = getattr(message, field, None)
            if isinstance(value, str) and value.strip():
                return value[:8192]
        return fallback[:8192] if isinstance(fallback, str) else ""

    @user_event
    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        if (
            not self._authorized(event.sender_id)
            or getattr(event, "chat_id", None) != event.sender_id
        ):
            self.log.warning("忽略未授权或非私聊按钮操作")
            await event.answer("无权执行这个操作。", alert=True)
            return
        await self._handle_callback(event)

    @user_event
    async def _on_album(self, event: events.Album.Event) -> None:
        if (not self._authorized(event.sender_id) or not event.is_private
                or event.chat_id != event.sender_id):
            return
        messages = event.messages
        if not messages or not event.grouped_id or any(
            message.sender_id != event.sender_id or message.chat_id != event.chat_id
            or message.grouped_id != event.grouped_id or message.out
            for message in messages
        ):
            return
        if len(messages) > 100:
            self.reactions.queue(event.chat_id, min(message.id for message in messages), REJECTED)
            return
        # Telegram updates may arrive out of order or be repeated. Use only this
        # received group, ordered by message id; never fetch channel history.
        messages = sorted({message.id: message for message in messages}.values(), key=lambda item: item.id)
        title = ""
        if len(messages) > 1:
            # The same bounded quality score as a single video, not raw length:
            # an explicit title must beat a longer advertisement/category label.
            try:
                titles = (caption_candidate(self._media_caption(message), getattr(message, "entities", ()))
                          for message in messages)
                title = max(titles, key=lambda candidate: candidate[1], default=("", -1))[0]
            except Exception:  # noqa: BLE001 - optional naming must not prevent ingestion
                self.log.warning("媒体组标题识别失败，使用原有文件命名；未影响任务接收。")
        numbers = {"视频": 0, "图片": 0}
        kinds = [self._media_kind(message) for message in messages]
        extensions = [self._album_extension(message, kind) if title and kind else ""
                      for message, kind in zip(messages, kinds)]
        # A verified cover/video pair is unambiguous: different real suffixes
        # distinguish the two files. Larger groups retain existing kind counters.
        pair = (len(messages) == 2 and set(kinds) == {"视频", "图片"}
                and all(message.file for message in messages)
                and len({extension.casefold() for extension in extensions}) == 2)
        deliveries = []
        group_created_at = time.time()
        group_options = self.db.feature_settings()
        for message, kind, extension in zip(messages, kinds, extensions):
            file = message.file
            name = None
            from tg2cloud.domain.planning import fields
            tokens = fields((file.name or "") + " " + self._media_caption(message)) if file else {}
            if title and kind and file and not (tokens.get("episode") or tokens.get("chapter")):
                numbers[kind] += 1
                name = album_file_name(title, kind, None if pair else numbers[kind], extension)
            proxy = SimpleNamespace(sender_id=message.sender_id, chat_id=message.chat_id,
                                    is_private=True, message=message, raw_text=self._media_caption(message))
            deliveries.append(self._on_message(proxy, album_name=name, album_delivery=True, created_at=group_created_at,
                                              classification_options=group_options))
        results = await asyncio.gather(*deliveries, return_exceptions=True)
        for message, result in zip(messages, results):
            if isinstance(result, Exception):
                self.log.error("媒体组消息 %s 接收失败；请核对任务列表后重发。", message.id)

    @user_event
    async def _on_message(self, event: events.NewMessage.Event, *,
                          album_name: str | None = None, album_delivery: bool = False,
                          created_at: float | None = None, classification_options: dict | None = None) -> None:
        if not self._authorized(event.sender_id) or not getattr(event, "is_private", False):
            self.log.warning("忽略未授权或非私聊消息")
            return

        message = getattr(event, "message", None)
        if getattr(message, "grouped_id", None):
            if not album_delivery:
                # Album aggregates split updates for ~0.5 s. Keep a fallback for
                # singleton/late groups so an isolated grouped video is not lost.
                await asyncio.sleep(2)
            if self.db.has_message(int(event.chat_id), int(message.id)):
                return
        text = (event.raw_text or "").strip()
        # Captions belong to their media, even when they look like /start or a
        # path. Only text-only/non-downloadable messages dispatch commands.
        downloadable = bool(getattr(message, "media", None) and getattr(message, "file", None))
        if text.startswith("/") and not album_delivery and not downloadable:
            await self._handle_command(event, text)
            return

        if not downloadable:
            from tg2cloud.telegram.planning import text as planning_text
            if await planning_text(self, event, text):
                return

        chat_id, message_id = int(event.chat_id), int(message.id)
        if not downloadable:
            self.reactions.queue(chat_id, message_id, REJECTED)
            return
        file_size = int(message.file.size or 0)
        if file_size <= 0:
            self.reactions.queue(chat_id, message_id, REJECTED)
            return
        snapshot = getattr(self, "snapshot", None)
        if snapshot and (snapshot.disk_free <= self.settings.min_free_disk_bytes or any(
            free <= self.settings.min_free_disk_bytes for _, free in snapshot.filesystems
        )):
            self.reactions.queue(chat_id, message_id, REJECTED)
            return
        fallback = f"telegram-{message.id}{message.file.ext or '.bin'}"
        file_name = safe_file_name(clean_promotional_affixes(message.file.name or ""), fallback)
        kind = self._media_kind(message)
        if kind:
            try:
                if kind == "视频":
                    file_name = video_file_name(message.file.name or "", self._media_caption(message, text),
                                                fallback, getattr(message, "entities", ()),
                                                media_extension=getattr(message.file, "ext", None) or "")
                else:
                    file_name = media_file_name(message.file.name or "", self._media_caption(message, text),
                                                fallback, getattr(message, "entities", ()))
            except Exception:  # noqa: BLE001 - keep the safe original if optional metadata is malformed
                self.log.warning("媒体标题识别失败，使用原有文件命名；未影响任务接收。")
        if album_name:
            file_name = album_name
        try:
            from tg2cloud.telegram.planning import manual
            if await manual(self, event, message, file_name, created_at=created_at,
                            classification_options=classification_options):
                return
            task, created = self.db.create_task(
                chat_id=chat_id,
                message_id=message_id,
                sender_id=int(event.sender_id),
                media_key=self._media_key(message),
                file_name=file_name,
                file_size=file_size,
                original_file_name=safe_file_name(message.file.name or "", fallback),
                media_kind=kind, mime_type=str(getattr(message.file, "mime_type", "") or ""),
                media_extension=getattr(message.file, "ext", "") or Path(file_name).suffix,
                target_base=self.settings.cd2_target, created_at=created_at,
                classification_options=classification_options,
            )
        except (ValueError, RuntimeError) as exc:
            self.log.warning("消息 %s 未进入队列：%s", message_id, type(exc).__name__)
            self.reactions.queue(chat_id, message_id, REJECTED)
            return
        self._mark_task_delivery(chat_id, message_id, task, created)

    def _mark_task_delivery(self, chat_id: int, message_id: int, task: dict, created: bool) -> None:
        if created:
            self.reactions.queue(chat_id, message_id, RECEIVED)
        elif (chat_id, message_id) != (task["chat_id"], task["message_id"]):
            emoji = CANCELLED if task["state"] == "cancelled" else DUPLICATE
            self.reactions.queue(chat_id, message_id, emoji)

    async def _watch_loop(self) -> None:
        while not self._stop.is_set():
            for task_id, message in list(self._watch_messages.items()):
                task = self.db.get(task_id)
                if task is None or not self._authorized(task["sender_id"]):
                    self._watch_messages.pop(task_id, None)
                    continue
                text = self._format_task(task, verbose=True)
                try:
                    if text != getattr(message, "raw_text", None):
                        await asyncio.wait_for(message.edit(text), timeout=5)
                except Exception:  # noqa: BLE001 - Telegram progress is best-effort
                    self._watch_messages.pop(task_id, None)
                    self.log.warning("进度订阅更新失败，已停止订阅 #%s", task_id)
                if task["state"] in {*FAILED_STATES, "completed", "confirmed", "cancelled"}:
                    self._watch_messages.pop(task_id, None)
            await asyncio.sleep(5)

    async def _notify(self, message: str) -> None:
        target = current_user(self.settings.allowed_user_id)
        if not self._authorized(target):
            return
        try:
            await self.client.send_message(target, message)
        except Exception:
            self.log.exception("发送 Bot 通知失败")
