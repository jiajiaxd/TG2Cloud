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
from tg2cloud.storage.rclone import MoveUncertainError


async def _choose_remote_final(self, file_name: str, task_id: int) -> str:
    from tg2cloud.domain.classification import check_scope, safe_directory
    task = self.db.get(task_id) or {}
    check_scope(task, self.settings)
    directory = safe_directory(task.get("target_directory", ""))
    if directory:
        await self.rclone.ensure_directory(directory)
    def in_directory(name):
        return directory + "/" + name if directory else name
    def claimed(path: str) -> bool:
        check = getattr(getattr(self, "db", None), "remote_claimed", None)
        return bool(check and check(path, task_id))

    if not claimed(in_directory(file_name)) and not await self.rclone.exists(in_directory(file_name)):
        return in_directory(file_name)
    path = Path(file_name)
    candidate = in_directory(f"{path.stem} (task-{task_id}){path.suffix}")
    suffix = 2
    while claimed(candidate) or await self.rclone.exists(candidate):
        candidate = in_directory(f"{path.stem} (task-{task_id}-{suffix}){path.suffix}")
        suffix += 1
    return candidate


async def _hold_transfer_failure(self, task: dict[str, Any], exc: Exception, *, stream: bool = False) -> bool:
    kind = failure_kind(exc)
    if kind not in {"remote_conflict", "authentication", "permission", "rate_limited"}:
        return False
    task_id = task["id"]
    self.db.transition(
        task_id, "download_failed" if stream else "upload_failed_retained",
        error=safe_failure(exc), failure_kind=kind,
        verification_method=None, verified_at=None,
        wait_reason="已停止自动重试；请查看任务详情选择恢复操作", next_retry_at=0,
    )
    await notify_listener_task(
        self, task, f"⚠️ 任务 #{task_id} 需要处理\n{safe_failure(exc)}\n使用 /task {task_id} 查看详情。"
    )
    return True


async def _complete_cloud_receive(
    self,
    task_id: int,
    task: dict[str, Any],
    local_path: Path | None,
    final_remote: str,
) -> None:
    current = self.db.get(task_id) or task
    temp = str(current.get("remote_temp_path") or "")
    if temp and temp != final_remote and await self.rclone.exists(temp):
        await self.rclone.remove(temp)
        if await self.rclone.exists(temp):
            raise RuntimeError("改名后临时文件仍存在；保留本地副本等待安全清理")
    # Persist the verified remote result before deleting the local copy.
    # A restart between these operations can then resume cleanup without
    # re-uploading or creating a duplicate remote file.
    self.db.transition(
        task_id,
        "cleanup_pending",
        remote_path=final_remote,
        remote_final_path=final_remote,
        remote_temp_path=None,
        uploaded_bytes=int(task["file_size"]),
        verification_method="size", verified_at=time.time(), failure_kind=None,
        error=None,
        wait_reason="远端文件已校验，正在清理 VPS 本地副本",
        next_retry_at=0,
    )
    if local_path is not None:
        try:
            local_path.unlink(missing_ok=True)
        except OSError as exc:
            self.db.update(
                task_id,
                error=f"远端已接收，但 VPS 本地文件暂时无法清理：{exc}"[:1000],
                wait_reason="远端已接收；等待自动重试清理 VPS 本地副本",
                next_retry_at=time.time() + 60,
            )
            self.log.warning("任务 #%s 的本地副本清理失败：%s", task_id, exc)
            return
    self.db.transition(
        task_id,
        "completed",
        local_path=None,
        error=None,
        wait_reason=None,
        next_retry_at=0,
    )
    await notify_listener_task(
        self, task,
        f"✅ Bot 传输已完成，{self.destination_label} 已接收\n"
        f"任务：#{task_id}\n"
        f"文件：{task['file_name']}\n"
        f"{self.destination_label} 路径：{final_remote}\n"
        "WebDAV 远端大小已经复验，本地临时文件已经清理。"
    )


@task_actor
async def _upload_one(self, task_id: int) -> None:
    task = self.db.get(task_id)
    if not task or task.get("cancel_requested") or task.get("state") in {"completed", "confirmed", "cancelled"}:
        return
    from tg2cloud.domain.classification import check_scope
    from tg2cloud.domain.states import can_transition
    try:
        check_scope(task, self.settings)
    except ValueError:
        # In particular, never re-check a cleanup_pending file in a different
        # base directory and then delete the only retained local copy.
        failed = "verification_failed_retained" if can_transition(task["state"], "verification_failed_retained") else "download_failed"
        self.db.transition(task_id, failed, failure_kind="remote_conflict",
                           error="任务接收后 WebDAV 基础目录变化；保留文件并停止自动恢复，请核对配置",
                           wait_reason="需要人工核对原任务目标目录", verification_method=None, verified_at=None)
        return
    local_path = Path(task["local_path"]) if task.get("local_path") else None
    if task.get("state") == "cleanup_pending":
        recorded_remote = str(task.get("remote_path") or "")
        try:
            if (recorded_remote and await self.rclone.exists(recorded_remote)
                    and await self.rclone.remote_size(recorded_remote) != int(task["file_size"])):
                self.db.transition(
                    task_id, "verification_failed_retained",
                    error=safe_failure(RemoteReviewRequired("changed after verification")),
                    failure_kind="remote_conflict", verification_method=None, verified_at=None,
                    wait_reason=None,
                )
                return
            if (
                recorded_remote
                and await self.rclone.exists(recorded_remote)
                and await self.rclone.remote_size(recorded_remote)
                == int(task["file_size"])
            ):
                await self._complete_cloud_receive(
                    task_id, task, local_path, recorded_remote
                )
                return
        except Exception as exc:  # noqa: BLE001 - retry external I/O
            self.db.update(
                task_id,
                error="检查已接收的远端文件失败：" + safe_failure(exc),
                verification_method=None, verified_at=None,
                wait_reason=(
                    f"等待 {self.destination_label} 恢复后继续本地清理"
                ),
                next_retry_at=time.time() + 60,
            )
            return
        if local_path is None or not local_path.is_file():
            if task.get("transfer_mode") == "stream":
                self.db.transition(
                    task_id,
                    "queued",
                    local_path=None,
                    downloaded_bytes=0,
                    uploaded_bytes=0,
                    verification_method=None, verified_at=None,
                    wait_reason=(
                        "流式任务的远端文件无法确认，已自动重新排队"
                    ),
                    next_retry_at=0,
                )
                return
            self.db.transition(
                task_id,
                "verification_failed_retained",
                error="远端正式文件和 VPS 本地副本都无法确认，已停止自动操作",
                failure_kind="remote_conflict", verification_method=None, verified_at=None,
                wait_reason=None,
            )
            return
        self.db.transition(
            task_id,
            "waiting_upload",
            remote_path=None,
            remote_final_path=None,
            error="远端正式文件不存在，保留本地副本并重新上传",
            verification_method=None, verified_at=None,
            wait_reason=None,
            next_retry_at=0,
        )
        task = self.db.get(task_id) or task
    if local_path is None or not local_path.is_file():
        self.db.transition(
            task_id,
            "queued",
            local_path=None,
            downloaded_bytes=0,
            download_retries=0,
            upload_retries=0,
            error="数据库记录的本地完整文件不存在",
            wait_reason="本地文件不存在，已自动重新排队下载",
            next_retry_at=0,
        )
        return
    actual_local_size = local_path.stat().st_size
    if actual_local_size != int(task["file_size"]):
        error = (
            f"本地文件大小错误：{actual_local_size} != {task['file_size']}"
        )
        try:
            local_path.unlink()
        except OSError as exc:
            self.db.transition(
                task_id,
                "verification_failed_retained",
                error=f"{error}；且无法清理：{exc}"[:1000],
            )
            return
        self.db.transition(
            task_id,
            "queued",
            local_path=None,
            downloaded_bytes=0,
            download_retries=0,
            upload_retries=0,
            error=error,
            wait_reason="本地文件不完整，已自动重新排队下载",
            next_retry_at=0,
        )
        await notify_listener_task(
            self, task,
            f"⚠️ 本地文件校验失败，已自动重新下载\n任务：#{task_id}"
        )
        return
    safe_name = safe_file_name(task["file_name"], f"task-{task_id}.bin")
    remote_temp = self.db.staging_name(task_id, safe_name)
    try:
        for attempt in range(
            int(task["upload_retries"]), self.settings.max_retries
        ):
            self.db.update(
                task_id,
                upload_retries=attempt,
                error=None,
                wait_reason=None,
            )
            try:
                if await self._resume_remote(task_id, task, local_path, safe_name):
                    return
                remote_write = await self._begin_remote_write(
                    task_id, task, safe_name, "uploading", remote_temp,
                )
                self._record_progress(task_id, "upload", 0, reset=True)

                # Per-attempt cache only: persist the first observation, every
                # byte change (including restart/reset), and keep speed samples live.
                last_persisted = None

                def progress(count: int, speed: float | None) -> None:
                    nonlocal last_persisted
                    uploaded = min(count, int(task["file_size"]))
                    if uploaded != last_persisted:
                        self.db.update(task_id, uploaded_bytes=uploaded)
                        last_persisted = uploaded
                    self._record_progress(task_id, "upload", count, speed)

                await self.rclone.upload(local_path, remote_write, progress=progress)
                self.db.transition(task_id, "verifying")
                remote_size = await self.rclone.remote_size(remote_write)
                if remote_size != int(task["file_size"]):
                    raise RemoteReviewRequired(
                        f"远端大小错误：{remote_size} != {task['file_size']}"
                    )
                await self._finalize_stream_remote(
                    task_id, task, remote_write, safe_name, local_path
                )
                return
            except asyncio.CancelledError:
                raise
            except MoveUncertainError as exc:
                self.db.transition(
                    task_id, "upload_failed_retained", error=safe_failure(exc), failure_kind="remote_conflict",
                    verification_method=None, verified_at=None,
                    wait_reason="OpenList 改名结果未确认；保留本地和远端文件",
                )
                await notify_listener_task(
                    self, task,
                    f"❌ OpenList 改名结果未确认，任务 #{task_id} 已停止自动重试。"
                    "本地文件已保留，请先核对远端临时文件与目标文件。"
                )
                return
            except Exception as exc:  # noqa: BLE001 - retry external I/O
                if await self._hold_transfer_failure(task, exc):
                    return
                self.recent_upload_errors.append(time.time())
                self.log.warning(
                    "任务 #%s 上传第 %s 次失败：%s", task_id, attempt + 1, safe_failure(exc)
                )
                self.db.update(
                    task_id,
                    upload_retries=attempt + 1,
                    error=safe_failure(exc), failure_kind=failure_kind(exc),
                )
                if attempt + 1 < self.settings.max_retries:
                    await asyncio.sleep(min(120, 3 ** (attempt + 1)))
        self.db.transition(
            task_id,
            "upload_failed_retained",
            error="上传重试次数已经用完；本地完整文件已保留",
        )
        await notify_listener_task(
            self, task,
            f"❌ 上传失败但本地文件已保留\n任务：#{task_id}\n"
            f"修复 {self.destination_label} 后使用 /retry 重试。"
        )
    except asyncio.CancelledError:
        current = self.db.get(task_id)
        if current and current["state"] not in {"cancelled", "cleanup_pending", "completed", "confirmed"}:
            self.db.transition(task_id, "waiting_upload")
        raise
    except Exception as exc:
        self.log.exception("任务 #%s 上传发生未处理异常", task_id)
        self.db.transition(
            task_id,
            "upload_failed_retained",
            error=safe_failure(exc),
        )
