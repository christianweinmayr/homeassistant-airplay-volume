"""Media player entities for AirPlay speakers controlled via Apple TV."""

from __future__ import annotations

import logging

from pyatv.interface import OutputDevice

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

VOLUME_STEP_SIZE = 5.0  # 5% steps (in 0-100 range)

_SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)

# Map pyatv DeviceState string representations to HA states
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
    """Set up AirPlay speaker entities from Apple TV output devices."""
    coordinator: AirplaySpeakerCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    known_ids: set[str] = set()

    @callback
    def _async_add_new_devices() -> None:
        """Add entities for newly discovered output devices."""
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

    # Add entities for devices already known
    _async_add_new_devices()

    # Listen for coordinator updates to add newly grouped devices
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))


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
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the AirPlay speaker entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer="AirPlay",
            via_device=(DOMAIN, f"atv_{entry.entry_id}"),
        )

    @property
    def _device_data(self) -> dict | None:
        """Get current data for this device from coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("devices", {}).get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True if the speaker is in the current output group."""
        return self.coordinator.last_update_success and self._device_data is not None

    @property
    def state(self) -> MediaPlayerState:
        """Return the current playback state."""
        if not self.available:
            return MediaPlayerState.IDLE
        device_state = self.coordinator.data.get("device_state")
        return _STATE_MAP.get(device_state, MediaPlayerState.IDLE)

    @property
    def media_title(self) -> str | None:
        """Return the current media title."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("title")

    @property
    def media_artist(self) -> str | None:
        """Return the current media artist."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("artist")

    @property
    def volume_level(self) -> float | None:
        """Return the current volume level (0.0 to 1.0)."""
        data = self._device_data
        if data is None:
            return None
        vol = data.get("volume")
        if vol is None:
            return None
        return vol / 100.0

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0.0 to 1.0)."""
        data = self._device_data
        if data is None:
            _LOGGER.warning("Cannot set volume: device %s not available", self._device_name)
            return

        output_device = OutputDevice(
            identifier=self._device_id,
            name=self._device_name,
        )
        try:
            await self.coordinator.atv.audio.set_volume(
                volume * 100.0,
                output_device=output_device,
            )
        except Exception:
            _LOGGER.exception("Failed to set volume for %s", self._device_name)
            return
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Increase volume by step."""
        current = (self.volume_level or 0.0) * 100.0
        target = min(100.0, current + VOLUME_STEP_SIZE)
        await self.async_set_volume_level(target / 100.0)

    async def async_volume_down(self) -> None:
        """Decrease volume by step."""
        current = (self.volume_level or 0.0) * 100.0
        target = max(0.0, current - VOLUME_STEP_SIZE)
        await self.async_set_volume_level(target / 100.0)
