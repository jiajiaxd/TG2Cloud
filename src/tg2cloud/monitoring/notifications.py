"""Administrator alerts and notifications for transfers from monitored sources."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KEY = "system-incidents.v1"
EVENTS = {
    "disk": ("磁盘空间不足", "新任务可能暂停", "释放受管暂存空间并检查磁盘容量"),
    "authentication": ("WebDAV 认证或权限失败", "新的上传任务无法完成", "检查 WebDAV 用户名、密码和目录权限"),
    "destination": ("WebDAV 持续不可用或限流", "上传与调度可能等待", "检查网关健康状态、网络及限流冷却"),
    "review": ("任务需要人工处理", "部分文件已停止自动重试", "查看自己的失败任务和恢复提示，不要直接删除远端文件"),
    "blocked": ("资源限制导致长时间等待", "部分排队任务无法继续", "检查暂存预算、磁盘余量和系统资源"),
}


async def notify_listener_task(service, task: dict, message: str) -> None:
    if task.get("read_identity", "bot").startswith("listener:"):
        await service._notify(message)


def observations(service, now: float) -> dict[str, bool | None]:
    snapshot = getattr(service, "snapshot", None)
    prefs = service.db.feature_settings()
    threshold = max(service.settings.min_free_disk_bytes, prefs["disk_threshold_bytes"])
    fresh = snapshot and 0 <= now - snapshot.sampled_at <= max(10, service.settings.control_interval * 3)
    free = min([snapshot.disk_free, *(free for _, free in snapshot.filesystems)]) if fresh else None
    destination_fresh = 0 < service.destination_last_checked <= now and now - service.destination_last_checked <= max(
        1000, service.settings.remote_health_interval + 45)
    kind = getattr(service, "destination_failure_kind", "")
    with service.db._lock:
        review = service.db._conn.execute(
            "SELECT 1 FROM tasks WHERE state IN ('download_failed','upload_failed_retained',"
            "'verification_failed_retained') LIMIT 1").fetchone() is not None
        task_auth = service.db._conn.execute(
            "SELECT 1 FROM tasks WHERE state IN ('download_failed','upload_failed_retained',"
            "'verification_failed_retained') AND failure_kind IN ('authentication','permission') LIMIT 1").fetchone() is not None
        blocked = service.db._conn.execute(
            "SELECT 1 FROM tasks WHERE state='queued' AND (wait_reason LIKE '等待本地临时空间%' "
            "OR wait_reason LIKE '等待真实磁盘空间%' OR wait_reason LIKE '等待个人并发额度%' "
            "OR wait_reason LIKE '流式任务等待共享上传窗口%') LIMIT 1").fetchone() is not None
    return {"disk": None if free is None else free <= threshold,
            "authentication": True if task_auth else None if not destination_fresh else kind in {"unauthorized", "authentication", "permission"},
            "destination": None if not destination_fresh or kind in {"unauthorized", "authentication", "permission"}
            else not service.destination_healthy,
            "review": review, "blocked": blocked}


async def tick(service, *, now: float | None = None) -> None:
    now = time.time() if now is None else now
    prefs = service.db.feature_settings()
    if not prefs["notifications"]:
        return
    values = observations(service, now)
    # Reserve the delivery attempt before awaiting Telegram. After a crash an
    # uncertain send is not replayed immediately. No raw exception is persisted.
    for key, active in values.items():
        if active is None:
            continue  # stale/unknown observations cannot produce a recovery
        with service.db._lock:
            connection = service.db._conn
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute("SELECT value FROM service_meta WHERE key=?", (KEY,)).fetchone()
                records = json.loads(row[0]) if row else {}
                if not isinstance(records, dict) or set(records) - set(EVENTS):
                    raise ValueError("故障记录无法确认")
                old = records.get(key, {})
                first = old.get("since", now) if old.get("active") else now
                delay = prefs["sustained_seconds"] if key == "destination" else prefs["blocked_seconds"] if key == "blocked" else 0
                emit = (active and now - first >= delay and now - old.get("attempt", 0) >= prefs["cooldown_seconds"])
                recovery = not active and old.get("active") and old.get("delivered") and prefs["recovery_notifications"]
                records[key] = {"active": active, "since": first, "attempt": now if emit or recovery else old.get("attempt", 0),
                                "delivered": bool(active and old.get("delivered"))}
                connection.execute("INSERT INTO service_meta(key,value) VALUES(?,?) "
                                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, json.dumps(records)))
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        if not emit and not recovery:
            continue
        reason, impact, advice = EVENTS[key]
        label = "恢复通知" if recovery else "异常通知"
        text = (f"{'✅' if recovery else '⚠️'} TG2Cloud · {label}\n\n"
                f"📦 服务：{service.destination_label}\n"
                f"{'✅ 已恢复：' if recovery else '🔍 原因：'}{reason}\n"
                + ("" if recovery else f"📋 影响：{impact}\n💡 建议：{advice}\n")
                + "🕐 检测时间：" + datetime.fromtimestamp(now, timezone.utc if prefs["timezone"] == "UTC"
                                                       else ZoneInfo(prefs["timezone"])).strftime("%H:%M"))
        try:
            await asyncio.wait_for(service.client.send_message(service.settings.allowed_user_id, text), timeout=10)
        except Exception:  # noqa: BLE001 - Telegram is best-effort; never expose raw errors
            service.log.warning("管理员通知发送未确认；已保留冷却，不输出原始错误")
            continue
        if active:
            with service.db._lock:
                row = service.db._conn.execute("SELECT value FROM service_meta WHERE key=?", (KEY,)).fetchone()
                records = json.loads(row[0])
                records[key]["delivered"] = True
                service.db._conn.execute("UPDATE service_meta SET value=? WHERE key=?", (json.dumps(records), KEY))


async def run(service) -> None:
    while not service._stop.is_set():
        try:
            await tick(service)
        except Exception:  # noqa: BLE001 - optional alerts must not interrupt transfers
            service.log.warning("主动通知暂不可用；不影响任务和原有状态查询")
        try:
            await asyncio.wait_for(service._stop.wait(), timeout=15)
        except TimeoutError:
            pass
