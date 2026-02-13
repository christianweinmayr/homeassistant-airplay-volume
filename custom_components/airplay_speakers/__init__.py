"""The AirPlay Speakers integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .apple_tv import AppleTVBridge, find_apple_tv
from .binary_manager import BinaryNotFoundError, CLIAirplayManager
from .const import CONF_APPLE_TV_ID, CONF_CREDENTIALS, CONF_DEVICE_ID, DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirPlay Speakers from a config entry."""
    manager = CLIAirplayManager(
        hass=hass,
        device_id=entry.data[CONF_DEVICE_ID],
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        credentials=entry.data.get(CONF_CREDENTIALS),
    )

    try:
        await manager.start()
    except BinaryNotFoundError as err:
        raise ConfigEntryNotReady(
            f"cliairplay binary not available: {err}"
        ) from err
    except OSError as err:
        raise ConfigEntryNotReady(
            f"Failed to start cliairplay for {entry.title}: {err}"
        ) from err

    # Try to find and connect to an Apple TV for enhanced playback control
    apple_tv_bridge: AppleTVBridge | None = None
    atv_id = entry.data.get(CONF_APPLE_TV_ID)
    if atv_id:
        apple_tv_bridge = AppleTVBridge(hass, atv_id)
        try:
            await apple_tv_bridge.connect()
        except (ConnectionError, RuntimeError):
            _LOGGER.debug(
                "Apple TV %s not available, continuing without it", atv_id
            )
            apple_tv_bridge = None
    else:
        # Auto-detect an Apple TV on the network
        apple_tvs = await find_apple_tv(hass)
        if apple_tvs:
            atv_info = apple_tvs[0]
            _LOGGER.info(
                "Found Apple TV '%s' (%s), connecting for enhanced control",
                atv_info["name"],
                atv_info["identifier"],
            )
            apple_tv_bridge = AppleTVBridge(hass, atv_info["identifier"])
            try:
                await apple_tv_bridge.connect()
            except (ConnectionError, RuntimeError):
                _LOGGER.debug(
                    "Apple TV '%s' not reachable, continuing without it",
                    atv_info["name"],
                )
                apple_tv_bridge = None

    coordinator = AirplaySpeakerCoordinator(
        hass, entry, manager, apple_tv_bridge=apple_tv_bridge
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "manager": manager,
        "apple_tv_bridge": apple_tv_bridge,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an AirPlay Speakers config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        bridge = data.get("apple_tv_bridge")
        if bridge is not None:
            await bridge.disconnect()
        await data["manager"].stop()

    return unload_ok
