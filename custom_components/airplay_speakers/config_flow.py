"""Config flow for AirPlay Speakers integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pyatv
from pyatv.const import Protocol
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AIRPLAY_CREDENTIALS,
    CONF_ATV_HOST,
    CONF_ATV_NAME,
    CONF_COMPANION_CREDENTIALS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AirplaySpeakersConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirPlay Speakers."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str = ""
        self._atv_name: str = ""
        self._atv_config = None
        self._companion_creds: str | None = None
        self._pairing = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: user enters Apple TV IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_ATV_HOST]

            loop = asyncio.get_running_loop()
            try:
                configs = await pyatv.scan(loop, hosts=[self._host], timeout=5)
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if not configs:
                    errors["base"] = "cannot_connect"
                else:
                    self._atv_config = configs[0]
                    self._atv_name = self._atv_config.name

                    # Check if already configured for this Apple TV
                    await self.async_set_unique_id(f"atv_{self._host}")
                    self._abort_if_unique_id_configured()

                    return await self.async_step_pair_companion()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ATV_HOST): str,
            }),
            errors=errors,
        )

    async def async_step_pair_companion(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pair with Apple TV via Companion protocol."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input["pin"]
            try:
                self._pairing.pin(int(pin))
                await self._pairing.finish()
                self._companion_creds = self._pairing.service.credentials
                await self._pairing.close()
                self._pairing = None
            except Exception:
                _LOGGER.exception("Companion pairing failed")
                errors["base"] = "pairing_failed"
                if self._pairing:
                    await self._pairing.close()
                    self._pairing = None
            else:
                return await self.async_step_pair_airplay()

        # Start Companion pairing
        if self._pairing is None:
            loop = asyncio.get_running_loop()
            try:
                self._pairing = await pyatv.pair(
                    self._atv_config, Protocol.Companion, loop
                )
                await self._pairing.begin()
            except Exception:
                _LOGGER.exception("Failed to start Companion pairing")
                return self.async_abort(reason="pairing_failed")

        return self.async_show_form(
            step_id="pair_companion",
            data_schema=vol.Schema({
                vol.Required("pin"): str,
            }),
            description_placeholders={"name": self._atv_name},
            errors=errors,
        )

    async def async_step_pair_airplay(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pair with Apple TV via AirPlay protocol."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input["pin"]
            try:
                self._pairing.pin(int(pin))
                await self._pairing.finish()
                airplay_creds = self._pairing.service.credentials
                await self._pairing.close()
                self._pairing = None
            except Exception:
                _LOGGER.exception("AirPlay pairing failed")
                errors["base"] = "pairing_failed"
                if self._pairing:
                    await self._pairing.close()
                    self._pairing = None
            else:
                return self.async_create_entry(
                    title=f"AirPlay Speakers ({self._atv_name})",
                    data={
                        CONF_ATV_HOST: self._host,
                        CONF_ATV_NAME: self._atv_name,
                        CONF_COMPANION_CREDENTIALS: self._companion_creds,
                        CONF_AIRPLAY_CREDENTIALS: airplay_creds,
                    },
                )

        # Start AirPlay pairing
        if self._pairing is None:
            loop = asyncio.get_running_loop()
            try:
                self._pairing = await pyatv.pair(
                    self._atv_config, Protocol.AirPlay, loop
                )
                await self._pairing.begin()
            except Exception:
                _LOGGER.exception("Failed to start AirPlay pairing")
                return self.async_abort(reason="pairing_failed")

        return self.async_show_form(
            step_id="pair_airplay",
            data_schema=vol.Schema({
                vol.Required("pin"): str,
            }),
            description_placeholders={"name": self._atv_name},
            errors=errors,
        )
