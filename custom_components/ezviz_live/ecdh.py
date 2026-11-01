"""ECDH command/media encryption used on VTM and VTDU connections. See docs/protocol.md.

Request packet (type 1, used until the first decrypted reply):
  $ 01 ext=00 len16 01 keyver seq32=1 | AES-ECB(master, session) | client pubkey (91) | ChaCha20 | HMAC(master)
Data packet (type 2):
  $ 02 ext=00 len16 00 00 seq32       | ChaCha20 | HMAC(session)

len16 is the ciphertext length (HMAC excluded). ChaCha20 nonce = LE32(seq) || 8 zero bytes, counter 0.
The HMAC covers ascii("%u%u" % (crc32(header), crc32(ciphertext)))[:8].
"""

from __future__ import annotations

import hmac
import os
import struct
import zlib
from hashlib import sha256

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class EcdhError(Exception):
    """Malformed packet or failed authentication."""


def chacha(key: bytes, seq: int, data: bytes) -> bytes:
    # cryptography takes a 16-byte nonce: LE32 block counter (0) || the 12-byte mbedtls nonce
    nonce = struct.pack("<II", 0, seq) + bytes(8)
    return Cipher(algorithms.ChaCha20(key, nonce), None).encryptor().update(data)


def aes_ecb(key: bytes, data: bytes, decrypt: bool = False) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    op = cipher.decryptor() if decrypt else cipher.encryptor()
    return op.update(data) + op.finalize()


def mac(key: bytes, header: bytes, ciphertext: bytes) -> bytes:
    msg = ("%u%u" % (zlib.crc32(header), zlib.crc32(ciphertext))).encode()[:8].ljust(8, b"\0")
    return hmac.new(key, msg, sha256).digest()


def spki(pub: ec.EllipticCurvePublicKey) -> bytes:
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if len(der) != 91:
        raise EcdhError(f"unexpected public key size {len(der)}")
    return der


def new_client_key_pem() -> str:
    """Client key pair, generated once per config entry (the app rotates it every 90 days)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def client_key_from_pem(pem: str) -> ec.EllipticCurvePrivateKey:
    return serialization.load_pem_private_key(pem.encode(), None)


def data_package(seq: int, plain: bytes, key: bytes, hmac_key: bytes) -> bytes:
    header = b"$\x02\x00" + struct.pack(">H", len(plain)) + b"\x00\x00" + struct.pack(">I", seq)
    ct = chacha(key, seq, plain)
    return header + ct + mac(hmac_key, header, ct)


def _head(pkt: bytes) -> tuple[int, int, int, int]:
    """Return (type, ext, length, seq). Byte 2 is an extension length that shifts seq and payload."""
    if len(pkt) < 11 or pkt[0] != 0x24:
        raise EcdhError(f"invalid ECDH packet: {pkt[:16].hex()}")
    ext = pkt[2]
    return pkt[1], ext, struct.unpack(">H", pkt[3:5])[0], struct.unpack(">I", pkt[7 + ext:11 + ext])[0]


def open_data_package(pkt: bytes, session: bytes, master: bytes | None = None) -> bytes:
    kind, ext, n, seq = _head(pkt)
    if kind != 2:
        raise EcdhError(f"expected a type 2 packet, got {kind}")
    hdr_len = 11 + ext
    header, ct, tag = pkt[:hdr_len], pkt[hdr_len:hdr_len + n], pkt[hdr_len + n:hdr_len + n + 32]
    # a peer-side flag decides whether the HMAC uses the session or the master key; accept both
    if not any(k and hmac.compare_digest(mac(k, header, ct), tag) for k in (session, master)):
        raise EcdhError("HMAC mismatch")
    return chacha(session, seq, ct)


def open_req_package(pkt: bytes, own_key: ec.EllipticCurvePrivateKey) -> tuple[bytes, bytes, bytes]:
    """Open a type 1 packet with the receiver's private key. Return (plain, master, session)."""
    kind, ext, n, seq = _head(pkt)
    if kind != 1:
        raise EcdhError(f"expected a type 1 packet, got {kind}")
    base = 11 + ext
    peer_pub = serialization.load_der_public_key(pkt[base + 32:base + 123])
    master = own_key.exchange(ec.ECDH(), peer_pub)
    session = aes_ecb(master, pkt[base:base + 32], decrypt=True)
    head_len = base + 123
    ct = pkt[head_len:head_len + n]
    if not hmac.compare_digest(mac(master, pkt[:head_len], ct), pkt[head_len + n:head_len + n + 32]):
        raise EcdhError("HMAC mismatch on type 1 packet")
    return chacha(session, seq, ct), master, session


class EcdhSession:
    """Command channel state, one per TCP connection (VTM or VTDU)."""

    def __init__(self, server_pub_der: bytes, key_version: int, client_key: ec.EllipticCurvePrivateKey,
                 session: bytes | None = None) -> None:
        server_pub = serialization.load_der_public_key(server_pub_der)
        self.client_key = client_key
        self.client_pub = spki(client_key.public_key())
        self.key_version = key_version
        self.master = client_key.exchange(ec.ECDH(), server_pub)
        self.session = session or os.urandom(32)
        self.established = False
        self.seq = 1

    def encrypt(self, plain: bytes) -> bytes:
        if not self.established:
            return self._req_package(plain)
        self.seq += 1
        return data_package(self.seq, plain, self.session, self.session)

    def _req_package(self, plain: bytes) -> bytes:
        header = (b"$\x01\x00" + struct.pack(">H", len(plain)) + bytes([1, self.key_version & 0xFF])
                  + struct.pack(">I", 1))
        head = header + aes_ecb(self.master, self.session) + self.client_pub
        ct = chacha(self.session, 1, plain)
        return head + ct + mac(self.master, head, ct)

    def decrypt(self, pkt: bytes) -> bytes:
        if pkt[1:2] == b"\x01":
            plain, _, _ = open_req_package(pkt, self.client_key)
        else:
            plain = open_data_package(pkt, self.session, self.master)
        self.established = True
        return plain


class MediaDecryptor:
    """Media channel 0x0b: the sender opens with an empty type 1 packet carrying its own session key,
    wrapped with ECDH(client key, sender key); type 2 packets with that session follow."""

    def __init__(self, client_key: ec.EllipticCurvePrivateKey) -> None:
        self.client_key = client_key
        self.session: bytes | None = None
        self.master: bytes | None = None

    def feed(self, pkt: bytes) -> bytes:
        if pkt[1:2] == b"\x01":
            plain, self.master, self.session = open_req_package(pkt, self.client_key)
            return plain
        if self.session is None:
            raise EcdhError("media data packet before the key packet")
        return open_data_package(pkt, self.session, self.master)
