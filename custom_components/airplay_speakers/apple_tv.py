"""Optional Apple TV bridge for enhanced playback control via pyatv MRP protocol.

When an Apple TV is present on the network, this module provides:
- Full playback control (play, pause, stop, skip)
- Speaker grouping (add/remove AirPlay output devices)
- Playback state information (title, artist, album, position)

Without an Apple TV, these features are unavailable and the integration
falls back to volume-only control via cliairplay.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Reconnection constants
_RECONNECT_BACKOFF_BASE = 2  # seconds
_RECONNECT_BACKOFF_MAX = 60  # seconds
_MAX_RECONNECT_ATTEMPTS = 5
_SCAN_TIMEOUT = 5  # seconds for pyatv.scan

# Graceful degradation: pyatv is optional
try:
    import pyatv
    from pyatv.const import DeviceState, Protocol
    from pyatv.interface import AppleTV, Playing

    PYATV_AVAILABLE = True
except ImportError:
    PYATV_AVAILABLE = False


async def find_apple_tv(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Scan the network for Apple TVs using pyatv.

    Returns a list of dicts with keys: name, identifier, address.
    Returns an empty list if pyatv is not installed.
    """
    if not PYATV_AVAILABLE:
        _LOGGER.debug("pyatv not installed, Apple TV discovery unavailable")
        return []

    loop = asyncio.get_running_loop()
    _LOGGER.debug("Scanning for Apple TVs on the network")

    try:
        configs = await pyatv.scan(loop, timeout=_SCAN_TIMEOUT)
    except Exception:
        _LOGGER.debug("Apple TV scan failed", exc_info=True)
        return []

    results: list[dict[str, Any]] = []
    for config in configs:
        # Only include devices that support MRP (Apple TV 4+)
        if any(
            service.protocol == Protocol.MRP for service in config.services
        ):
            results.append(
                {
                    "name": config.name,
                    "identifier": config.identifier,
                    "address": str(config.address),
                }
            )

    _LOGGER.debug("Found %d Apple TV(s) with MRP support", len(results))
    return results


class AppleTVBridge:
    """Bridge to an Apple TV for MRP-based playback control and speaker grouping."""

    def __init__(self, hass: HomeAssistant, atv_identifier: str) -> None:
        """Initialize the Apple TV bridge.

        Args:
            hass: Home Assistant instance.
            atv_identifier: The unique identifier for the Apple TV.
        """
        self.hass = hass
        self._identifier = atv_identifier
        self._atv: AppleTV | None = None if PYATV_AVAILABLE else None
        self._reconnect_count = 0
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing = False

    async def connect(self) -> None:
        """Connect to the Apple TV via pyatv.

        Scans for the device by identifier and establishes an MRP connection.

        Raises:
            RuntimeError: If pyatv is not installed.
            ConnectionError: If the Apple TV cannot be found or connection fails.
        """
        if not PYATV_AVAILABLE:
            raise RuntimeError("pyatv is not installed")

        self._closing = False
        loop = asyncio.get_running_loop()

        _LOGGER.debug("Connecting to Apple TV %s", self._identifier)

        try:
            configs = await pyatv.scan(
                loop, identifier=self._identifier, timeout=_SCAN_TIMEOUT
            )
        except Exception as err:
            raise ConnectionError(
                f"Failed to scan for Apple TV {self._identifier}: {err}"
            ) from err

        if not configs:
            raise ConnectionError(
                f"Apple TV {self._identifier} not found on the network"
            )

        config = configs[0]

        try:
            self._atv = await pyatv.connect(config, loop, protocol=Protocol.MRP)
        except pyatv.exceptions.AuthenticationError as err:
            raise ConnectionError(
                f"Authentication failed for Apple TV {self._identifier}: {err}"
            ) from err
        except pyatv.exceptions.ConnectionFailedError as err:
            raise ConnectionError(
                f"Connection failed to Apple TV {self._identifier}: {err}"
            ) from err

        self._reconnect_count = 0
        _LOGGER.debug(
            "Connected to Apple TV %s (%s)", config.name, self._identifier
        )

    async def disconnect(self) -> None:
        """Close the pyatv connection."""
        self._closing = True

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._atv is not None:
            self._atv.close()
            self._atv = None
            _LOGGER.debug("Disconnected from Apple TV %s", self._identifier)

    @property
    def is_connected(self) -> bool:
        """Return whether the bridge is connected to the Apple TV."""
        return self._atv is not None

    async def play(self) -> None:
        """Send play command via MRP."""
        atv = self._get_atv()
        _LOGGER.debug("Sending play to Apple TV %s", self._identifier)
        await atv.remote_control.play()

    async def pause(self) -> None:
        """Send pause command via MRP."""
        atv = self._get_atv()
        _LOGGER.debug("Sending pause to Apple TV %s", self._identifier)
        await atv.remote_control.pause()

    async def stop(self) -> None:
        """Send stop command via MRP."""
        atv = self._get_atv()
        _LOGGER.debug("Sending stop to Apple TV %s", self._identifier)
        await atv.remote_control.stop()

    async def next_track(self) -> None:
        """Skip to next track via MRP."""
        atv = self._get_atv()
        _LOGGER.debug("Sending next to Apple TV %s", self._identifier)
        await atv.remote_control.next()

    async def previous_track(self) -> None:
        """Skip to previous track via MRP."""
        atv = self._get_atv()
        _LOGGER.debug("Sending previous to Apple TV %s", self._identifier)
        await atv.remote_control.previous()

    async def get_playing_state(self) -> dict[str, Any]:
        """Get current playback information from the Apple TV.

        Returns:
            Dict with keys: state (str), title, artist, album (str or None),
            position (int or None), total_time (int or None).
        """
        atv = self._get_atv()
        _LOGGER.debug(
            "Getting playing state from Apple TV %s", self._identifier
        )
        playing: Playing = await atv.metadata.playing()

        state_map = {
            DeviceState.Idle: "idle",
            DeviceState.Loading: "loading",
            DeviceState.Paused: "paused",
            DeviceState.Playing: "playing",
            DeviceState.Seeking: "seeking",
            DeviceState.Stopped: "stopped",
        }

        return {
            "state": state_map.get(playing.device_state, "unknown"),
            "title": playing.title,
            "artist": playing.artist,
            "album": playing.album,
            "position": playing.position,
            "total_time": playing.total_time,
        }

    async def add_output_device(self, device_id: str) -> None:
        """Add an AirPlay speaker to the output group.

        Args:
            device_id: The device ID (MAC address) of the speaker to add.
        """
        atv = self._get_atv()
        _LOGGER.debug(
            "Adding output device %s on Apple TV %s",
            device_id,
            self._identifier,
        )
        await atv.audio.add_output_devices([device_id])

    async def remove_output_device(self, device_id: str) -> None:
        """Remove an AirPlay speaker from the output group.

        Args:
            device_id: The device ID (MAC address) of the speaker to remove.
        """
        atv = self._get_atv()
        _LOGGER.debug(
            "Removing output device %s on Apple TV %s",
            device_id,
            self._identifier,
        )
        await atv.audio.remove_output_devices([device_id])

    async def set_output_devices(self, device_ids: list[str]) -> None:
        """Set the exact list of AirPlay speakers in the output group.

        Args:
            device_ids: List of device IDs (MAC addresses) for the group.
        """
        atv = self._get_atv()
        _LOGGER.debug(
            "Setting output devices %s on Apple TV %s",
            device_ids,
            self._identifier,
        )
        await atv.audio.set_output_devices(device_ids)

    def schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt with exponential backoff.

        Safe to call multiple times; only one reconnection loop runs at a time.
        """
        if self._closing:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return

        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(),
            name=f"appletv_reconnect_{self._identifier}",
        )

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        while not self._closing:
            if self._reconnect_count >= _MAX_RECONNECT_ATTEMPTS:
                _LOGGER.error(
                    "Apple TV %s: giving up reconnection after %d attempts",
                    self._identifier,
                    self._reconnect_count,
                )
                return

            backoff = min(
                _RECONNECT_BACKOFF_BASE * (2**self._reconnect_count),
                _RECONNECT_BACKOFF_MAX,
            )
            self._reconnect_count += 1

            _LOGGER.debug(
                "Apple TV %s: reconnecting in %ds (attempt %d/%d)",
                self._identifier,
                backoff,
                self._reconnect_count,
                _MAX_RECONNECT_ATTEMPTS,
            )

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return

            if self._closing:
                return

            try:
                await self.connect()
                _LOGGER.info(
                    "Apple TV %s: reconnected successfully", self._identifier
                )
                return
            except ConnectionError:
                _LOGGER.debug(
                    "Apple TV %s: reconnection attempt %d failed",
                    self._identifier,
                    self._reconnect_count,
                    exc_info=True,
                )

    def _get_atv(self) -> AppleTV:
        """Return the connected AppleTV instance or raise."""
        if self._atv is None:
            raise ConnectionError(
                f"Not connected to Apple TV {self._identifier}"
            )
        return self._atv
