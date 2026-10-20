"""Config flow for the Beretta hybrid integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL, DEFAULT_PORT, DOMAIN
from .hub import async_test_connection

_LOGGER = logging.getLogger(__name__)


def _user_schema(host: str = "", port: int = DEFAULT_PORT) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
        }
    )


class BerettaHybridConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of the RS485 gateway."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            try:
                await async_test_connection(host, port)
            except (OSError, TimeoutError) as err:
                _LOGGER.debug("Connection test to %s:%s failed: %s", host, port, err)
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Beretta ibrido ({host})",
                    data={CONF_HOST: host, CONF_PORT: port},
                )
            return self.async_show_form(
                step_id="user", data_schema=_user_schema(host, port), errors=errors
            )
        return self.async_show_form(step_id="user", data_schema=_user_schema(), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BerettaHybridOptionsFlow()


class BerettaHybridOptionsFlow(OptionsFlow):
    """Options: rate limit for high-frequency values."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_MIN_INTERVAL: int(user_input[CONF_MIN_INTERVAL])}
            )
        current = self.config_entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MIN_INTERVAL, default=current): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=600,
                            step=1,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
