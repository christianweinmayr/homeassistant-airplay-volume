"""Config flow for AirPlay Speakers integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from .binary_manager import (
    CLIAirplayAuthenticationError,
    CLIAirplayConnectionError,
    CLIAirplayManager,
)
from .const import (
    CONF_CREDENTIALS,
    CONF_DEVICE_ID,
    CONF_MODEL,
    DOMAIN,
    TXT_DEVICE_ID,
    TXT_FEATURES,
    TXT_MODEL,
)

_LOGGER = logging.getLogger(__name__)

# Apple TV integration domain for coexistence check
APPLE_TV_DOMAIN = "apple_tv"

# AirPlay 2 feature bit (bit 38) — indicates HAP pairing support
_AIRPLAY2_FEATURE_BIT = 1 << 38


def _is_airplay2(features_str: str | None) -> bool:
    """Determine if a device supports AirPlay 2 based on its feature bitmask."""
    if not features_str:
        return False
    try:
        # Features field can be a hex string like "0x..." or a plain integer
        features = int(features_str, 0)
    except (ValueError, TypeError):
        return False
    return bool(features & _AIRPLAY2_FEATURE_BIT)


def _normalize_device_id(device_id: str) -> str:
    """Normalize a device ID (MAC address) to a consistent format.

    Strips whitespace, lowercases, and ensures colon separators.
    """
    return device_id.strip().upper()


class AirplaySpeakersConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirPlay Speakers."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: dict[str, Any] = {}

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle zeroconf discovery of an AirPlay speaker."""
        properties = discovery_info.properties

        # Extract device identifiers from mDNS TXT records
        device_id_raw = properties.get(TXT_DEVICE_ID, "")
        if not device_id_raw:
            return self.async_abort(reason="no_devices_found")

        device_id = _normalize_device_id(device_id_raw)
        name = discovery_info.name.split("._")[0]  # Strip service type suffix
        model = properties.get(TXT_MODEL, "AirPlay Speaker")
        features = properties.get(TXT_FEATURES)
        host = str(discovery_info.host)
        port = discovery_info.port or 7000

        _LOGGER.debug(
            "Discovered AirPlay device: name=%s, deviceid=%s, model=%s, host=%s:%s",
            name,
            device_id,
            model,
            host,
            port,
        )

        # Set unique ID and abort if already configured (update host/port on IP change)
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host, CONF_PORT: port}
        )

        # Check if device is already managed by the Apple TV integration
        for entry in self.hass.config_entries.async_entries(APPLE_TV_DOMAIN):
            if entry.unique_id and entry.unique_id.upper() == device_id:
                _LOGGER.debug(
                    "Device %s already managed by Apple TV integration, skipping",
                    device_id,
                )
                return self.async_abort(reason="already_configured")

        # Store discovery data for subsequent steps
        self._discovery_info = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_DEVICE_ID: device_id,
            CONF_NAME: name,
            CONF_MODEL: model,
            "is_airplay2": _is_airplay2(features),
        }

        # Set flow title context for the UI
        self.context["title_placeholders"] = {"name": name}

        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders={"name": name, "model": model},
        )

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user confirmation of discovered device."""
        if user_input is None:
            return self.async_show_form(
                step_id="zeroconf_confirm",
                description_placeholders={
                    "name": self._discovery_info[CONF_NAME],
                    "model": self._discovery_info[CONF_MODEL],
                },
            )

        # User confirmed — check if pairing is needed
        if self._discovery_info.get("is_airplay2"):
            return await self.async_step_pair()

        # AirPlay 1 device — no pairing needed, create entry directly
        return self.async_create_entry(
            title=self._discovery_info[CONF_NAME],
            data={
                CONF_HOST: self._discovery_info[CONF_HOST],
                CONF_PORT: self._discovery_info[CONF_PORT],
                CONF_DEVICE_ID: self._discovery_info[CONF_DEVICE_ID],
                CONF_NAME: self._discovery_info[CONF_NAME],
                CONF_MODEL: self._discovery_info[CONF_MODEL],
                CONF_CREDENTIALS: None,
            },
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle PIN-based HAP pairing for AirPlay 2 devices."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input.get("pin", "").strip()
            if not pin:
                errors["pin"] = "invalid_pin"
            else:
                # Attempt pairing via cliairplay
                manager = CLIAirplayManager(
                    hass=self.hass,
                    device_id=self._discovery_info[CONF_DEVICE_ID],
                    host=self._discovery_info[CONF_HOST],
                    port=self._discovery_info[CONF_PORT],
                )
                try:
                    result = await manager.pair(pin)
                    credentials = result.get("credentials")
                except CLIAirplayAuthenticationError:
                    _LOGGER.debug(
                        "Pairing failed for %s: invalid PIN or auth error",
                        self._discovery_info[CONF_DEVICE_ID],
                    )
                    errors["pin"] = "invalid_pin"
                except CLIAirplayConnectionError:
                    _LOGGER.debug(
                        "Connection error during pairing for %s",
                        self._discovery_info[CONF_DEVICE_ID],
                    )
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception(
                        "Unexpected error during pairing for %s",
                        self._discovery_info[CONF_DEVICE_ID],
                    )
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=self._discovery_info[CONF_NAME],
                        data={
                            CONF_HOST: self._discovery_info[CONF_HOST],
                            CONF_PORT: self._discovery_info[CONF_PORT],
                            CONF_DEVICE_ID: self._discovery_info[CONF_DEVICE_ID],
                            CONF_NAME: self._discovery_info[CONF_NAME],
                            CONF_MODEL: self._discovery_info[CONF_MODEL],
                            CONF_CREDENTIALS: credentials,
                        },
                    )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required("pin"): str}),
            description_placeholders={
                "name": self._discovery_info[CONF_NAME],
            },
            errors=errors,
        )
