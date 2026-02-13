"""Volume control entities for AirPlay speakers controlled via Apple TV."""

from __future__ import annotations

import logging

from pyatv.interface import OutputDevice

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirplaySpeakerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AirPlay speaker volume controls from Apple TV output devices."""
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
                    AirplaySpeakerVolume(coordinator, entry, dev_id, dev_info["name"])
                )

        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_devices))


class AirplaySpeakerVolume(
    CoordinatorEntity[AirplaySpeakerCoordinator], NumberEntity
):
    """Volume slider for an AirPlay speaker."""

    _attr_has_entity_name = True
    _attr_name = "Volume"
    _attr_icon = "mdi:speaker"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        coordinator: AirplaySpeakerCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
    ) -> None:
        """Initialize the volume entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_unique_id = f"{device_id}_volume"
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
    def native_value(self) -> float | None:
        """Return the current volume."""
        data = self._device_data
        if data is None:
            return None
        return data.get("volume")

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        output_device = OutputDevice(
            identifier=self._device_id,
            name=self._device_name,
        )
        try:
            await self.coordinator.atv.audio.set_volume(
                value, output_device=output_device
            )
        except Exception:
            _LOGGER.exception("Failed to set volume for %s", self._device_name)
            return
        await self.coordinator.async_request_refresh()
