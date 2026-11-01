"""Device image encryption ("verification code"): decrypt the video NAL units inside the MPEG-PS.

Experimental: relies on pyezvizapi's decryptor (installed with the core ezviz integration) and has not been
verified against a real encrypted stream by this project yet.
"""

from __future__ import annotations

BATCH = 64 * 1024  # parse the buffer in batches; per-chunk parsing would be quadratic
MAX_BUFFER = 4 * 1024 * 1024


class PsVideoDecryptor:
    def __init__(self, key: str) -> None:
        from pyezvizapi.stream import (  # noqa: PLC0415 - only needed when encryption is on
            decrypt_hikvision_ps_video,
            detect_hikvision_ps_video_nalu_header_size,
            mpeg_ps_decryptable_prefix_length,
        )

        self._decrypt = decrypt_hikvision_ps_video
        self._detect = detect_hikvision_ps_video_nalu_header_size
        self._prefix = mpeg_ps_decryptable_prefix_length
        self._key = key
        self._buf = bytearray()
        self._nalu_header: int | None = None

    def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk
        if len(self._buf) < BATCH:
            return b""
        n = self._prefix(self._buf)
        if not n:
            if len(self._buf) > MAX_BUFFER:  # never found a boundary: give up on this run
                self._buf.clear()
            return b""
        ready = bytes(self._buf[:n])
        del self._buf[:n]
        if self._nalu_header is None:
            self._nalu_header = self._detect(ready, self._key) or 2  # 2 = HEVC, 1 = H.264
        return self._decrypt(ready, self._key, nalu_header_size=self._nalu_header)
