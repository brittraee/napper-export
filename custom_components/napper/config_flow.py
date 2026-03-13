"""Config flow for the Napper integration."""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import API_BASE, CONF_API_TOKEN, CONF_BABY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): str,
        vol.Required(CONF_BABY_ID): str,
    }
)


def _validate_credentials(token: str, baby_id: str) -> str | None:
    """Validate the API token. Returns baby name on success, None on failure."""
    url = f"{API_BASE}/babies"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        items = data.get("items", [])
        for baby in items:
            if baby.get("id") == baby_id:
                return baby.get("name", "Baby")
        return items[0].get("name", "Baby") if items else "Baby"
    except (HTTPError, Exception):
        return None


class NapperConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Napper."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_API_TOKEN]
            baby_id = user_input[CONF_BABY_ID]

            baby_name = await self.hass.async_add_executor_job(
                _validate_credentials, token, baby_id
            )

            if baby_name is not None:
                await self.async_set_unique_id(baby_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Napper - {baby_name}",
                    data=user_input,
                )
            errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
