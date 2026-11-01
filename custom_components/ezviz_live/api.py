"""EZVIZ cloud calls needed for live view: pagelist (VTM servers) and stream tokens.

The session itself is borrowed (see auth.py): this module never logs in.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp

_LOGGER = logging.getLogger(__name__)

APP_VERSION = "7.6.1.0824"
TOKEN_BATCH = 20


class EzvizApiError(Exception):
    def __init__(self, code: Any, msg: str = "") -> None:
        super().__init__(f"{code}: {msg}")
        self.code = code


@dataclass(frozen=True)
class Session:
    api_url: str
    feature_code: str
    session_id: str


class SessionSource(Protocol):
    """Where the logged-in EZVIZ session comes from."""

    def current(self) -> Session: ...

    async def refresh(self) -> None: ...


@dataclass(frozen=True)
class LiveChannel:
    """One live-viewable camera channel (a pagelist resource that has a VTM server)."""

    serial: str
    channel: int
    device_name: str
    channel_name: str
    model: str
    firmware: str
    online: bool
    image_encrypted: bool
    stream_biz: str | None
    vtm_host: str
    vtm_port: int
    vtm_key: bytes | None
    vtm_key_version: int
    channels_on_device: int

    @property
    def key(self) -> str:
        return f"{self.serial}_{self.channel}"


class EzvizCloud:
    def __init__(self, http: aiohttp.ClientSession, source: SessionSource) -> None:
        self._http = http
        self._source = source
        self._stream_tokens: list[str] = []

    def _headers(self, s: Session) -> dict[str, str]:
        return {
            "featureCode": s.feature_code,
            "clientType": "3",
            "clientVersion": APP_VERSION,
            "netType": "WIFI",
            "customno": "1000001",
            "clientNo": "web_site",
            "appId": "ys7",
            "language": "en_GB",
            "lang": "en",
            "User-Agent": "okhttp/3.12.1",
            "sessionId": s.session_id,
        }

    async def _call(self, method: str, path: str, *, data: dict | None = None, **kw) -> dict:
        try:
            return await self._call_once(method, path, data=data, **kw)
        except EzvizApiError as err:
            _LOGGER.debug("%s %s failed (%s), asking the ezviz integration to refresh its session",
                          method, path, err)
        await self._source.refresh()
        self._stream_tokens.clear()
        return await self._call_once(method, path, data=data, **kw)

    async def _call_once(self, method: str, path: str, *, data: dict | None = None, **kw) -> dict:
        s = self._source.current()
        if data is not None:
            data = {**data, "sessionId": s.session_id, "featureCode": s.feature_code, "clientType": "3"}
        async with self._http.request(method, f"https://{s.api_url}{path}", headers=self._headers(s),
                                      data=data, timeout=aiohttp.ClientTimeout(total=20), **kw) as r:
            if r.status == 401:
                raise EzvizApiError(401, "session rejected")
            r.raise_for_status()
            j = await r.json(content_type=None)
        meta = j.get("meta")
        if meta is not None and meta.get("code") != 200:
            raise EzvizApiError(meta.get("code"), meta.get("message", ""))
        if meta is None and str(j.get("resultCode", "0")) != "0":  # older /api/... endpoints
            raise EzvizApiError(j.get("resultCode"), j.get("resultDes", ""))
        return j

    async def channels(self) -> dict[str, LiveChannel]:
        """Every channel that has a VTM server, keyed by "<serial>_<channel>"."""
        page = await self._call("GET", "/v3/userdevices/v1/resources/pagelist",
                                params={"filter": "VTM,STATUS", "limit": 50, "offset": 0, "groupId": -1})
        vtms = page.get("VTM") or {}
        status = page.get("STATUS") or {}
        devices = {d.get("deviceSerial"): d for d in page.get("deviceInfos", [])}
        resources = [r for r in page.get("resourceInfos", []) if r.get("resourceId") in vtms]
        per_device: dict[str, int] = {}
        for r in resources:
            per_device[r.get("deviceSerial")] = per_device.get(r.get("deviceSerial"), 0) + 1

        out: dict[str, LiveChannel] = {}
        for res in resources:
            serial = res.get("deviceSerial")
            dev = devices.get(serial, {})
            vtm = vtms[res["resourceId"]]
            pk = vtm.get("publicKey") or {}
            channel = int(res.get("localIndex") or 1)
            ch = LiveChannel(
                serial=serial,
                channel=channel,
                device_name=dev.get("name") or serial,
                channel_name=res.get("resourceName") or f"{channel}",
                model=dev.get("deviceType") or "",
                firmware=dev.get("version") or "",
                online=dev.get("status") == 1,
                image_encrypted=str((status.get(serial) or {}).get("isEncrypt", 0)) == "1",
                stream_biz=res.get("streamBizUrl"),
                vtm_host=vtm.get("domain") or vtm.get("externalIp"),
                vtm_port=int(vtm.get("port") or 8554),
                vtm_key=base64.b64decode(pk["key"]) if pk.get("key") else None,
                vtm_key_version=int(pk.get("version") or 0),
                channels_on_device=per_device[serial],
            )
            out[ch.key] = ch
        return out

    async def stream_token(self) -> str:
        """One ssn= token per live view; fetched in batches like the app does."""
        if not self._stream_tokens:
            j = await self._call("POST", "/api/user/token/get", data={"count": TOKEN_BATCH})
            self._stream_tokens = list(j["tokenArray"])
        return self._stream_tokens.pop(0)

    def drop_tokens(self) -> None:
        self._stream_tokens.clear()
