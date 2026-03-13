"""Button platform for the Napper integration.

Provides pill-style action buttons: Log Nap, Stop Nap, Log Bedtime.
"""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NapperCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    baby_name = coordinator.baby_name or "Baby"
    async_add_entities([
        NapperLogNapButton(coordinator, entry, baby_name),
        NapperStopNapButton(coordinator, entry, baby_name),
        NapperLogBedButton(coordinator, entry, baby_name),
    ])


class NapperLogNapButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Log the start of a nap."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry, baby_name: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_log_nap"
        self._attr_name = f"{baby_name} Log Nap"
        self._attr_icon = "mdi:sleep"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_log_nap")
        )

    async def async_press(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "NAP",
            "start": now,
        }
        await self.hass.async_add_executor_job(
            self.coordinator.api_post, "/logs", body
        )
        await self.coordinator.async_request_refresh()


class NapperStopNapButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """End the current nap."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry, baby_name: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_stop_nap"
        self._attr_name = f"{baby_name} Stop Nap"
        self._attr_icon = "mdi:sleep-off"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_stop_nap")
        )

    async def async_press(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "NAP",
            "end": now,
        }
        await self.hass.async_add_executor_job(
            self.coordinator.api_post, "/logs/end", body
        )
        await self.coordinator.async_request_refresh()


class NapperLogBedButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Log bedtime."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry, baby_name: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_log_bed"
        self._attr_name = f"{baby_name} Log Bedtime"
        self._attr_icon = "mdi:weather-night"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_log_bed")
        )

    async def async_press(self) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "BED_TIME",
            "start": now,
        }
        await self.hass.async_add_executor_job(
            self.coordinator.api_post, "/logs", body
        )
        await self.coordinator.async_request_refresh()
