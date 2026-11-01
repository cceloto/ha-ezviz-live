"""Shared live session per channel, plus a local HTTP relay that serves it as MPEG-PS.

Home Assistant's stream component (PyAV) reads http://127.0.0.1:<port>/<secret>/<channel>.ps. The EZVIZ session
opens with the first reader and closes `grace` seconds after the last one leaves, so battery devices sleep again.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass

from aiohttp import web
from cryptography.hazmat.primitives.asymmetric import ec

from .ecdh import EcdhError, MediaDecryptor
from .ysproto import KEEPALIVE_REQ, STOP_REQ, T_MEDIA, T_MEDIA_ENC, OpenStream, keepalive_body

_LOGGER = logging.getLogger(__name__)

PSM = b"\x00\x00\x01\xbc"  # program stream map: sent with every keyframe, tells the demuxer the codecs
CACHE_LIMIT = 2 * 1024 * 1024
QUEUE_LIMIT = 4000
RECV_TIMEOUT = 20


@dataclass
class Opened:
    stream: OpenStream
    transform: Callable[[bytes], bytes] | None = None  # e.g. image-encryption decryptor


@dataclass
class HubStatus:
    state: str = "idle"  # idle | opening | streaming
    last_error: str | None = None
    last_open_seconds: float | None = None
    session_started: float | None = None
    session_bytes: int = 0
    vtdu: str | None = None
    encrypted_transport: bool | None = None


class LiveHub:
    def __init__(self, key: str, opener: Callable[[], Awaitable[Opened]],
                 client_key: ec.EllipticCurvePrivateKey, *, grace: float = 5, keepalive: float = 15,
                 max_seconds: float = 900, on_change: Callable[[], None] | None = None) -> None:
        self.key = key
        self._opener = opener
        self._client_key = client_key
        self._grace, self._keepalive, self._max = grace, keepalive, max_seconds
        self._on_change = on_change
        self._subs: set[asyncio.Queue[bytes | None]] = set()
        self._cache: list[bytes] = []
        self._cache_size = 0
        self._task: asyncio.Task | None = None
        self._stopper: asyncio.TimerHandle | None = None
        self.status = HubStatus()

    @property
    def viewers(self) -> int:
        return len(self._subs)

    def _changed(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.status, k, v)
        if self._on_change:
            self._on_change()

    async def subscribe(self) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        for chunk in self._cache:  # late joiners start at the last keyframe
            queue.put_nowait(chunk)
        self._subs.add(queue)
        if self._stopper:
            self._stopper.cancel()
            self._stopper = None
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name=f"ezviz_live {self.key}")
        try:
            while (chunk := await queue.get()) is not None:
                yield chunk
        finally:
            self._subs.discard(queue)
            if not self._subs and self._task and not self._task.done():
                self._stopper = asyncio.get_running_loop().call_later(self._grace, self._stop_if_idle)

    def _stop_if_idle(self) -> None:
        self._stopper = None
        if not self._subs and self._task:
            self._task.cancel()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _publish(self, chunk: bytes) -> None:
        if PSM in chunk or self._cache_size > CACHE_LIMIT:
            self._cache, self._cache_size = [], 0
        self._cache.append(chunk)
        self._cache_size += len(chunk)
        for queue in list(self._subs):
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:  # stalled reader: drop only that one
                _LOGGER.warning("%s: dropping a stalled reader", self.key)
                self._subs.discard(queue)
                queue.get_nowait()
                queue.put_nowait(None)

    async def _run(self) -> None:
        opened: Opened | None = None
        t0 = time.monotonic()
        self._changed(state="opening", last_error=None, session_bytes=0)
        try:
            opened = await self._opener()
            stream, conn = opened.stream, opened.stream.conn
            elapsed = round(time.monotonic() - t0, 1)
            self._changed(state="streaming", last_open_seconds=elapsed, session_started=time.time(),
                          vtdu=stream.vtdu, encrypted_transport=stream.encrypted)
            _LOGGER.info("%s: live view open in %.1f s via %s", self.key, elapsed, stream.vtdu)
            media = MediaDecryptor(self._client_key)
            ka_body = keepalive_body(stream.streamssn)
            last_ka = time.monotonic()
            total = 0
            while time.monotonic() - t0 < self._max:
                if time.monotonic() - last_ka >= self._keepalive:
                    conn.send(KEEPALIVE_REQ, ka_body)
                    await conn.writer.drain()
                    last_ka = time.monotonic()
                frame = await asyncio.wait_for(conn.recv(), RECV_TIMEOUT)
                if frame.kind == T_MEDIA:
                    payload = frame.body
                elif frame.kind == T_MEDIA_ENC:
                    try:
                        payload = media.feed(frame.body)
                    except EcdhError as err:
                        _LOGGER.debug("%s: media packet dropped: %s", self.key, err)
                        continue
                else:
                    continue
                if payload and opened.transform:
                    payload = opened.transform(payload)
                if payload:
                    total += len(payload)
                    self._publish(payload)
                    self.status.session_bytes = total
            _LOGGER.info("%s: session limit of %d s reached", self.key, self._max)
        except asyncio.CancelledError:
            _LOGGER.debug("%s: session closed (no readers)", self.key)
        except Exception as err:  # noqa: BLE001 - any failure becomes status and ends the readers
            _LOGGER.warning("%s: live view failed: %s", self.key, err)
            self.status.last_error = str(err)
        finally:
            if opened:
                try:
                    opened.stream.conn.send(STOP_REQ, keepalive_body(opened.stream.streamssn))
                except Exception:  # noqa: BLE001
                    pass
                opened.stream.conn.close()
            self._cache, self._cache_size = [], 0
            for queue in list(self._subs):
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
            self._changed(state="idle", session_started=None)


class RelayServer:
    """HTTP on 127.0.0.1 only, random port, secret path."""

    def __init__(self) -> None:
        self._hubs: dict[str, LiveHub] = {}
        self._secret = secrets.token_urlsafe(16)
        self._runner: web.AppRunner | None = None
        self.port = 0

    def add(self, hub: LiveHub) -> None:
        self._hubs[hub.key] = hub

    def url(self, key: str) -> str:
        return f"http://127.0.0.1:{self.port}/{self._secret}/{key}.ps"

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/{secret}/{key}.ps", self._handle)
        self._runner = web.AppRunner(app, access_log=None, handle_signals=False)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]

    async def stop(self) -> None:
        for hub in self._hubs.values():
            await hub.stop()
        if self._runner:
            await self._runner.cleanup()

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        if not secrets.compare_digest(request.match_info["secret"], self._secret):
            raise web.HTTPNotFound
        hub = self._hubs.get(request.match_info["key"])
        if hub is None:
            raise web.HTTPNotFound
        resp = web.StreamResponse(headers={"Content-Type": "video/MP2P", "Cache-Control": "no-store"})
        await resp.prepare(request)
        _LOGGER.debug("%s: reader connected", hub.key)
        try:
            async with aclosing(hub.subscribe()) as chunks:
                async for chunk in chunks:
                    await resp.write(chunk)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            _LOGGER.debug("%s: reader left", hub.key)
        return resp
