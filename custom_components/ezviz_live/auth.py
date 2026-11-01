"""Borrow the logged-in session of the core `ezviz` integration.

The core integration keeps a pyezvizapi `EzvizClient` in `entry.runtime_data.ezviz_client` and refreshes it every
30 s. We read its session for our own HTTP calls and, when the cloud rejects it, ask that same client to refresh.
Sharing the object means the two integrations never rotate the refresh token behind each other's back.

This depends on internals of the core integration and of pyezvizapi; everything is isolated here.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_TYPE
from homeassistant.core import HomeAssistant

from .api import EzvizApiError, Session
from .const import EZVIZ_DOMAIN, EZVIZ_TYPE_CLOUD


def cloud_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Cloud-account entries of the core ezviz integration (it also has per-camera RTSP entries)."""
    return [e for e in hass.config_entries.async_entries(EZVIZ_DOMAIN)
            if e.data.get(CONF_TYPE) == EZVIZ_TYPE_CLOUD]


def camera_verification_code(hass: HomeAssistant, serial: str) -> str | None:
    """The verification code stored by the core integration's per-camera entry, if the user added one.

    It is the key of the device's image encryption.
    """
    for entry in hass.config_entries.async_entries(EZVIZ_DOMAIN):
        if entry.unique_id == serial and entry.data.get(CONF_TYPE) != EZVIZ_TYPE_CLOUD:
            return entry.data.get(CONF_PASSWORD) or None
    return None


class EzvizIntegrationSession:
    """SessionSource backed by the core ezviz integration."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._lock = asyncio.Lock()

    def _client(self) -> Any:
        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            raise EzvizApiError("ezviz_missing", "the linked ezviz entry was removed")
        if entry.state is not ConfigEntryState.LOADED:
            raise EzvizApiError("ezviz_not_loaded", f"the ezviz entry is {entry.state.value}")
        try:
            return entry.runtime_data.ezviz_client
        except AttributeError as err:
            raise EzvizApiError("ezviz_incompatible", "the ezviz integration changed; update ezviz_live") from err

    def current(self) -> Session:
        client = self._client()
        token = getattr(client, "_token", None) or {}
        session_id = token.get("session_id")
        if not session_id:
            raise EzvizApiError("ezviz_no_session", "the ezviz integration has no session")
        feature_code = token.get("feature_code") or client._session.headers.get("featureCode")
        return Session(token["api_url"], feature_code, session_id)

    async def refresh(self) -> None:
        client = self._client()
        async with self._lock:
            await self._hass.async_add_executor_job(client.login)
