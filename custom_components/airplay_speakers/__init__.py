"""The AirPlay Speakers integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player"]

try:
    import pyatv
    from pyatv.const import Protocol
except ImportError:
    pyatv = None  # type: ignore[assignment]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirPlay Speakers from a config entry."""
    if pyatv is None:
        raise ConfigEntryNotReady("pyatv library is not installed")

    host = entry.data[CONF_HOST]
    device_id = entry.data[CONF_DEVICE_ID]

    loop = asyncio.get_running_loop()

    # Scan for the specific speaker by host address
    _LOGGER.debug("Scanning for AirPlay speaker at %s", host)
    try:
        configs = await pyatv.scan(loop, hosts=[host], timeout=5)
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Failed to scan for speaker {entry.title} at {host}: {err}"
        ) from err

    if not configs:
        raise ConfigEntryNotReady(
            f"Speaker {entry.title} not found at {host}"
        )

    config = configs[0]

    # Connect via RAOP protocol for speaker control
    _LOGGER.debug(
        "Connecting to %s via pyatv (protocols: %s)",
        entry.title,
        [s.protocol.name for s in config.services],
    )

    try:
        atv = await pyatv.connect(config, loop)
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Failed to connect to speaker {entry.title}: {err}"
        ) from err

    coordinator = AirplaySpeakerCoordinator(hass, entry, atv)

    # Don't block setup if the first poll fails.
    # The entity will show as unavailable and the coordinator retries.
    await coordinator.async_refresh()

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
