"""Persistent outbound-only WSS worker with bounded reconnect and resumption."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from openjarvis.edge_worker.approvals import CodexApprovalBridge
from openjarvis.edge_worker.codex_events import CodexEventRelay
from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.connection_safety import (
    safe_connection_failure,
    wait_for_reconnect,
)
from openjarvis.edge_worker.executor import CodexEdgeExecutor
from openjarvis.edge_worker.job_runner import EdgeJobRunner
from openjarvis.edge_worker.spool import EdgeWorkerSpool
from openjarvis.edge_worker.spool_errors import EdgeTerminalPayloadError
from openjarvis.server.jarvis_agent.edge.frames import (
    EdgeFrame,
    make_edge_frame,
    parse_edge_frame,
)

logger = logging.getLogger(__name__)


class EdgeWorker:
    def __init__(
        self,
        config: EdgeWorkerConfig,
        *,
        spool: EdgeWorkerSpool | None = None,
        executor: CodexEdgeExecutor | None = None,
    ) -> None:
        self.config = config
        self.spool = spool or EdgeWorkerSpool(
            config.state_path,
            max_frames=config.spool_max_frames,
            max_bytes=config.spool_max_bytes,
        )
        self.spool.discard_legacy_registration_frames()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: ClientConnection | None = None
        self._send_lock: asyncio.Lock | None = None
        self._handshake_complete = False
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
            emit_terminal=self._emit_terminal,
            accept_job=self._accept_job,
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
                        "Edge connection unavailable: %s", safe_connection_failure(exc)
                    )
                    await wait_for_reconnect(
                        stop,
                        delay,
                        max_seconds=self.config.reconnect_max_seconds,
                    )
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
            self._handshake_complete = False
            await self._send_registration()
            first = parse_edge_frame(await websocket.recv(), from_client=False)
            if first.type != "edge.registered":
                raise ValueError("Core did not acknowledge Edge registration")
            await self._handle_core(first)
            await self._replay_and_resume()
            recovered, self._recovered = self._recovered, []
            await self.jobs.publish_recovered(recovered)
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
                self._handshake_complete = False
                self._connection = None
                self._send_lock = None

    async def _send_registration(self) -> EdgeFrame:
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            raise ConnectionError("Edge connection is offline")
        sequence = self.spool.next_outbound_sequence()
        frame = make_edge_frame(
            frame_type="edge.register",
            device_id=self.config.device_id,
            sequence=sequence,
            payload={
                "worker_version": "1.0.0",
                "platform": "windows",
                "capabilities": sorted(self.executor.capabilities),
                "last_core_sequence": self.spool.inbound_sequence(),
            },
            from_client=True,
        )
        async with lock:
            await connection.send(frame.wire_json())
        return frame

    async def _handle_core(self, frame: EdgeFrame) -> None:
        if frame.device_id != self.config.device_id:
            raise ValueError("Core frame targets another device")
        if not self.spool.record_inbound(str(frame.event_id), frame.sequence):
            return
        payload = frame.validated_payload(from_client=False).model_dump(mode="json")
        acknowledged = payload.get("acknowledged_sequence")
        if isinstance(acknowledged, int):
            self.spool.reconcile_outbound_sequence(acknowledged)
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
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            return self._queue_frame(frame_type, payload, job_id=job_id)
        async with lock:
            frame = self._queue_frame(frame_type, payload, job_id=job_id)
            if self._handshake_complete:
                await connection.send(frame.wire_json())
            return frame

    def _queue_frame(
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
        return frame

    async def _accept_job(
        self,
        *,
        job_id: str,
        attempt_id: str,
        tool_id: str,
        payload_hash: str,
    ) -> bool:
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            created, _ = self._queue_job_acceptance(
                job_id=job_id,
                attempt_id=attempt_id,
                tool_id=tool_id,
                payload_hash=payload_hash,
            )
            return created
        async with lock:
            created, frame = self._queue_job_acceptance(
                job_id=job_id,
                attempt_id=attempt_id,
                tool_id=tool_id,
                payload_hash=payload_hash,
            )
            if self._handshake_complete:
                try:
                    await connection.send(frame.wire_json())
                except Exception as exc:
                    self._handshake_complete = False
                    logger.warning(
                        "Edge acceptance retained for replay after send failure: %s",
                        type(exc).__name__,
                    )
            return created

    def _queue_job_acceptance(
        self,
        *,
        job_id: str,
        attempt_id: str,
        tool_id: str,
        payload_hash: str,
    ) -> tuple[bool, EdgeFrame]:
        sequence = self.spool.next_outbound_sequence()
        frame = make_edge_frame(
            frame_type="job.accepted",
            device_id=self.config.device_id,
            sequence=sequence,
            payload={"attempt_id": attempt_id},
            job_id=job_id,
            from_client=True,
        )
        created = self.spool.accept_job_with_frame(
            job_id=job_id,
            attempt_id=attempt_id,
            tool_id=tool_id,
            payload_hash=payload_hash,
            event_id=str(frame.event_id),
            sequence=sequence,
            wire_json=frame.wire_json(),
        )
        return created, frame

    async def _emit_terminal(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str,
        state: str,
    ) -> EdgeFrame:
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            return self._queue_terminal_frame(
                frame_type, payload, job_id=job_id, state=state
            )
        async with lock:
            frame = self._queue_terminal_frame(
                frame_type, payload, job_id=job_id, state=state
            )
            if self._handshake_complete:
                try:
                    await connection.send(frame.wire_json())
                except Exception as exc:
                    self._handshake_complete = False
                    logger.warning(
                        "Edge terminal event retained for replay after send "
                        "failure: %s",
                        type(exc).__name__,
                    )
            return frame

    def _queue_terminal_frame(
        self,
        frame_type: str,
        payload: Mapping[str, Any],
        *,
        job_id: str,
        state: str,
    ) -> EdgeFrame:
        sequence = self.spool.next_outbound_sequence()
        try:
            frame = make_edge_frame(
                frame_type=frame_type,
                device_id=self.config.device_id,
                sequence=sequence,
                payload=payload,
                job_id=job_id,
                from_client=True,
            )
            wire_json = frame.wire_json()
        except (TypeError, ValueError, OverflowError) as exc:
            raise EdgeTerminalPayloadError(
                "Edge terminal payload is not protocol-safe"
            ) from exc
        self.spool.queue_terminal(
            job_id=job_id,
            state=state,
            event_id=str(frame.event_id),
            sequence=sequence,
            wire_json=wire_json,
        )
        return frame

    async def _emit_codex_event(self, payload: Mapping[str, Any]) -> EdgeFrame:
        return await self._emit("codex.event", payload)

    async def _replay_and_resume(self) -> None:
        connection, lock = self._connection, self._send_lock
        if connection is None or lock is None:
            return
        async with lock:
            cursor = 0
            while True:
                page = self.spool.pending_frames(
                    after_sequence=cursor,
                    limit=self.config.replay_batch_size,
                )
                if not page:
                    break
                for pending in page:
                    await connection.send(pending.wire_json)
                    cursor = pending.sequence
            resume = self._queue_frame(
                "edge.resume", {"active_job_ids": self.spool.active_job_ids()}
            )
            self._handshake_complete = True
            try:
                await connection.send(resume.wire_json())
            except Exception:
                self._handshake_complete = False
                raise

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
