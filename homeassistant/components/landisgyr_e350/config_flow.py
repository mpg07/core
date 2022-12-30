"""Config flow for DSMR integration."""
from __future__ import annotations

import os
from typing import Any

import serial
import serial.tools.list_ports
import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_SERIAL_ID, DOMAIN

CONF_MANUAL_PATH = "Enter Manually"


class E350ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """E350 config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step when user initializes a integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_selection = user_input[CONF_PORT]
            if user_selection == CONF_MANUAL_PATH:
                return await self.async_step_setup_serial_manual_path()
            dev_path = await self.hass.async_add_executor_job(
                get_serial_by_id, user_selection
            )

            validate_data = {
                CONF_PORT: dev_path,
                CONF_SERIAL_ID: "0000",
            }

            data = await self.async_validate_connection(validate_data, errors)
            if not errors:
                return self.async_create_entry(title=data[CONF_PORT], data=data)

        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        list_of_ports = {
            port.device: f"{port}, s/n: {port.serial_number or 'n/a'}"
            + (f" - {port.manufacturer}" if port.manufacturer else "")
            for port in ports
        }
        list_of_ports[CONF_MANUAL_PATH] = CONF_MANUAL_PATH

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT): vol.In(list_of_ports),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_setup_serial_manual_path(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select path manually."""
        if user_input is not None:
            validate_data = {
                CONF_PORT: user_input[CONF_PORT],
                CONF_SERIAL_ID: "0000",
            }

            errors: dict[str, str] = {}
            data = await self.async_validate_connection(validate_data, errors)
            if not errors:
                return self.async_create_entry(title=data[CONF_PORT], data=data)

        schema = vol.Schema({vol.Required(CONF_PORT): str})
        return self.async_show_form(
            step_id="setup_serial_manual_path",
            data_schema=schema,
        )

    async def async_validate_connection(self, data, errors) -> dict[str, Any]:
        """Verify input values."""

        return data


def get_serial_by_id(dev_path: str) -> str:
    """Return a /dev/serial/by-id match for given device if available."""
    by_id = "/dev/serial/by-id"
    if not os.path.isdir(by_id):
        return dev_path

    for path in (entry.path for entry in os.scandir(by_id) if entry.is_symlink()):
        if os.path.realpath(path) == dev_path:
            return path
    return dev_path


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class CannotCommunicate(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
