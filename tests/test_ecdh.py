"""ECDH round trips: client encrypts, a test server with the private key decrypts and answers."""

import struct

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from custom_components.ezviz_live.ecdh import (
    EcdhError,
    EcdhSession,
    MediaDecryptor,
    aes_ecb,
    chacha,
    data_package,
    mac,
    open_req_package,
    spki,
)


@pytest.fixture
def keys():
    return ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())


def test_request_then_data_packets(keys):
    server_key, client_key = keys
    cli = EcdhSession(spki(server_key.public_key()), 3, client_key)

    req = b"\x0a\x10ysproto://test" * 5
    pkt = cli.encrypt(req)
    assert pkt[:2] == b"$\x01" and pkt[6] == 3 and pkt[7:11] == b"\0\0\0\1"
    assert struct.unpack(">H", pkt[3:5])[0] == len(req)  # ciphertext length, HMAC excluded
    assert len(pkt) == 134 + len(req) + 32
    plain, master, session = open_req_package(pkt, server_key)
    assert (plain, master, session) == (req, cli.master, cli.session)

    rsp = b"\x08\xb6\x29"
    assert cli.decrypt(data_package(7, rsp, session, session)) == rsp
    assert cli.decrypt(data_package(8, rsp, session, master)) == rsp  # HMAC by master also accepted

    nxt = cli.encrypt(b"keepalive")
    assert nxt[:2] == b"$\x02" and struct.unpack(">I", nxt[7:11])[0] == 2


def test_tampered_header_rejected(keys):
    """The HMAC input is the first 8 chars of "%u%u" % (crc(header), crc(ciphertext)), which in practice
    come from the header CRC alone: the protocol authenticates the header, not the payload."""
    server_key, client_key = keys
    cli = EcdhSession(spki(server_key.public_key()), 1, client_key)
    _, _, session = open_req_package(cli.encrypt(b"x"), server_key)
    bad = bytearray(data_package(9, b"payload", session, session))
    bad[10] ^= 1  # seq byte
    with pytest.raises(EcdhError):
        cli.decrypt(bytes(bad))


def test_media_key_packet_then_data(keys):
    """0x0b media: an empty type 1 packet from the sender carries the media session, then type 2 data."""
    sender_key, client_key = keys
    media_session = bytes(range(32))
    master = sender_key.exchange(ec.ECDH(), client_key.public_key())
    header = b"$\x01\x00" + struct.pack(">H", 0) + b"\x01\x01" + struct.pack(">I", 1)
    head = header + aes_ecb(master, media_session) + spki(sender_key.public_key())
    key_pkt = head + mac(master, head, b"")

    dec = MediaDecryptor(client_key)
    assert dec.feed(key_pkt) == b""
    assert dec.session == media_session
    frame = b"\x00\x00\x01\xba" + b"\x11" * 1196
    assert dec.feed(data_package(2, frame, media_session, media_session)) == frame


def test_chacha_nonce_layout():
    key = bytes(32)
    # same nonce (seq) → same keystream; different seq → different keystream
    assert chacha(key, 5, b"\0" * 16) == chacha(key, 5, b"\0" * 16)
    assert chacha(key, 5, b"\0" * 16) != chacha(key, 6, b"\0" * 16)
