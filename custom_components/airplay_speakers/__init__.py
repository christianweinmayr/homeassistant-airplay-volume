"""The AirPlay Speakers integration."""

from __future__ import annotations

import asyncio
import logging

import pyatv
from pyatv.const import Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_AIRPLAY_CREDENTIALS,
    CONF_ATV_IDENTIFIER,
    CONF_COMPANION_CREDENTIALS,
    DOMAIN,
)
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirPlay Speakers from a config entry."""
    identifier = entry.data[CONF_ATV_IDENTIFIER]
    companion_creds = entry.data[CONF_COMPANION_CREDENTIALS]
    airplay_creds = entry.data[CONF_AIRPLAY_CREDENTIALS]

    loop = asyncio.get_running_loop()

    # Scan network to find the Apple TV by its unique identifier
    _LOGGER.debug("Scanning network for Apple TV %s", identifier)
    try:
        configs = await pyatv.scan(loop, timeout=5)
    except Exception as err:
        raise ConfigEntryNotReady(f"Network scan failed: {err}") from err

    config = None
    for c in configs:
        if c.identifier == identifier:
            config = c
            break

    if config is None:
        raise ConfigEntryNotReady(
            f"Apple TV {entry.title} not found on network"
        )

    config.set_credentials(Protocol.Companion, companion_creds)
    config.set_credentials(Protocol.AirPlay, airplay_creds)

    _LOGGER.debug("Connecting to Apple TV %s", config.name)
    try:
        atv = await pyatv.connect(config, loop)
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to connect to Apple TV: {err}") from err

    coordinator = AirplaySpeakerCoordinator(hass, entry, atv)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "atv": atv,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AirPlay Speakers config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        atv = data.get("atv")
        if atv is not None:
            atv.close()
    return unload_ok
