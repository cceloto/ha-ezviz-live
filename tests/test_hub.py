"""LiveHub + RelayServer: one session shared by readers, late joiners start at the last PSM, idle close."""

import asyncio

import aiohttp

from custom_components.ezviz_live.hub import PSM, LiveHub, Opened, RelayServer
from custom_components.ezviz_live.ysproto import Frame, OpenStream


class FakeConn:
    """Feeds a scripted PS stream: a PSM chunk every 5 chunks."""

    def __init__(self):
        self.sent = []
        self.closed = False
        self.n = 0
        self.writer = self

    def send(self, msg_id, body):
        self.sent.append(msg_id)

    async def drain(self):
        pass

    async def recv(self):
        await asyncio.sleep(0.01)
        self.n += 1
        body = (PSM if self.n % 5 == 1 else b"") + f"chunk{self.n};".encode()
        return Frame(0x01, 0x47CB, body)

    def close(self):
        self.closed = True


async def test_shared_session_late_join_and_idle_close():
    opens = []

    async def opener():
        conn = FakeConn()
        opens.append(conn)
        return Opened(OpenStream(conn, b"", "ssn", "fake:1", False))

    hub = LiveHub("S_1", opener, None, grace=0.2)
    relay = RelayServer()
    relay.add(hub)
    await relay.start()
    try:
        async with aiohttp.ClientSession() as http:
            r1 = await http.get(relay.url("S_1"))
            first = await r1.content.read(30)
            assert first.startswith(PSM + b"chunk1;")
            await asyncio.sleep(0.12)
            r2 = await http.get(relay.url("S_1"))
            late = await r2.content.read(20)
            assert late.startswith(PSM)  # cache replays from the last keyframe
            assert hub.viewers == 2 and len(opens) == 1  # one EZVIZ session for both
            r1.close()
            r2.close()
            await asyncio.sleep(0.6)
        assert hub.status.state == "idle"
        assert opens[0].closed and 0x130 in opens[0].sent  # StopStreamReq sent on close
    finally:
        await relay.stop()


async def test_wrong_secret_is_404():
    relay = RelayServer()
    await relay.start()
    try:
        async with aiohttp.ClientSession() as http:
            r = await http.get(f"http://127.0.0.1:{relay.port}/nope/S_1.ps")
            assert r.status == 404
    finally:
        await relay.stop()
