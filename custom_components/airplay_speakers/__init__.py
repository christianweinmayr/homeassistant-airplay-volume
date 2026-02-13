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
    CONF_ATV_HOST,
    CONF_COMPANION_CREDENTIALS,
    DOMAIN,
)
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirPlay Speakers from a config entry."""
    host = entry.data[CONF_ATV_HOST]
    companion_creds = entry.data[CONF_COMPANION_CREDENTIALS]
    airplay_creds = entry.data[CONF_AIRPLAY_CREDENTIALS]

    loop = asyncio.get_running_loop()

    _LOGGER.debug("Scanning for Apple TV at %s", host)
    try:
        configs = await pyatv.scan(loop, hosts=[host], timeout=5)
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed to scan for Apple TV at {host}: {err}") from err

    if not configs:
        raise ConfigEntryNotReady(f"Apple TV not found at {host}")

    config = configs[0]
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
