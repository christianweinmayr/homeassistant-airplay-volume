"""DataUpdateCoordinator for polling AirPlay speaker state."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .apple_tv import AppleTVBridge
from .binary_manager import (
    CLIAirplayAuthenticationError,
    CLIAirplayConnectionError,
    CLIAirplayManager,
)
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class AirplaySpeakerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls an AirPlay speaker for volume/mute/playing state."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        manager: CLIAirplayManager,
        apple_tv_bridge: AppleTVBridge | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: The config entry for this speaker.
            manager: The CLIAirplayManager instance for communicating with the speaker.
            apple_tv_bridge: Optional Apple TV bridge for enhanced playback info.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self.config_entry = entry
        self.manager = manager
        self.apple_tv_bridge = apple_tv_bridge

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll the speaker for current state.

        Returns:
            Dict with keys: volume (float 0.0-1.0), muted (bool), playing (bool).

        Raises:
            ConfigEntryAuthFailed: When credentials are invalid or expired.
            UpdateFailed: When the speaker cannot be reached.
        """
        try:
            volume = await self.manager.get_volume()
            muted = await self.manager.get_muted()
        except CLIAirplayAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication failed for {self.manager.device_id}: {err}"
            ) from err
        except CLIAirplayConnectionError as err:
            raise UpdateFailed(
                f"Failed to update {self.manager.device_id}: {err}"
            ) from err

        data: dict[str, Any] = {
            "volume": volume,
            "muted": muted,
            "playing": False,
            "playing_title": None,
            "playing_artist": None,
            "media_position": None,
            "media_type": None,
        }

        # Fetch playback state from Apple TV if available
        if self.apple_tv_bridge is not None and self.apple_tv_bridge.is_connected:
            try:
                playing_state = await self.apple_tv_bridge.get_playing_state()
                data["playing"] = playing_state.get("state") == "playing"
                data["playing_title"] = playing_state.get("title")
                data["playing_artist"] = playing_state.get("artist")
                data["media_position"] = playing_state.get("position")
                data["media_type"] = playing_state.get("state")
            except ConnectionError:
                _LOGGER.debug(
                    "Apple TV disconnected during update, scheduling reconnect"
                )
                self.apple_tv_bridge.schedule_reconnect()

        return data
