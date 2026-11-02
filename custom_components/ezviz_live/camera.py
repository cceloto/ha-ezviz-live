"""Live camera entities: stream_source points at the local relay and Home Assistant's stream builds the HLS."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.image.const import DATA_COMPONENT as IMAGE_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EzvizLiveConfigEntry, EzvizLiveData
from .api import LiveChannel
from .auth import camera_verification_code
from .const import (CONF_ALLOW_WEBRTC, CONF_AREA_SYNCED, CONF_STREAM_TYPE, DEFAULT_ALLOW_WEBRTC, DEFAULT_STREAM_TYPE, DOMAIN,
                    EZVIZ_DOMAIN)
from .hub import LiveHub, Opened
from .image_crypto import PsVideoDecryptor
from .ysproto import StreamError, open_live

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_FIRST = 8  # seconds after opening: past the first keyframe
SNAPSHOT_EVERY = 20


class MissingVerificationCode(Exception):
    """Image encryption is on and the core ezviz integration has no verification code for the device."""


async def async_setup_entry(hass: HomeAssistant, entry: EzvizLiveConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    data = entry.runtime_data
    stream_type = int(entry.options.get(CONF_STREAM_TYPE, DEFAULT_STREAM_TYPE))
    allow_webrtc = entry.options.get(CONF_ALLOW_WEBRTC, DEFAULT_ALLOW_WEBRTC)
    async_add_entities(EzvizLiveCamera(data, ch, stream_type, allow_webrtc) for ch in data.channels.values())


def _copy_area_once(hass: HomeAssistant, entry: EzvizLiveConfigEntry, serial: str) -> None:
    """Put a new linked device in the area of the core ezviz device, once; later changes are the user's."""
    done = entry.data.get(CONF_AREA_SYNCED, [])
    if serial in done:
        return
    reg = dr.async_get(hass)
    ours = reg.async_get_device_by_identifier((EZVIZ_DOMAIN, serial), entry.entry_id)
    if ours is None:
        return
    core = reg.async_get_device_by_identifier((EZVIZ_DOMAIN, serial), entry.runtime_data.ezviz_entry_id)
    if core and core.area_id and not ours.area_id:
        reg.async_update_device(ours.id, area_id=core.area_id)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_AREA_SYNCED: sorted({*done, serial})})


class EzvizLiveCamera(Camera):
    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, data: EzvizLiveData, ch: LiveChannel, stream_type: int, allow_webrtc: bool) -> None:
        super().__init__()
        self._data = data
        self._ch = ch
        self._stream_type = stream_type
        self._allow_webrtc = allow_webrtc
        self._last_image: bytes | None = None
        self._snapper: asyncio.Task | None = None
        self._attr_unique_id = ch.key
        if ch.channels_on_device > 1:
            self._attr_translation_key = "live_channel"
            self._attr_translation_placeholders = {"channel": ch.channel_name}
        else:
            self._attr_translation_key = "live"
        # Since HA 2026.8 every config entry owns its own device. Sharing the core ezviz identifier (and the MAC)
        # makes ours a *linked device* of the one the core integration creates.
        self._attr_device_info = DeviceInfo(
            identifiers={(EZVIZ_DOMAIN, ch.serial)},
            connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(ch.mac))} if ch.mac else set(),
            name=ch.device_name,
            manufacturer="EZVIZ",
            model=ch.model,
            model_id=ch.model_id,
            sw_version=ch.firmware or None,
        )
        self._hub = LiveHub(ch.key, self._open, data.client_key, on_change=self._hub_changed)
        data.relay.add(self._hub)

    # --- opening -------------------------------------------------------------------

    async def _open(self) -> Opened:
        """Fresh VTM data from the pagelist and a fresh token; one retry with new tokens."""
        cloud = self._data.cloud
        for attempt in (1, 2):
            ch = (await cloud.channels())[self._ch.key]
            transform = self._image_decryptor(ch)
            try:
                stream = await open_live(
                    vtm_host=ch.vtm_host, vtm_port=ch.vtm_port, server_key=ch.vtm_key,
                    key_version=ch.vtm_key_version, client_key=self._data.client_key, serial=ch.serial,
                    channel=ch.channel, stream=self._stream_type, token=await cloud.stream_token(),
                    biz=ch.stream_biz)
                return Opened(stream, transform)
            except StreamError as err:
                if attempt == 2:
                    raise
                _LOGGER.debug("%s: %s; retrying with fresh tokens", self._ch.key, err)
                cloud.drop_tokens()
        raise AssertionError("unreachable")

    def _image_decryptor(self, ch: LiveChannel):
        issue_id = f"verification_code_{ch.serial}"
        if not ch.image_encrypted:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return None
        code = camera_verification_code(self.hass, ch.serial)
        if not code:
            ir.async_create_issue(self.hass, DOMAIN, issue_id, is_fixable=False,
                                  severity=ir.IssueSeverity.WARNING, translation_key="verification_code",
                                  translation_placeholders={"name": ch.device_name, "serial": ch.serial})
            raise MissingVerificationCode(f"{ch.serial} has image encryption on and no verification code")
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        return PsVideoDecryptor(code).feed

    # --- state ---------------------------------------------------------------------

    def _hub_changed(self) -> None:
        if not self.hass:
            return
        if self._hub.status.state == "streaming" and (self._snapper is None or self._snapper.done()):
            self._snapper = self.hass.async_create_background_task(
                self._snap_while_streaming(), f"ezviz_live snapshot {self._ch.key}")
        self.async_write_ha_state()

    def _stream_live(self) -> bool:
        # HA's stream must be reading from the relay; otherwise async_get_image would restart it and wake the device
        return bool(self.stream) and self._hub.status.state == "streaming" and self._hub.viewers > 0

    async def _snap_while_streaming(self) -> None:
        """Keep a recent frame so the thumbnail stays useful after the device goes back to sleep."""
        await asyncio.sleep(SNAPSHOT_FIRST)
        while self._stream_live():
            if image := await self.stream.async_get_image():
                self._last_image = image
            await asyncio.sleep(SNAPSHOT_EVERY)

    async def _motion_image(self) -> bytes | None:
        """Before the first session: the last motion picture the core ezviz integration exposes for the device."""
        device = dr.async_get(self.hass).async_get_device_by_identifier(
            (EZVIZ_DOMAIN, self._ch.serial), self._data.ezviz_entry_id)
        component = self.hass.data.get(IMAGE_COMPONENT)
        if not device or not component:
            return None
        for entry in er.async_entries_for_device(er.async_get(self.hass), device.id):
            if entry.domain == "image" and entry.platform == EZVIZ_DOMAIN and (
                    ent := component.get_entity(entry.entity_id)):
                return await ent.async_image()
        return None

    # --- Camera API ----------------------------------------------------------------

    async def stream_source(self) -> str | None:
        return self._data.relay.url(self._ch.key)

    async def _async_get_supported_webrtc_provider(self, fn):
        # the streams are often HEVC: HLS only unless the user opts in, so go2rtc does not take the camera
        if not self._allow_webrtc:
            return None
        return await super()._async_get_supported_webrtc_provider(fn)

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        # never wake the device for a thumbnail: use the stream only while a session is already open
        if self._stream_live():
            if image := await self.stream.async_get_image(width, height):
                self._last_image = image
        return self._last_image or await self._motion_image()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # the device is registered by now
        _copy_area_once(self.hass, self.platform.config_entry, self._ch.serial)

    async def async_will_remove_from_hass(self) -> None:
        await self._hub.stop()
        await super().async_will_remove_from_hass()

    @property
    def is_streaming(self) -> bool:
        return self._hub.status.state == "streaming"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._hub.status
        return {
            "live_state": s.state,
            "viewers": self._hub.viewers,
            "last_open_seconds": s.last_open_seconds,
            "last_error": s.last_error,
            "stream_type": "main" if self._stream_type == 1 else "sub",
        }
