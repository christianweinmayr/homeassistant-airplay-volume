"""DataUpdateCoordinator for polling AirPlay speaker state."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

try:
    from pyatv.interface import AppleTV
except ImportError:
    AppleTV = None  # type: ignore[assignment, misc]


class AirplaySpeakerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls an AirPlay speaker for volume state via pyatv."""

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
        """Poll the speaker for current state."""
        try:
            volume = self.atv.audio.volume
        except Exception as err:
            raise UpdateFailed(
                f"Failed to get volume for {self.config_entry.title}: {err}"
            ) from err

        return {
            "volume": volume / 100.0 if volume is not None else None,
        }
