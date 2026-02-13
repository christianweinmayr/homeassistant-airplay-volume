"""Media player entity for AirPlay speakers (state and media info display)."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

_STATE_MAP = {
    "DeviceState.Playing": MediaPlayerState.PLAYING,
    "DeviceState.Paused": MediaPlayerState.PAUSED,
    "DeviceState.Stopped": MediaPlayerState.IDLE,
    "DeviceState.Idle": MediaPlayerState.IDLE,
    "DeviceState.Seeking": MediaPlayerState.PLAYING,
    "DeviceState.Loading": MediaPlayerState.BUFFERING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AirPlay speaker media player from Apple TV output devices."""
    coordinator: AirplaySpeakerCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    known_ids: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        if coordinator.data is None:
            return
        devices = coordinator.data.get("devices", {})
        new_entities = []
        for dev_id, dev_info in devices.items():
            if dev_id not in known_ids:
                known_ids.add(dev_id)
                new_entities.append(
                    AirplaySpeakerEntity(coordinator, entry, dev_id, dev_info["name"])
                )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))


class AirplaySpeakerEntity(
    CoordinatorEntity[AirplaySpeakerCoordinator], MediaPlayerEntity
):
    """AirPlay speaker media player showing playback state and media info."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = MediaPlayerEntityFeature(0)

    def __init__(
        self,
        coordinator: AirplaySpeakerCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="AirPlay",
            via_device=(DOMAIN, f"atv_{entry.entry_id}"),
        )

    @property
    def available(self) -> bool:
        if self.coordinator.data is None:
            return False
        return (
            self.coordinator.last_update_success
            and self._device_id in self.coordinator.data.get("devices", {})
        )

    @property
    def state(self) -> MediaPlayerState:
        if not self.available:
            return MediaPlayerState.IDLE
        device_state = self.coordinator.data.get("device_state")
        return _STATE_MAP.get(device_state, MediaPlayerState.IDLE)

    @property
    def media_title(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("title")

    @property
    def media_artist(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("artist")
