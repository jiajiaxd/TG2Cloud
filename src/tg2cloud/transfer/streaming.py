from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from tg2cloud.domain.actors import task_actor
from tg2cloud.domain.errors import (
    RemoteReviewRequired,
    failure_kind,
    safe_failure,
)
from tg2cloud.domain.naming import (
    safe_file_name,
)
from tg2cloud.monitoring.notifications import notify_listener_task
from tg2cloud.storage.policies import policy_for
from tg2cloud.storage.rclone import MoveUncertainError


async def _finalize_stream_remote(
    self,
    task_id: int,
    task: dict[str, Any],
    remote_path: str,
    safe_name: str,
    local_path: Path | None = None,
) -> None:
    final_remote = remote_path
    move_completed = False
    if remote_path.startswith(".uploading-"):
        async with self._finalize_lock:
            current = self.db.get(task_id) or task
            final_remote = str(current.get("remote_final_path") or "")
            if not final_remote:
                final_remote = await self._choose_remote_final(safe_name, task_id)
            elif await self.rclone.exists(final_remote):
                raise RemoteReviewRequired("预留正式路径已经存在；保留数据，等待复核")
            self.db.transition(
                task_id,
                "finalizing",
                remote_path=final_remote,
                remote_temp_path=remote_path,
                remote_final_path=final_remote,
            )
            await self.rclone.move(remote_path, final_remote)
            move_completed = True
    try:
        final_size = await self.rclone.remote_size(final_remote)
    except Exception as exc:
        if move_completed and policy_for(self.settings).direct_final:
            raise MoveUncertainError(
                "MOVE_UNCERTAIN: OpenList 改名后的目标文件暂时无法复验；"
                "已停止自动重试并保留文件供核对。"
            ) from exc
        raise
    if final_size != int(task["file_size"]):
        if move_completed and policy_for(self.settings).direct_final:
            raise MoveUncertainError(
                "MOVE_UNCERTAIN: OpenList 改名后的目标文件大小不符；"
                "已停止自动重试并保留文件供核对。"
            )
        raise RemoteReviewRequired(
            f"流式改名后远端大小错误：{final_size} != {task['file_size']}"
        )
    await self._complete_cloud_receive(
        task_id, task, local_path, final_remote
    )


async def _begin_remote_write(
    self,
    task_id: int,
    task: dict[str, Any],
    safe_name: str,
    state: str,
    remote_temp: str,
    **fields: Any,
) -> str:
    return await policy_for(self.settings).begin(
        self, task_id, task, safe_name, state, remote_temp, **fields,
    )




@task_actor
async def _stream_one(self, task_id: int) -> None:
    task = self.db.get(task_id)
    if not task:
        return
    safe_name = safe_file_name(task["file_name"], f"task-{task_id}.bin")
    remote_temp = self.db.staging_name(task_id, safe_name)
    stream = None
    last_failure = None
    try:
        from tg2cloud.listening.service import ListenerReadError, task_source
        source = task_source(self, task)
        for attempt in range(
            int(task["download_retries"]), self.settings.max_retries
        ):
            try:
                if await self._resume_remote(task_id, task, None, safe_name):
                    return
                message = await source.get_messages(
                    int(task["chat_id"]), ids=int(task["message_id"])
                )
                if not message or not message.media:
                    raise RuntimeError("Telegram 消息或文件已经不可访问")
                remote_write = await self._begin_remote_write(
                    task_id, task, safe_name, "streaming", remote_temp,
                    transfer_mode="stream",
                    local_path=None,
                    downloaded_bytes=0,
                    uploaded_bytes=0,
                    download_retries=attempt,
                    error=None,
                    wait_reason=None,
                )
                stream = await self.rclone.open_upload_stream(
                    remote_write, int(task["file_size"])
                )
                last_progress_at = 0.0

                def progress(received: int, total: int) -> None:
                    nonlocal last_progress_at
                    now = time.monotonic()
                    if now - last_progress_at >= 1 or received >= total:
                        self.db.update(
                            task_id,
                            downloaded_bytes=int(received),
                            uploaded_bytes=int(received),
                        )
                        self._record_progress(task_id, "stream", int(received))
                        last_progress_at = now

                self._record_progress(task_id, "stream", 0, reset=True)
                await source.download_media(
                    message,
                    file=stream,
                    progress_callback=progress,
                )
                streamed_size = stream.tell()
                if streamed_size != int(task["file_size"]):
                    raise RuntimeError(
                        f"流式读取大小错误：{streamed_size} "
                        f"!= {task['file_size']}"
                    )
                await stream.finish()
                self.db.transition(task_id, "verifying")
                remote_size = await self.rclone.remote_size(remote_write)
                if remote_size != int(task["file_size"]):
                    raise RemoteReviewRequired(
                        f"流式远端大小错误：{remote_size} "
                        f"!= {task['file_size']}"
                    )
                await self._finalize_stream_remote(
                    task_id, task, remote_write, safe_name
                )
                return
            except asyncio.CancelledError:
                raise
            except ListenerReadError as exc:
                if stream is not None:
                    await stream.abort()
                current = self.db.get(task_id)
                if not current or current["cancel_requested"] or current["state"] not in {"reserved", "streaming"}:
                    return
                self.db.transition(task_id, "download_failed", local_path=None,
                                   error=str(exc), failure_kind=exc.failure_kind)
                if exc.failure_kind == "rate_limited":
                    await self._notify(f"⏳ 任务 #{task_id}：{exc}；流式远端现场已保留，请在冷却后核对恢复。")
                else:
                    await self._notify(f"⚠️ 任务 #{task_id} 未能读取监听附件：{exc}；已有远端现场保留供核对。")
                return
            except MoveUncertainError as exc:
                if stream is not None:
                    await stream.abort()
                self.db.transition(
                    task_id, "download_failed", error=safe_failure(exc), failure_kind="remote_conflict",
                    verification_method=None, verified_at=None,
                    wait_reason="OpenList 改名结果未确认；停止自动重试并保留远端现场",
                )
                await notify_listener_task(
                    self, task,
                    f"❌ OpenList 改名结果未确认，任务 #{task_id} 已停止自动重试。"
                    "请先核对远端临时文件与目标文件。"
                )
                return
            except Exception as exc:  # noqa: BLE001 - retry external I/O
                if stream is not None:
                    await stream.abort()
                    stream = None
                if await self._hold_transfer_failure(task, exc, stream=True):
                    return
                # Unknown remote results are reconciled on the next attempt;
                # never discard a possibly recoverable staging object here.
                self.recent_download_errors.append(time.time())
                self.recent_upload_errors.append(time.time())
                self.log.warning(
                    "任务 #%s 流式传输第 %s 次失败：%s",
                    task_id,
                    attempt + 1,
                    safe_failure(exc),
                )
                last_failure = safe_failure(exc)
                self.db.update(
                    task_id,
                    download_retries=attempt + 1,
                    error=last_failure, failure_kind=failure_kind(exc),
                )
                if attempt + 1 < self.settings.max_retries:
                    await asyncio.sleep(min(120, 3 ** (attempt + 1)))
        current = self.db.get(task_id) or task
        retained_remote = str(current.get("remote_path") or "")
        self.db.transition(
            task_id,
            "download_failed",
            local_path=None,
            remote_path=retained_remote or None,
            error="流式传输重试次数已经用完"
                  + ("；" + last_failure if last_failure else "")
                  + "；使用 /retry 可重新开始",
            wait_reason=None,
        )
        await notify_listener_task(
            self, task,
            f"❌ 流式传输失败\n任务：#{task_id}\n"
            "大文件不会占用本地任务额度，可使用 /retry 重新开始。"
        )
    except asyncio.CancelledError:
        if stream is not None:
            await stream.abort()
        current = self.db.get(task_id)
        recorded_remote = (
            str(current.get("remote_path") or "") if current else ""
        )
        if current and current["state"] not in {"cancelled", "cleanup_pending", "completed", "confirmed"}:
            self.db.transition(
                task_id,
                "queued",
                local_path=None,
                remote_path=recorded_remote or None,
                downloaded_bytes=0,
                uploaded_bytes=0,
                wait_reason="流式任务已暂停并自动重新排队",
            )
        raise
    except Exception as exc:
        self.log.exception("任务 #%s 流式传输发生未处理异常", task_id)
        self.db.transition(
            task_id,
            "download_failed",
            local_path=None,
            error=safe_failure(exc),
        )
