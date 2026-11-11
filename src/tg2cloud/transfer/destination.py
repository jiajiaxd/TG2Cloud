from __future__ import annotations

import asyncio
import time

from tg2cloud.domain.classification import media_directories
from tg2cloud.monitoring.observations import record_event
from tg2cloud.storage.policies import policy_for
from tg2cloud.transfer.ports import Destination, DestinationProbe


async def prepare_media_directories(destination: Destination, parent: str) -> None:
    for directory in media_directories(parent):
        await destination.ensure_directory(directory)


async def _probe_destination_once(self) -> None:
    lock = getattr(self, "_destination_probe_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        self._destination_probe_lock = lock
    async with lock:
        openlist = policy_for(self.settings).probe_cooldown
        if openlist and time.monotonic() < getattr(self, "_destination_next_probe_at", 0):
            return  # Merge queued refreshes; never bypass a 401/429 cooldown.
        failure_kind = ""
        try:
            probe_method = getattr(self.rclone, "probe", None)
            if callable(probe_method):
                probe = await asyncio.wait_for(probe_method(), 30)
            else:
                accessible = await asyncio.wait_for(self.rclone.healthy(), 30)
                probe = DestinationProbe(
                    accessible,
                    "unknown",
                    "目录探测通过，不代表可写"
                    if accessible else "目录访问失败，请核对凭据与网络",
                )
            self.destination_healthy = probe.accessible
            self.destination_scope = probe.scope
            self.destination_error = probe.detail
            failure_kind = getattr(probe, "failure_kind", "")
        except TimeoutError:
            self.destination_healthy = False
            self.destination_scope = "unknown"
            self.destination_error = "目录探测超时"
        except Exception:
            self.destination_healthy = False
            self.destination_scope = "unknown"
            self.destination_error = "目录探测异常，请查看本机最近日志"
            self.log.exception("目的端探测异常")
        self.destination_last_checked = time.time()
        self.destination_failure_kind = failure_kind
        if not self.destination_healthy:
            kind = "authentication" if failure_kind == "unauthorized" else failure_kind
            kind = kind if kind in {"authentication", "permission", "rate_limited", "server"} else "network"
            record_event(self, "destination_" + kind)
        if openlist:
            if failure_kind == "rate_limited":
                failures = min(5, getattr(self, "_destination_rate_limit_failures", 0) + 1)
                self._destination_rate_limit_failures = failures
                cooldown = min(900, 60 * 2 ** (failures - 1))
            else:
                self._destination_rate_limit_failures = 0
                if failure_kind in {"unauthorized", "permission"}:
                    cooldown = 300
                elif self.destination_healthy:
                    cooldown = min(10, self.settings.remote_health_interval)
                else:
                    cooldown = self.settings.remote_health_interval
            self._destination_next_probe_at = time.monotonic() + cooldown


async def _destination_loop(self) -> None:
    while not self._stop.is_set():
        await self._probe_destination_once()
        await asyncio.sleep(self.settings.remote_health_interval)
