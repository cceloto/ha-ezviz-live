"""Diagnostics for bug reports. Serials are partially masked; keys and tokens are never included."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import EzvizLiveConfigEntry
from .const import CONF_EZVIZ_ENTRY_ID


def _mask(serial: str) -> str:
    return f"***{serial[-4:]}" if serial else serial


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: EzvizLiveConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    ezviz_entry = hass.config_entries.async_get_entry(entry.data[CONF_EZVIZ_ENTRY_ID])
    channels = []
    for ch in data.channels.values():
        hub = next((h for h in data.relay._hubs.values() if h.key == ch.key), None)  # noqa: SLF001
        channels.append({
            "serial": _mask(ch.serial),
            "channel": ch.channel,
            "channels_on_device": ch.channels_on_device,
            "model": ch.model,
            "firmware": ch.firmware,
            "online": ch.online,
            "image_encrypted": ch.image_encrypted,
            "vtm_port": ch.vtm_port,
            "vtm_has_public_key": ch.vtm_key is not None,
            "vtm_key_version": ch.vtm_key_version,
            "stream_biz": ch.stream_biz,
            "hub": asdict(hub.status) if hub else None,
        })
    return {
        "options": dict(entry.options),
        "ezviz_entry_state": ezviz_entry.state.value if ezviz_entry else None,
        "channels": channels,
    }
