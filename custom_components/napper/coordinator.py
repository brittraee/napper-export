"""Data update coordinator for Napper."""

import json
import logging
from datetime import date, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)

# Number of recent days to average for predicted wake time
WAKE_HISTORY_DAYS = 7


def _to_12hr(time_24: str | None) -> str | None:
    """Convert HH:MM (24hr) to h:MM AM/PM."""
    if not time_24 or len(time_24) < 5:
        return None
    try:
        hour, minute = int(time_24[:2]), int(time_24[3:5])
        period = "AM" if hour < 12 else "PM"
        display_hour = hour % 12 or 12
        return f"{display_hour}:{minute:02d} {period}"
    except (ValueError, IndexError):
        return None


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

    @property
    def baby_id(self) -> str:
        return self._baby_id

    @property
    def token(self) -> str:
        return self._token

    def _api_get(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        req = Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        })
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    def api_post(self, path: str, body: dict) -> dict:
        """POST JSON to the Napper API."""
        url = f"{API_BASE}{path}"
        data = json.dumps(body).encode()
        req = Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except Exception as err:
            raise UpdateFailed(f"Error fetching Napper data: {err}") from err

    @property
    def has_api(self) -> bool:
        """Whether an API token is configured."""
        return bool(self._token)

    def _fetch(self) -> dict:
        # Fetch baby name on first run
        if self._baby_name is None:
            if self.has_api:
                try:
                    babies = self._api_get("/babies")
                    api_items = babies.get("items", [])
                    for baby in api_items:
                        if baby.get("id") == self._baby_id:
                            self._baby_name = baby.get("name", "Baby")
                            break
                    if not self._baby_name and api_items:
                        self._baby_name = api_items[0].get("name", "Baby")
                except (HTTPError, Exception):
                    self._baby_name = "Baby"
            else:
                self._baby_name = "Baby"

        today = date.today()
        history_start = today - timedelta(days=WAKE_HISTORY_DAYS)

        items = []
        if self.has_api:
            path = f"/logs-between-days/{self._baby_id}/{history_start.isoformat()}/{today.isoformat()}"
            data = self._api_get(path)
            items = data.get("items", [])

        today_str = today.isoformat()
        yesterday_str = (today - timedelta(days=1)).isoformat()

        today_events = []
        yesterday_events = []
        recent_wake_times = []  # HH:MM strings from recent days (not today)

        for ev in items:
            start = ev.get("start", "")
            ev_date = start[:10] if start else ""
            if ev_date == today_str:
                today_events.append(ev)
            elif ev_date == yesterday_str:
                yesterday_events.append(ev)

            # Collect wake times from past days for prediction
            if (
                ev.get("category") == "WOKE_UP"
                and ev_date
                and ev_date != today_str
                and ev_date >= history_start.isoformat()
                and len(start) >= 16
            ):
                recent_wake_times.append(start[11:16])

        return self._summarize(
            today_events, yesterday_events, today_str, recent_wake_times
        )

    def _summarize(
        self,
        today_events: list,
        yesterday_events: list,
        today_str: str,
        recent_wake_times: list[str],
    ) -> dict:
        now = datetime.now()
        current_hour = now.hour

        result = {
            "date": today_str,
            "last_event_type": None,
            "last_event": None,
            "how_baby_slept": None,
            "events_today": len(today_events),
            "night_wakings": 0,
            "nap_skipped": False,
            "nap_in_progress": False,
            "wake_time": None,
            "nap_start": None,
            "nap_end": None,
            "nap_duration_min": None,
            "bedtime": None,
            "suggested_wake_time": None,
            # Visibility flags for action buttons
            "show_log_nap": False,
            "show_stop_nap": False,
            "show_log_bed": False,
        }

        has_nap_start = False
        has_nap_end = False
        has_bedtime = False

        for ev in today_events:
            cat = ev.get("category")
            start = ev.get("start", "")
            end = ev.get("end", "")
            time_str = start[11:16] if len(start) >= 16 else None

            if cat == "WOKE_UP":
                result["wake_time"] = _to_12hr(time_str)
            elif cat == "NAP":
                if ev.get("skipped") or ev.get("isSkipped"):
                    result["nap_skipped"] = True
                else:
                    has_nap_start = True
                    result["nap_start"] = _to_12hr(time_str)
                    end_time = end[11:16] if len(end) >= 16 else None
                    if end_time:
                        has_nap_end = True
                        result["nap_end"] = _to_12hr(end_time)
                    if start and end:
                        result["nap_duration_min"] = self._duration_min(start, end)
                    result["how_baby_slept"] = ev.get("howBabySlept")
            elif cat == "BED_TIME":
                has_bedtime = True
                result["bedtime"] = _to_12hr(time_str)
            elif cat == "NIGHT_WAKING":
                result["night_wakings"] += 1

            if time_str:
                result["last_event"] = _to_12hr(time_str)
                result["last_event_type"] = cat

        # Nap is in progress if started but not ended
        result["nap_in_progress"] = has_nap_start and not has_nap_end

        # Visibility rules:
        # Log Nap: show 11 AM–5 PM, only if no nap started yet today
        result["show_log_nap"] = (
            11 <= current_hour < 17
            and not has_nap_start
            and not result["nap_skipped"]
        )
        # Stop Nap: show whenever a nap is actively in progress
        result["show_stop_nap"] = result["nap_in_progress"]
        # Log Bed: show 6 PM–11 PM, only if no bedtime logged yet
        result["show_log_bed"] = 18 <= current_hour < 23 and not has_bedtime

        # If no bedtime today, check yesterday
        if result["bedtime"] is None:
            for ev in yesterday_events:
                if ev.get("category") == "BED_TIME":
                    start = ev.get("start", "")
                    result["bedtime"] = _to_12hr(
                        start[11:16] if len(start) >= 16 else None
                    )

        # Predicted tomorrow wake time: average of recent wake times
        result["suggested_wake_time"] = self._predict_wake(recent_wake_times)

        return result

    @staticmethod
    def _predict_wake(wake_times: list[str]) -> str | None:
        """Average recent wake times to predict tomorrow's wake time."""
        if not wake_times:
            return None
        total_minutes = 0
        count = 0
        for t in wake_times:
            try:
                h, m = int(t[:2]), int(t[3:5])
                total_minutes += h * 60 + m
                count += 1
            except (ValueError, IndexError):
                continue
        if count == 0:
            return None
        avg = round(total_minutes / count)
        hour = avg // 60
        minute = avg % 60
        return _to_12hr(f"{hour:02d}:{minute:02d}")

    @staticmethod
    def _duration_min(start: str, end: str) -> float | None:
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            s = datetime.strptime(start[:19], fmt)
            e = datetime.strptime(end[:19], fmt)
            diff = (e - s).total_seconds() / 60
            return round(diff, 1) if diff > 0 else None
        except (ValueError, TypeError):
            return None
