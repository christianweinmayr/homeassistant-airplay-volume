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

from .apple_tv import AppleTVBridge
from .binary_manager import CLIAirplayConnectionError
from .const import CONF_DEVICE_ID, CONF_MODEL, DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)

VOLUME_STEP_SIZE = 0.05

_BASE_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

_APPLE_TV_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
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

    def __init__(
        self,
        coordinator: AirplaySpeakerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the AirPlay speaker entity.

        Args:
            coordinator: The data update coordinator for this speaker.
            entry: The config entry for this speaker.
        """
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
    def _apple_tv_bridge(self) -> AppleTVBridge | None:
        """Return the Apple TV bridge if available and connected."""
        bridge = self.coordinator.apple_tv_bridge
        if bridge is not None and bridge.is_connected:
            return bridge
        return None

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported features, dynamically adding playback controls with Apple TV."""
        features = _BASE_FEATURES
        if self._apple_tv_bridge is not None:
            features |= _APPLE_TV_FEATURES
        return features

    @property
    def state(self) -> MediaPlayerState:
        """Return the current state of the speaker."""
        if self.coordinator.data is None:
            return MediaPlayerState.OFF

        media_state = self.coordinator.data.get("media_type")
        if media_state == "paused":
            return MediaPlayerState.PAUSED
        if self.coordinator.data.get("playing"):
            return MediaPlayerState.PLAYING

        return MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        """Return the current volume level (0.0 to 1.0)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("volume")

    @property
    def is_volume_muted(self) -> bool | None:
        """Return whether the speaker is muted."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("muted")

    @property
    def media_title(self) -> str | None:
        """Return the title of the currently playing media."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("playing_title")

    @property
    def media_artist(self) -> str | None:
        """Return the artist of the currently playing media."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("playing_artist")

    async def async_media_play(self) -> None:
        """Send play command via Apple TV."""
        bridge = self._apple_tv_bridge
        if bridge is None:
            return
        try:
            await bridge.play()
        except ConnectionError:
            _LOGGER.debug("Apple TV play command failed for %s", self._entry.title)
            return
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        """Send pause command via Apple TV."""
        bridge = self._apple_tv_bridge
        if bridge is None:
            return
        try:
            await bridge.pause()
        except ConnectionError:
            _LOGGER.debug("Apple TV pause command failed for %s", self._entry.title)
            return
        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        """Send stop command via Apple TV."""
        bridge = self._apple_tv_bridge
        if bridge is None:
            return
        try:
            await bridge.stop()
        except ConnectionError:
            _LOGGER.debug("Apple TV stop command failed for %s", self._entry.title)
            return
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        """Skip to next track via Apple TV."""
        bridge = self._apple_tv_bridge
        if bridge is None:
            return
        try:
            await bridge.next_track()
        except ConnectionError:
            _LOGGER.debug("Apple TV next track failed for %s", self._entry.title)
            return
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        """Skip to previous track via Apple TV."""
        bridge = self._apple_tv_bridge
        if bridge is None:
            return
        try:
            await bridge.previous_track()
        except ConnectionError:
            _LOGGER.debug(
                "Apple TV previous track failed for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level (0.0 to 1.0)."""
        try:
            await self.coordinator.manager.set_volume(volume)
        except CLIAirplayConnectionError:
            _LOGGER.warning(
                "Failed to set volume for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        """Increase volume by 5%."""
        current = self.volume_level or 0.0
        try:
            await self.coordinator.manager.set_volume(
                min(1.0, current + VOLUME_STEP_SIZE)
            )
        except CLIAirplayConnectionError:
            _LOGGER.warning(
                "Failed to increase volume for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        """Decrease volume by 5%."""
        current = self.volume_level or 0.0
        try:
            await self.coordinator.manager.set_volume(
                max(0.0, current - VOLUME_STEP_SIZE)
            )
        except CLIAirplayConnectionError:
            _LOGGER.warning(
                "Failed to decrease volume for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the speaker."""
        try:
            await self.coordinator.manager.set_muted(mute)
        except CLIAirplayConnectionError:
            _LOGGER.warning(
                "Failed to set mute state for %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play media (TTS audio) on the speaker."""
        try:
            await self.coordinator.manager.play_audio(media_id, media_type)
        except CLIAirplayConnectionError:
            _LOGGER.warning(
                "Failed to play media on %s", self._entry.title
            )
            return
        await self.coordinator.async_request_refresh()
