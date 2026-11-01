"""Protobuf helpers, URL building and the VTM → VTDU handshake against fake servers."""

import asyncio
import struct
from urllib.parse import parse_qs, urlsplit

from custom_components.ezviz_live.ysproto import (
    INFO_RSP,
    InfoResponse,
    build_url,
    info_request,
    open_live,
    pb_decode,
    pb_encode,
)


def test_protobuf_round_trip():
    msg = pb_decode(info_request("ysproto://h:1/live?x=1", "k" * 31))
    assert msg[1] == [b"ysproto://h:1/live?x=1"]
    assert msg[2] == [b"k" * 31]
    assert msg[4] == [0] and msg[8] == [10]


def test_info_response_parse():
    rsp = InfoResponse.parse(pb_encode([(1, 5302), (5, "abc"), (7, "ysproto://10.0.0.1:6001/live?a=1")]))
    assert (rsp.result, rsp.vtmstreamkey, rsp.vtduurl) == (5302, "abc", "ysproto://10.0.0.1:6001/live?a=1")


def test_url_uses_auth_1_and_biz():
    url = build_url("1.2.3.4", 8554, "SERIAL", 1, 2, "tok", "biz=1")
    q = parse_qs(urlsplit(url).query)
    assert q["auth"] == ["1"] and q["ssn"] == ["tok"] and q["biz"] == ["1"] and q["stream"] == ["2"]


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def _frame(msg_id: int, body: bytes, kind: int = 0) -> bytes:
    return struct.pack(">BBHHH", 0x24, kind, len(body), 1, msg_id) + body


async def test_open_live_plain_handshake():
    """Without a VTM public key everything runs in clear: VTM redirects, VTDU answers with the session."""
    seen = {}

    async def vtdu(reader, writer):
        head = await reader.readexactly(8)
        body = await reader.readexactly(struct.unpack(">H", head[2:4])[0])
        seen["vtdu"] = pb_decode(body)
        writer.write(_frame(INFO_RSP, pb_encode([(1, 0), (3, "SU1LSA=="), (4, "ssn-1")])))
        writer.write(_frame(0x47CB, b"\x00\x00\x01\xba media", kind=1))
        await writer.drain()

    vtdu_server, vtdu_port = await _serve(vtdu)

    async def vtm(reader, writer):
        head = await reader.readexactly(8)
        body = await reader.readexactly(struct.unpack(">H", head[2:4])[0])
        seen["vtm"] = pb_decode(body)
        writer.write(_frame(INFO_RSP, pb_encode(
            [(1, 5302), (5, "key31"), (7, f"ysproto://127.0.0.1:{vtdu_port}/live?dev=S")])))
        await writer.drain()
        writer.close()

    vtm_server, vtm_port = await _serve(vtm)
    async with vtm_server, vtdu_server:
        opened = await open_live(vtm_host="127.0.0.1", vtm_port=vtm_port, server_key=None, key_version=0,
                                 client_key=None, serial="S", channel=1, stream=1, token="tok", biz="biz=1")
        frame = await opened.conn.recv()
        opened.conn.close()

    assert opened.streamssn == "ssn-1" and opened.streamhead == b"IMKH" and not opened.encrypted
    assert seen["vtdu"][2] == [b"key31"]  # vtmstreamkey forwarded
    assert seen["vtdu"][1] == [f"ysproto://127.0.0.1:{vtdu_port}/live?dev=S".encode()]
    assert frame.kind == 1 and frame.body.startswith(b"\x00\x00\x01\xba")
