"""Persistent outbound-only WSS worker with bounded reconnect and resumption."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from openjarvis.edge_worker.approvals import CodexApprovalBridge
from openjarvis.edge_worker.codex_events import CodexEventRelay
from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.executor import CodexEdgeExecutor
from openjarvis.edge_worker.job_runner import EdgeJobRunner
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.server.jarvis_agent.edge.frames import (
    EdgeFrame,
    make_edge_frame,
    parse_edge_frame,
)

logger = logging.getLogger(__name__)

_SAFE_VALUE_ERRORS = {
    "Core did not acknowledge Edge registration": "registration_not_acknowledged",
    "Core frame targets another device": "device_identity_mismatch",
    "Core frame sequence moved backwards": "core_sequence_moved_backwards",
    "Edge job identity mismatch": "job_identity_mismatch",
}
_SAFE_CLOSE_REASON = re.compile(r"^[a-z0-9_.:-]{1,80}$")


def _safe_connection_failure(exc: Exception) -> str:
    """Return protocol diagnostics without logging URLs, tokens or payloads."""

    if isinstance(exc, ValueError):
        return f"ValueError:{_SAFE_VALUE_ERRORS.get(str(exc), 'protocol_value_error')}"
    received = getattr(exc, "rcvd", None)
    code = getattr(received, "code", None)
    reason = str(getattr(received, "reason", "") or "")
    details = [type(exc).__name__]
    if isinstance(code, int):
        details.append(f"code={code}")
    if reason and _SAFE_CLOSE_REASON.fullmatch(reason):
        details.append(f"reason={reason}")
    return ":".join(details)


class EdgeWorker:
    def __init__(
        self,
        config: EdgeWorkerConfig,
        *,
        spool: EdgeWorkerSpool | None = None,
        executor: CodexEdgeExecutor | None = None,
    ) -> None:
        self.config = config
        self.spool = spool or EdgeWorkerSpool(config.state_path)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: ClientConnection | None = None
        self._send_lock: asyncio.Lock | None = None
        self._recovered = self.spool.recover_interrupted()
        self.approvals = CodexApprovalBridge(
            self._send_required_from_thread,
            timeout_seconds=config.approval_timeout_seconds,
        )
        self.codex_events = CodexEventRelay(self._emit_codex_event)
        self.executor = executor or CodexEdgeExecutor(config, self.approvals)
        set_event_sink = getattr(self.executor, "set_event_sink", None)
        if callable(set_event_sink):
            set_event_sink(
                self.codex_events.submit,
                self.codex_events.flush_from_thread,
            )
        self.jobs = EdgeJobRunner(
            spool=self.spool,
            executor=self.executor,
            emit=self._emit,
        )

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        self.codex_events.start(asyncio.get_running_loop())
        delay = self.config.reconnect_min_seconds
        try:
            while not stop.is_set():
                try:
                    await self._run_connection(stop)
                    delay = self.config.reconnect_min_seconds
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Edge connection unavailable: %s", _safe_connection_failure(exc)
                    )
                    await self._bounded_delay(stop, delay)
                    delay = min(self.config.reconnect_max_seconds, delay * 2)
        finally:
            await self.close()

    async def _run_connection(self, stop: asyncio.Event) -> None:
        headers = {
            "Authorization": f"Bearer {self.config.token}",
            "X-OpenJarvis-Device-ID": self.config.device_id,
        }
        async with connect(
            self.config.edge_url,
            additional_headers=headers,
            max_size=256 * 1024,
            ping_interval=None,
            open_timeout=20.0,
            close_timeout=5.0,
        ) as websocket:
            self._loop = asyncio.get_running_loop()
            self.jobs.set_loop(self._loop)
            self._connection = websocket
            self._send_lock = asyncio.Lock()
            await self._emit(
                "edge.register",
                {
                    "worker_version": "1.0.0",
                    "platform": "windows",
                    "capabilities": sorted(self.executor.capabilities),
                },
            )
            first = parse_edge_frame(await websocket.recv(), from_client=False)
            if first.type != "edge.registered":
                raise ValueError("Core did not acknowledge Edge registration")
            await self._handle_core(first)
            await self._emit(
                "edge.resume", {"active_job_ids": self.spool.active_job_ids()}
            )
            recovered, self._recovered = self._recovered, []
            await self.jobs.publish_recovered(recovered)
            await self._replay_spool()
            heartbeat = asyncio.create_task(self._heartbeat(stop))
            try:
                while not stop.is_set():
                    raw = await asyncio.wait_for(
                        websocket.recv(), timeout=self.config.heartbeat_seconds * 3
                    )
                    await self._handle_core(parse_edge_frame(raw, from_client=False))
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                self._connection = None
                self._send_lock = None

    async def _handle_core(self, frame: EdgeFrame) -> None:
        if frame.device_id != self.config.device_id:
            raise ValueError("Core frame targets another device")
        if not self.spool.record_inbound(str(frame.event_id), frame.sequence):
            return
        payload = frame.validated_payload(from_client=False).model_dump(mode="json")
        acknowledged = payload.get("acknowledged_sequence")
        if isinstance(acknowledged, int):
            self.spool.acknowledge(acknowledged)
        if frame.type == "job.offer":
            await self.jobs.accept_offer(frame, payload)
        elif frame.type == "job.cancel":
            self.jobs.cancel(str(frame.job_id), str(payload["attempt_id"]))
        elif frame.type == "approval.resolved":
            self.approvals.resolve(payload["approval_id"], payload["decision"])
        elif frame.type == "edge.rotate_credentials":
            logger.warning("Credential rotation requires local operator activation")

    async def _heartbeat(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(self.config.heartbeat_seconds)
            await self._emit(
                "edge.heartbeat",
                {"active_job_ids": self.spool.active_job_ids()},
            )

    async def _emit(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str | None = None,
    ) -> EdgeFrame:
        sequence = self.spool.next_outbound_sequence()
        frame = make_edge_frame(
            frame_type=frame_type,
            device_id=self.config.device_id,
            sequence=sequence,
            payload=payload,
            job_id=job_id,
            from_client=True,
        )
        self.spool.queue_outbound(str(frame.event_id), sequence, frame.wire_json())
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            return frame
        async with lock:
            await connection.send(frame.wire_json())
        return frame

    async def _emit_codex_event(self, payload: Mapping[str, Any]) -> EdgeFrame:
        return await self._emit("codex.event", payload)

    async def _replay_spool(self) -> None:
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            return
        async with lock:
            for wire in self.spool.pending_frames():
                await connection.send(wire)

    def _send_required_from_thread(
        self, job_id: str, frame_type: str, payload: Mapping[str, Any]
    ) -> None:
        loop = self._loop
        if loop is None or self._connection is None:
            raise ConnectionError("Edge connection is offline")
        future = asyncio.run_coroutine_threadsafe(
            self._emit(frame_type, payload, job_id=job_id), loop
        )
        future.result(timeout=10.0)
        self.spool.transition(job_id, "WAITING_APPROVAL")

    async def _bounded_delay(self, stop: asyncio.Event, delay: float) -> None:
        duration = min(
            self.config.reconnect_max_seconds,
            delay + random.uniform(0, max(0.1, delay * 0.2)),
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=duration)
        except asyncio.TimeoutError:
            pass

    async def close(self) -> None:
        await self.jobs.close()
        await self.codex_events.close()
        connection = self._connection
        if connection is not None:
            try:
                await self._emit("edge.goodbye", {"reason": "worker_shutdown"})
            except Exception:
                pass
            await connection.close(code=1000, reason="worker_shutdown")


__all__ = ["EdgeWorker"]
