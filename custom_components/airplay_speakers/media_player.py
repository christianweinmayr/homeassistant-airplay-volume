"""Media player entity for AirPlay speakers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_MODEL, DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

VOLUME_STEP_SIZE = 0.05

_SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AirPlay speaker media player from a config entry."""
    coordinator: AirplaySpeakerCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([AirplaySpeakerEntity(coordinator, entry)])


class AirplaySpeakerEntity(
    CoordinatorEntity[AirplaySpeakerCoordinator], MediaPlayerEntity
):
    """Representation of an AirPlay speaker as a media player entity."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = _SUPPORTED_FEATURES

    def __init__(
        self,
        coordinator: AirplaySpeakerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the AirPlay speaker entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.data[CONF_DEVICE_ID]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.title,
            manufacturer="Apple",
            model=entry.data.get(CONF_MODEL),
        )

    @property
    def state(self) -> MediaPlayerState:
        """Return the current state of the speaker."""
        if self.coordinator.data is None:
            return MediaPlayerState.IDLE
        return MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        """Return the current volume level (0.0 to 1.0)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("volume")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0.0 to 1.0)."""
        try:
            await self.coordinator.atv.audio.set_volume(volume * 100.0)
        except Exception:
            _LOGGER.warning(
                "Failed to set volume for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Increase volume by 5%."""
        current = self.volume_level or 0.0
        await self.async_set_volume_level(min(1.0, current + VOLUME_STEP_SIZE))

    async def async_volume_down(self) -> None:
        """Decrease volume by 5%."""
        current = self.volume_level or 0.0
        await self.async_set_volume_level(max(0.0, current - VOLUME_STEP_SIZE))
