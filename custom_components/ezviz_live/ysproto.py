"""Async ysproto client for the EZVIZ stream servers (VTM and VTDU). See docs/protocol.md."""

from __future__ import annotations

import asyncio
import base64
import random
import socket
import struct
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

from cryptography.hazmat.primitives.asymmetric import ec

from .ecdh import EcdhSession

SDK_VERSION = "v3.10.1.20260710"

# envelope types
T_PLAIN, T_MEDIA, T_ECDH, T_MEDIA_ENC = 0x00, 0x01, 0x0A, 0x0B
# message ids
STOP_REQ, KEEPALIVE_REQ, INFO_REQ, INFO_RSP = 0x130, 0x132, 0x13B, 0x13C
RESULT_GOTO_VTDU = 5302


class StreamError(Exception):
    """A stream server refused the request."""

    def __init__(self, stage: str, result: int | str) -> None:
        super().__init__(f"{stage} refused the stream: {result}")
        self.stage, self.result = stage, result


# --- minimal protobuf -------------------------------------------------------------

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def pb_encode(fields: list[tuple[int, int | str | bytes | None]]) -> bytes:
    out = bytearray()
    for num, val in fields:
        if val is None:
            continue
        if isinstance(val, int):
            out += _varint(num << 3) + _varint(val)
        else:
            raw = val.encode() if isinstance(val, str) else val
            out += _varint(num << 3 | 2) + _varint(len(raw)) + raw
    return bytes(out)


def pb_decode(buf: bytes) -> dict[int, list[int | bytes]]:
    res: dict[int, list] = {}
    i = 0

    def read_varint() -> int:
        nonlocal i
        shift = n = 0
        while True:
            b = buf[i]
            i += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return n

    while i < len(buf):
        key = read_varint()
        num, wire = key >> 3, key & 7
        if wire == 0:
            val = read_varint()
        elif wire == 2:
            ln = read_varint()
            val = buf[i:i + ln]
            i += ln
        elif wire == 5:
            val = struct.unpack("<I", buf[i:i + 4])[0]
            i += 4
        elif wire == 1:
            val = struct.unpack("<Q", buf[i:i + 8])[0]
            i += 8
        else:
            raise ValueError(f"unsupported wire type {wire} in field {num}")
        res.setdefault(num, []).append(val)
    return res


def _first(msg: dict, num: int, default=None):
    v = msg.get(num)
    return v[0] if v else default


def _text(msg: dict, num: int) -> str:
    v = _first(msg, num, b"")
    return v.decode(errors="replace") if isinstance(v, bytes) else str(v)


def build_url(host: str, port: int, serial: str, channel: int, stream: int, token: str,
              biz: str | None = None) -> str:
    """Live view URL as the app builds it. auth=1 is the value the VTDU accepts (0 → 6001, 2 → 5569)."""
    query = urlencode([("dev", serial), ("chn", channel), ("stream", stream),
                       ("cln", 3), ("isp", 0), ("auth", 1), ("ssn", token)])
    if biz:
        query += "&" + biz.lstrip("&")
    query += f"&tls=0&rnd={random.randint(0, 0x7FFFFFFF)}"
    return f"ysproto://{host}:{port}/live?{query}"


def info_request(url: str, vtmstreamkey: str | None = None) -> bytes:
    """StreamInfoReq: url, vtmstreamkey, useragent, proxytype=0, clnversion, timeout=10."""
    return pb_encode([(1, url), (2, vtmstreamkey), (3, SDK_VERSION), (4, 0), (6, SDK_VERSION), (8, 10)])


def keepalive_body(streamssn: str) -> bytes:
    return pb_encode([(1, streamssn)])


@dataclass
class InfoResponse:
    result: int
    streamhead: str = ""
    streamssn: str = ""
    vtmstreamkey: str = ""
    vtduurl: str = ""

    @classmethod
    def parse(cls, body: bytes) -> InfoResponse:
        m = pb_decode(body)
        return cls(result=_first(m, 1, -1), streamhead=_text(m, 3), streamssn=_text(m, 4),
                   vtmstreamkey=_text(m, 5), vtduurl=_text(m, 7))


# --- connection -------------------------------------------------------------------

@dataclass
class Frame:
    kind: int
    msg_id: int
    body: bytes


@dataclass
class Conn:
    host: str
    port: int
    crypto: EcdhSession | None
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    seq: int = 0
    stats: dict[int, int] = field(default_factory=dict)

    async def connect(self, timeout: float = 10) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout)

    def close(self) -> None:
        if self.writer:
            self.writer.close()
            self.writer = None

    def send(self, msg_id: int, body: bytes) -> None:
        kind = T_PLAIN
        if self.crypto:
            body, kind = self.crypto.encrypt(body), T_ECDH
        self.seq = (self.seq + 1) & 0xFFFF
        self.writer.write(struct.pack(">BBHHH", 0x24, kind, len(body), self.seq, msg_id) + body)

    async def recv(self) -> Frame:
        head = await self.reader.readexactly(8)
        magic, kind, length, _seq, msg_id = struct.unpack(">BBHHH", head)
        if magic != 0x24:
            raise StreamError("framing", f"bad magic {head.hex()}")
        body = await self.reader.readexactly(length)
        self.stats[kind] = self.stats.get(kind, 0) + 1
        if kind == T_ECDH and self.crypto:
            body = self.crypto.decrypt(body)
        return Frame(kind, msg_id, body)

    async def ask(self, body: bytes, timeout: float) -> InfoResponse:
        """Send StreamInfoReq and wait for StreamInfoRsp, skipping anything else."""
        self.send(INFO_REQ, body)
        await self.writer.drain()
        async with asyncio.timeout(timeout):
            while True:
                frame = await self.recv()
                if frame.kind in (T_PLAIN, T_ECDH) and frame.msg_id == INFO_RSP:
                    return InfoResponse.parse(frame.body)


@dataclass
class OpenStream:
    conn: Conn
    streamhead: bytes
    streamssn: str
    vtdu: str
    encrypted: bool


async def open_live(*, vtm_host: str, vtm_port: int, server_key: bytes | None, key_version: int,
                    client_key: ec.EllipticCurvePrivateKey, serial: str, channel: int, stream: int,
                    token: str, biz: str | None) -> OpenStream:
    """VTM (5302 → VTDU address) then VTDU (0 → stream session). Returns the VTDU connection with media flowing.

    With the VTM public key the commands go ECDH-encrypted, as the app does, and media arrives as 0x0b.
    Without it everything runs in clear and media arrives as 0x01.
    """
    loop = asyncio.get_running_loop()
    vtm_ip = (await loop.getaddrinfo(vtm_host, vtm_port, type=socket.SOCK_STREAM))[0][4][0]
    url = build_url(vtm_ip, vtm_port, serial, channel, stream, token, biz)

    def crypto() -> EcdhSession | None:
        return EcdhSession(server_key, key_version, client_key) if server_key else None

    vtm = Conn(vtm_ip, vtm_port, crypto())
    try:
        await vtm.connect()
        rsp = await vtm.ask(info_request(url), timeout=15)
    finally:
        vtm.close()
    if rsp.result != RESULT_GOTO_VTDU:
        raise StreamError("VTM", rsp.result)

    # field 7 is the full VTDU URL (ysproto://ip:port/live?...), sent back as the stream URL
    vtdu_url = rsp.vtduurl if "://" in rsp.vtduurl else f"ysproto://{rsp.vtduurl}"
    target = urlsplit(vtdu_url)
    conn = Conn(target.hostname, target.port, crypto())
    try:
        await conn.connect()
        # battery devices take a few seconds to wake up before the VTDU answers
        vrsp = await conn.ask(info_request(vtdu_url if "://" in rsp.vtduurl else url, rsp.vtmstreamkey),
                              timeout=40)
    except BaseException:
        conn.close()
        raise
    if vrsp.result != 0:
        conn.close()
        raise StreamError("VTDU", vrsp.result)
    return OpenStream(conn, base64.b64decode(vrsp.streamhead or ""), vrsp.streamssn,
                      f"{target.hostname}:{target.port}", server_key is not None)
