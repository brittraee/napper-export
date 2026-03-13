"""Button platform for the Napper integration.

Provides pill-style action buttons: Log Nap, Stop Nap, Log Bedtime.
Each button writes to the local sleep.db first, then best-effort syncs
to the Napper API so Cory's app stays up to date.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_DB_PATH, DOMAIN
from .coordinator import NapperCoordinator
from . import db

_LOGGER = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _local_iso() -> str:
    """ISO timestamp in local time with offset."""
    now = datetime.now().astimezone()
    return now.strftime("%Y-%m-%dT%H:%M:%S") + now.strftime("%z")


def _try_api_post(coordinator: NapperCoordinator, path: str, body: dict) -> None:
    """Best-effort POST to Napper API. Logs but doesn't raise on failure."""
    try:
        coordinator.api_post(path, body)
    except Exception as err:
        _LOGGER.warning("Napper API sync failed (non-fatal): %s", err)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NapperCoordinator = hass.data[DOMAIN][entry.entry_id]
    baby_name = coordinator.baby_name or "Baby"
    db_path = entry.data.get("db_path", DEFAULT_DB_PATH)
    async_add_entities([
        NapperLogNapButton(coordinator, entry, baby_name, db_path),
        NapperStopNapButton(coordinator, entry, baby_name, db_path),
        NapperLogBedButton(coordinator, entry, baby_name, db_path),
    ])


class NapperLogNapButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Log the start of a nap."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry,
        baby_name: str, db_path: str,
    ) -> None:
        super().__init__(coordinator)
        self._db_path = db_path
        self._attr_unique_id = f"{entry.entry_id}_log_nap"
        self._attr_name = f"{baby_name} Log Nap"
        self._attr_icon = "mdi:sleep"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_log_nap")
        )

    async def async_press(self) -> None:
        now_utc = _now_iso()
        now_local = _local_iso()

        # Local DB first
        await self.hass.async_add_executor_job(
            db.log_event, self._db_path, "NAP", now_local
        )

        # Best-effort API sync
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "NAP",
            "start": now_utc,
        }
        await self.hass.async_add_executor_job(
            _try_api_post, self.coordinator, "/logs", body
        )
        await self.coordinator.async_request_refresh()


class NapperStopNapButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """End the current nap."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry,
        baby_name: str, db_path: str,
    ) -> None:
        super().__init__(coordinator)
        self._db_path = db_path
        self._attr_unique_id = f"{entry.entry_id}_stop_nap"
        self._attr_name = f"{baby_name} Stop Nap"
        self._attr_icon = "mdi:sleep-off"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_stop_nap")
        )

    async def async_press(self) -> None:
        now_local = _local_iso()
        now_utc = _now_iso()

        # Local DB first — close the open nap
        await self.hass.async_add_executor_job(
            db.end_nap, self._db_path, now_local
        )

        # Best-effort API sync
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "NAP",
            "end": now_utc,
        }
        await self.hass.async_add_executor_job(
            _try_api_post, self.coordinator, "/logs/end", body
        )
        await self.coordinator.async_request_refresh()


class NapperLogBedButton(CoordinatorEntity[NapperCoordinator], ButtonEntity):
    """Log bedtime."""

    def __init__(
        self, coordinator: NapperCoordinator, entry: ConfigEntry,
        baby_name: str, db_path: str,
    ) -> None:
        super().__init__(coordinator)
        self._db_path = db_path
        self._attr_unique_id = f"{entry.entry_id}_log_bed"
        self._attr_name = f"{baby_name} Log Bedtime"
        self._attr_icon = "mdi:weather-night"

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.get("show_log_bed")
        )

    async def async_press(self) -> None:
        now_utc = _now_iso()
        now_local = _local_iso()

        # Local DB first
        await self.hass.async_add_executor_job(
            db.log_event, self._db_path, "BED_TIME", now_local
        )

        # Best-effort API sync
        body = {
            "babyId": self.coordinator.baby_id,
            "category": "BED_TIME",
            "start": now_utc,
        }
        await self.hass.async_add_executor_job(
            _try_api_post, self.coordinator, "/logs", body
        )
        await self.coordinator.async_request_refresh()
