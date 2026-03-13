"""Config flow for Hildebrand Glow integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant import config_entries, core

from .const import APP_ID, DOMAIN  # pylint:disable=unused-import
from .glow import CannotConnect, Glow, InvalidAuth

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({"username": str, "password": str})


def config_object(data: dict, glow: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a ConfigEntity with authentication data and a temporary token."""
    return {
        "name": glow["name"],
        "username": data["username"],
        "password": data["password"],
        "token": glow["token"],
        "token_exp": glow["exp"],
    }


async def validate_input(hass: core.HomeAssistant, data: dict) -> Dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    glow = Glow(APP_ID, data["username"], data["password"])

    auth_data: Dict[str, Any] = await hass.async_add_executor_job(glow.authenticate)

    # Return some info we want to store in the config entry.
    return config_object(data, auth_data)


class DomainConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hildebrand Glow."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.SOURCE_USER

    async def _validate_and_get_info(self, user_input: dict) -> tuple[Dict[str, Any] | None, dict]:
        """Validate user input and return (info, errors)."""
        errors: dict = {}
        try:
            info = await validate_input(self.hass, user_input)
            return info, errors
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        return None, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            info, errors = await self._validate_and_get_info(user_input)
            if info is not None:
                return self.async_create_entry(title=info["name"], data=info)

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle re-authentication with the same credentials."""
        errors = {}
        if user_input is not None:
            self._abort_if_unique_id_mismatch()
            info, errors = await self._validate_and_get_info(user_input)
            if info is not None:
                return self.async_update_reload_and_abort(
                    entry=self._get_reauth_entry(),
                    data_updates=info,
                )

        return self.async_show_form(
            step_id="reauth",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle the reconfiguration step."""
        errors = {}
        if user_input is not None:
            self._abort_if_unique_id_mismatch()
            info, errors = await self._validate_and_get_info(user_input)
            if info is not None:
                return self.async_update_reload_and_abort(
                    entry=self._get_reconfigure_entry(),
                    data_updates=info,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )
