"""EZVIZ Live: cloud live view (VTM/VTDU) for EZVIZ cameras, served to Home Assistant's stream component."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp
from cryptography.hazmat.primitives.asymmetric import ec

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EzvizApiError, EzvizCloud, LiveChannel
from .auth import EzvizIntegrationSession
from .const import CONF_CLIENT_KEY, CONF_EZVIZ_ENTRY_ID
from .ecdh import client_key_from_pem
from .hub import RelayServer

PLATFORMS = [Platform.CAMERA]


@dataclass
class EzvizLiveData:
    ezviz_entry_id: str
    cloud: EzvizCloud
    channels: dict[str, LiveChannel]
    relay: RelayServer
    client_key: ec.EllipticCurvePrivateKey


type EzvizLiveConfigEntry = ConfigEntry[EzvizLiveData]


async def async_setup_entry(hass: HomeAssistant, entry: EzvizLiveConfigEntry) -> bool:
    ezviz_entry_id = entry.data[CONF_EZVIZ_ENTRY_ID]
    if hass.config_entries.async_get_entry(ezviz_entry_id) is None:
        raise ConfigEntryError(translation_domain="ezviz_live", translation_key="ezviz_missing")

    cloud = EzvizCloud(async_get_clientsession(hass), EzvizIntegrationSession(hass, ezviz_entry_id))
    try:
        channels = await cloud.channels()
    except (EzvizApiError, aiohttp.ClientError, TimeoutError) as err:
        # also covers the ezviz entry still loading after a restart
        raise ConfigEntryNotReady(str(err)) from err

    client_key = await hass.async_add_executor_job(client_key_from_pem, entry.data[CONF_CLIENT_KEY])
    relay = RelayServer()
    await relay.start()
    entry.runtime_data = EzvizLiveData(ezviz_entry_id, cloud, channels, relay, client_key)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EzvizLiveConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await asyncio.shield(entry.runtime_data.relay.stop())
    return unloaded
