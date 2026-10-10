"""Data update coordinator for Napper."""

import json
import logging
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class NapperCoordinator(DataUpdateCoordinator):
    """Fetch today's sleep data from the Napper API."""

    def __init__(
        self,
        hass: HomeAssistant,
        baby_id: str,
        token: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Napper",
            update_interval=update_interval,
        )
        self._baby_id = baby_id
        self._token = token
        self._baby_name: str | None = None

    @property
    def baby_name(self) -> str | None:
        return self._baby_name

    def _api_get(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        req = Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except Exception as err:
            raise UpdateFailed(f"Error fetching Napper data: {err}") from err

    def _fetch(self) -> dict:
        # Fetch baby name on first run
        if self._baby_name is None:
            try:
                babies = self._api_get("/babies")
                items = babies.get("items", [])
                for baby in items:
                    if baby.get("id") == self._baby_id:
                        self._baby_name = baby.get("name", "Baby")
                        break
                if not self._baby_name and items:
                    self._baby_name = items[0].get("name", "Baby")
            except (HTTPError, Exception):
                self._baby_name = "Baby"

        # Fetch today and yesterday
        today = date.today()
        yesterday = today - timedelta(days=1)
        path = f"/logs-between-days/{self._baby_id}/{yesterday.isoformat()}/{today.isoformat()}"

        data = self._api_get(path)
        items = data.get("items", [])

        today_str = today.isoformat()
        yesterday_str = yesterday.isoformat()

        today_events = []
        yesterday_events = []
        for ev in items:
            start = ev.get("start", "")
            ev_date = start[:10] if start else ""
            if ev_date == today_str:
                today_events.append(ev)
            elif ev_date == yesterday_str:
                yesterday_events.append(ev)

        return self._summarize(today_events, yesterday_events, today_str)

    def _summarize(
        self, today_events: list, yesterday_events: list, today_str: str
    ) -> dict:
        result = {
            "date": today_str,
            "wake_time": None,
            "nap_start": None,
            "nap_end": None,
            "nap_duration_min": None,
            "nap_skipped": False,
            "bedtime": None,
            "how_baby_slept": None,
            "night_wakings": 0,
            "last_event": None,
            "last_event_type": None,
            "events_today": len(today_events),
        }

        for ev in today_events:
            cat = ev.get("category")
            start = ev.get("start", "")
            end = ev.get("end", "")
            time_str = start[11:16] if len(start) >= 16 else None

            if cat == "WOKE_UP":
                result["wake_time"] = time_str
            elif cat == "NAP":
                if ev.get("skipped") or ev.get("isSkipped"):
                    result["nap_skipped"] = True
                else:
                    result["nap_start"] = time_str
                    end_time = end[11:16] if len(end) >= 16 else None
                    result["nap_end"] = end_time
                    if start and end:
                        result["nap_duration_min"] = self._duration_min(start, end)
                    result["how_baby_slept"] = ev.get("howBabySlept")
            elif cat == "BED_TIME":
                result["bedtime"] = time_str
            elif cat == "NIGHT_WAKING":
                result["night_wakings"] += 1

            if time_str:
                result["last_event"] = time_str
                result["last_event_type"] = cat

        # If no bedtime today, check yesterday
        if result["bedtime"] is None:
            for ev in yesterday_events:
                if ev.get("category") == "BED_TIME":
                    start = ev.get("start", "")
                    result["bedtime"] = start[11:16] if len(start) >= 16 else None

        return result

    @staticmethod
    def _duration_min(start: str, end: str) -> float | None:
        from datetime import datetime
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            s = datetime.strptime(start[:19], fmt)
            e = datetime.strptime(end[:19], fmt)
            diff = (e - s).total_seconds() / 60
            return round(diff, 1) if diff > 0 else None
        except (ValueError, TypeError):
            return None
