# EZVIZ cloud live view protocol

What `ezviz_live` implements, as observed on the wire with the EZVIZ Android app 7.6.1 and an EZVIZ DP2C. It is an
interoperability description, not an official specification. Values marked **observed** were confirmed with real
traffic.

## 1. Flow

```
App ──HTTPS──▶ EZVIZ API  (sessionId header from the account login)
     1. GET  /v3/userdevices/v1/resources/pagelist?filter=VTM,STATUS   → VTM server + public key per channel
     2. POST /api/user/token/get  count=N                               → tokenArray (one token per live view)
App ──TCP──▶ VTM
     3. StreamInfoReq{url ysproto://…/live?…&auth=1&ssn=<token>}
     4. StreamInfoRsp{result=5302, vtmstreamkey, vtduurl=ysproto://ip:port/live?…}     (immediate)
App ──TCP──▶ VTDU
     5. StreamInfoReq{url, vtmstreamkey}
     6. StreamInfoRsp{result=0, streamssn, streamhead}      (~3 s on battery devices: they wake up first)
        → media frames follow on the same connection
     7. StreamKeepAliveReq{streamssn} every 15 s · StopStreamReq on close
```

The resource that owns the VTM entry is the camera resource. On the DP2C there are two `resourceInfos`: type 0
(the device, `localIndex` 0) and type 50 (the camera, `localIndex` 1); `VTM` is keyed by the type 50 `resourceId`
and the channel is its `localIndex`.

## 2. Stream URL

```
ysproto://{vtm_ip}:{port}/live?dev={serial}&chn={channel}&stream={1|2}&cln=3&isp=0&auth=1&ssn={token}
    [&{streamBizUrl}]&tls=0&rnd={random}
```

| Parameter | Value |
|---|---|
| `stream` | 1 = main, 2 = sub |
| `cln` | client type, 3 = Android (the pyezvizapi library uses 9; both work) |
| `auth` | **1** (observed). The VTM accepts any value, but the VTDU answers 6001 for `auth=0` and 5569 for `auth=2` |
| `ssn` | one token from `tokenArray`; each live view consumes one |
| extras | `streamBizUrl` from the pagelist resource, e.g. `biz=1` |

## 3. Framing

Every message on VTM/VTDU connections has an 8-byte big-endian header followed by the body:

| Byte | Field | Values |
|---|---|---|
| 0 | magic | `0x24` (`$`) |
| 1 | type | `0x00` clear protobuf · `0x0a` ECDH protobuf · `0x01` media · `0x0b` ECDH media · `0x0c` RTP with encrypted payload · `0x02` end · `0x03` aux |
| 2–3 | body length | uint16 |
| 4–5 | sequence | uint16 |
| 6–7 | message id | uint16 |

| Id | Message |
|---|---|
| `0x130` / `0x131` | StopStreamReq / Rsp |
| `0x132` / `0x133` | StreamKeepAliveReq / Rsp |
| `0x13b` / `0x13c` | StreamInfoReq / Rsp |

## 4. Messages (package `hik.ys.streamprotocol`)

```proto
message StreamInfoReq {            // 0x13b
  optional string streamurl    = 1;
  optional string vtmstreamkey = 2; // empty to the VTM; the VTM's value to the VTDU
  optional string useragent    = 3; // SDK version, e.g. "v3.10.1.20260710"
  optional uint32 proxytype    = 4; // 0
  optional string proxyinfo    = 5;
  optional string clnversion   = 6; // SDK version
  optional uint32 proxyid      = 7;
  optional uint32 timeout      = 8; // seconds, 10
}

message StreamInfoRsp {            // 0x13c
  optional uint32 result       = 1;  // 0 ok (VTDU); 5302 "go to the VTDU" (VTM)
  optional uint32 datakey      = 2;  // observed: per-session number
  optional string streamhead   = 3;  // observed: base64 of the 40-byte "IMKH" header
  optional string streamssn    = 4;  // used in keepalive/stop
  optional string vtmstreamkey = 5;  // observed: 31 hex chars
  optional string serverinfo   = 6;  // observed: "ys7-vtm vtmk82.6 v2.18.9 build 20261014"
  optional string vtduurl      = 7;  // observed: full ysproto:// URL of the VTDU
  optional string streamkey    = 11; // public key for encrypted media (not sent to us so far)
  optional string vtduipv6     = 13;
  optional uint32 vtdutlsport  = 14;
}

message StreamKeepAliveReq { optional string streamssn = 1; }
```

## 5. Command encryption (ECDH)

Used when the pagelist VTM entry has `publicKey`. Without it, everything runs in clear (types `0x00`/`0x01`); the
servers observed accept both.

**Keys.** Curve secp256r1. Client key pair generated locally and kept (the app rotates it every 90 days); public key
sent as 91-byte SubjectPublicKeyInfo DER. `master = ECDH(client_private, server_public)` (32 bytes, X coordinate);
`session` = 32 random bytes per connection.

**Request packet (type 1)** — every message until the first reply decrypts:

| Offset | Size | Content |
|---|---|---|
| 0 | 1 | `$` |
| 1 | 1 | `0x01` |
| 2 | 1 | extension length (`0x00`) |
| 3 | 2 | ciphertext length, BE (HMAC excluded) |
| 5 | 1 | `0x01` |
| 6 | 1 | server key version (`publicKey.version`) |
| 7 | 4 | seq, BE = 1 |
| 11 | 32 | `AES-256-ECB(master, session)` |
| 43 | 91 | client public key |
| 134 | n | `ChaCha20(key=session, nonce=LE32(seq) ‖ 8×0x00, counter=0)` of the protobuf |
| 134+n | 32 | `HMAC-SHA256(master, ascii("%u%u" % (crc32(bytes[0:134]), crc32(ciphertext)))[:8])` |

**Data packet (type 2)** — afterwards, seq incrementing:

| Offset | Size | Content |
|---|---|---|
| 0 | 3 | `$`, `0x02`, extension length |
| 3 | 2 | ciphertext length, BE |
| 5 | 2 | `0x00 0x00` |
| 7 | 4 | seq, BE |
| 11 | n | `ChaCha20(session, nonce=LE32(seq) ‖ 8×0x00)` |
| 11+n | 32 | `HMAC-SHA256(session, ascii("%u%u" % (crc32(bytes[0:11]), crc32(ciphertext)))[:8])` |

The extension length (byte 2) shifts seq and payload by that many bytes when reading. Replies come as type 2 with the
same session; their HMAC may use either the session or the master key. CRC32 is the standard zlib CRC.

Note that only the first 8 characters of the decimal string are authenticated, which in practice come from the
header CRC alone: the scheme authenticates the header, not the payload.

The whole ECDH packet travels as the body of a type `0x0a` frame with the original message id.

## 6. Media

With ECDH, media arrives as type **`0x0b`** even when the VTDU sends no `streamkey`:

1. The first `0x0b` frame (166 bytes) is a **type 1 packet with an empty payload**. It carries the sender's public
   key and the media session key, wrapped with `AES-ECB(ECDH(client_private, sender_public))`.
2. The following frames are type 2 packets with that media session (usually 1200 bytes of media + 32 of HMAC).
3. The plaintext is an MPEG program stream starting with `00 00 01 BA`. A program stream map (`00 00 01 BC`) comes
   with every keyframe.

Without ECDH the same MPEG-PS arrives in type `0x01` frames.

| Observed on the DP2C | Main (`stream=1`) | Sub (`stream=2`) |
|---|---|---|
| Video | HEVC Main 1920×1080, 15 fps | HEVC Main 1280×720, 15 fps |
| Audio | AAC-LC 16 kHz mono | AAC-LC 16 kHz mono |
| Bitrate | ~1.0 Mbit/s | ~0.45 Mbit/s |
| Keyframe interval | 4 s | — |

**Device image encryption.** When the device's image encryption is on (`STATUS.isEncrypt = 1`), the video NAL units
inside the program stream are additionally encrypted with the device verification code (AES-ECB, key zero-padded to
16 bytes, NAL header kept clear). `ezviz_live` uses the pyezvizapi implementation for that step.

## 7. Error codes seen

| Where | Result | Meaning |
|---|---|---|
| VTM | 5302 | redirect to the VTDU (normal) |
| VTDU | 6001 | `auth=0` |
| VTDU | 5569 | `auth=2` |
