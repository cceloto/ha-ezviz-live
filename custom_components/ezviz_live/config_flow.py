"""Config flow: link to an existing core ezviz cloud account. No credentials are asked or stored."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .auth import cloud_entries
from .const import (CONF_ALLOW_WEBRTC, CONF_CLIENT_KEY, CONF_EZVIZ_ENTRY_ID, CONF_STREAM_TYPE,
                    DEFAULT_ALLOW_WEBRTC, DEFAULT_STREAM_TYPE, DOMAIN)
from .ecdh import new_client_key_pem


class EzvizLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        accounts = {e.entry_id: e.title for e in cloud_entries(self.hass)}
        if not accounts:
            return self.async_abort(reason="ezviz_missing")
        configured = {e.unique_id for e in self._async_current_entries()}
        available = {k: v for k, v in accounts.items() if k not in configured}
        if not available:
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            entry_id = user_input[CONF_EZVIZ_ENTRY_ID]
            await self.async_set_unique_id(entry_id)
            self._abort_if_unique_id_configured()
            key_pem = await self.hass.async_add_executor_job(new_client_key_pem)
            return self.async_create_entry(title=available[entry_id], data={
                CONF_EZVIZ_ENTRY_ID: entry_id,
                CONF_CLIENT_KEY: key_pem,
            })

        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_EZVIZ_ENTRY_ID, default=next(iter(available))): vol.In(available),
        }))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EzvizLiveOptionsFlow:
        return EzvizLiveOptionsFlow()


class EzvizLiveOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**user_input, CONF_STREAM_TYPE: int(user_input[CONF_STREAM_TYPE])})
        opts = self.config_entry.options
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_STREAM_TYPE, default=str(opts.get(CONF_STREAM_TYPE, DEFAULT_STREAM_TYPE))):
                SelectSelector(SelectSelectorConfig(options=["1", "2"], translation_key=CONF_STREAM_TYPE,
                                                    mode=SelectSelectorMode.LIST)),
            vol.Required(CONF_ALLOW_WEBRTC, default=opts.get(CONF_ALLOW_WEBRTC, DEFAULT_ALLOW_WEBRTC)): bool,
        }))
