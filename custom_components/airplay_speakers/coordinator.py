"""DataUpdateCoordinator for polling AirPlay speaker state via Apple TV."""

from __future__ import annotations

import logging
from typing import Any

from pyatv.interface import AppleTV, OutputDevice

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AirplaySpeakerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Apple TV for output device state."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        atv: AppleTV,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.atv = atv

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll Apple TV for output devices and playback state."""
        try:
            output_devices: list[OutputDevice] = self.atv.audio.output_devices
        except Exception as err:
            raise UpdateFailed(f"Failed to get output devices: {err}") from err

        try:
            playing = await self.atv.metadata.playing()
            device_state = str(playing.device_state)
            title = playing.title
            artist = playing.artist
        except Exception:
            device_state = None
            title = None
            artist = None

        devices = {}
        for dev in output_devices:
            devices[dev.identifier] = {
                "name": dev.name,
                "volume": dev.volume,
                "identifier": dev.identifier,
                "output_device": dev,
            }

        return {
            "devices": devices,
            "device_state": device_state,
            "title": title,
            "artist": artist,
        }
