"""Sensor platform for the Napper integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NapperCoordinator

# Ordered: text/status info first, then time-based sensors
SENSOR_TYPES: dict[str, tuple[str, str | None, str | None]] = {
    # key: (name_suffix, unit, icon)
    # --- Text / status info up top ---
    "last_event_type": ("Last Event Type", None, "mdi:format-list-bulleted"),
    "last_event": ("Last Event Time", None, "mdi:clock-outline"),
    "how_baby_slept": ("How Baby Slept", None, "mdi:star-outline"),
    "events_today": ("Events Today", None, "mdi:counter"),
    "night_wakings": ("Night Wakings", None, "mdi:eye-outline"),
    "nap_skipped": ("Nap Skipped", None, "mdi:cancel"),
    # --- Time-based sensors ---
    "wake_time": ("Wake Time", None, "mdi:weather-sunset-up"),
    "nap_start": ("Nap Start", None, "mdi:sleep"),
    "nap_end": ("Nap End", None, "mdi:sleep-off"),
    "nap_duration_min": ("Nap Duration", "min", "mdi:timer-outline"),
    "bedtime": ("Bedtime", None, "mdi:weather-night"),
    "suggested_wake_time": ("Suggested Wake Time", None, "mdi:crystal-ball"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        NapperSensor(coordinator, entry, key, name, unit, icon)
        for key, (name, unit, icon) in SENSOR_TYPES.items()
    ]
    async_add_entities(entities)


class NapperSensor(CoordinatorEntity[NapperCoordinator], SensorEntity):
    """A single Napper sleep data sensor."""

    def __init__(
        self,
        coordinator: NapperCoordinator,
        entry: ConfigEntry,
        key: str,
        name_suffix: str,
        unit: str | None,
        icon: str | None,
    ) -> None:
        super().__init__(coordinator)
        baby_name = coordinator.baby_name or "Baby"
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = f"{baby_name} {name_suffix}"
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)
