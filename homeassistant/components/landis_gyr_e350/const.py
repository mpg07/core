"""Constants for the Landis+Gyr E350 integration."""
from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "landis_gyr_e350"

LOGGER = logging.getLogger(__package__)

PLATFORMS = [Platform.SENSOR]
CONF_PRECISION = "precision"
CONF_TIME_BETWEEN_UPDATE = "time_between_update"

CONF_SERIAL_ID = "serial_id"

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_PRECISION = 3
DEFAULT_TIME_BETWEEN_UPDATE = 30

DATA_TASK = "task"

DEVICE_NAME_ELECTRICITY = "Electricity Meter"
