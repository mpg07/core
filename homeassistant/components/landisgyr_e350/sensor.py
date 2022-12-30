"""Support for Dutch Smart Meter (also known as Smartmeter or P1 port)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

import async_timeout

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_SERIAL_ID, DEVICE_NAME_ELECTRICITY, DOMAIN
from .obis_references import ObisReferences
from .serial_power_meter import (
    PollingMeterConfiguration,
    PollingPowerMeter,
    PowerMeterError,
    UnitType,
)


@dataclass
class DSMRSensorEntityDescriptionMixin:
    """Mixin for required keys."""

    obis_reference: str


@dataclass
class DSMRSensorEntityDescription(
    SensorEntityDescription, DSMRSensorEntityDescriptionMixin
):
    """Represents an DSMR Sensor."""


SENSORS: tuple[DSMRSensorEntityDescription, ...] = (
    DSMRSensorEntityDescription(
        key="instantaneous_electrical_power",
        name="Power production",  # - means delivery, + means consumption
        obis_reference=ObisReferences.INSTANTANEOUS_POWER,
        device_class=SensorDeviceClass.POWER,
        force_update=True,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kW",
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_total",
        name="Energy consumption (total)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TOTAL,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_total",
        name="Energy production (total)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TOTAL,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_tariff_1",
        name="Energy consumption (tarif 1)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TARIFF_1,
        device_class=SensorDeviceClass.ENERGY,
        force_update=True,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_tariff_2",
        name="Energy consumption (tarif 2)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TARIFF_2,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_tariff_1",
        name="Energy production (tarif 1)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TARIFF_1,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_tariff_2",
        name="Energy production (tarif 2)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TARIFF_2,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
    ),
    DSMRSensorEntityDescription(
        key="power_failure_count",
        name="Power failure count",
        obis_reference=ObisReferences.POWER_FAIL_COUNT,
        entity_registry_enabled_default=False,
        icon="mdi:flash-off",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DSMRSensorEntityDescription(
        key="status_flags",
        name="Meter status flags",
        obis_reference=ObisReferences.STATUS_FLAGS,
        entity_registry_enabled_default=False,
        icon="mdi:flash-off",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DSMRSensorEntityDescription(
        key="error_code",
        name="Error code",
        obis_reference=ObisReferences.ERROR_CODE,
        entity_registry_enabled_default=False,
        icon="mdi:flash-off",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DSMRSensorEntityDescription(
        key="instantaneous_voltage_l1",
        name="Voltage phase L1",
        obis_reference=ObisReferences.INSTANTANEOUS_VOLTAGE_L1,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="V",
    ),
    DSMRSensorEntityDescription(
        key="instantaneous_voltage_l2",
        name="Voltage phase L2",
        obis_reference=ObisReferences.INSTANTANEOUS_VOLTAGE_L2,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="V",
    ),
    DSMRSensorEntityDescription(
        key="instantaneous_voltage_l3",
        name="Voltage phase L3",
        obis_reference=ObisReferences.INSTANTANEOUS_VOLTAGE_L3,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="V",
    ),
)


_LOGGER = logging.getLogger(__name__)


class PowerMeterCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, my_api: PollingPowerMeter):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=30),
        )
        self.my_api = my_api

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            async with async_timeout.timeout(10):
                return await self.my_api.read_once(self.hass.loop)
        except PowerMeterError as err:
            raise UpdateFailed(err) from err


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the DSMR sensor."""

    config = PollingMeterConfiguration()
    config.port = entry.data[CONF_PORT]

    api = PollingPowerMeter(config)

    coordinator = PowerMeterCoordinator(hass, api)

    entities = [DSMREntity(coordinator, description, entry) for description in SENSORS]
    async_add_entities(entities)


class DSMREntity(CoordinatorEntity, SensorEntity):
    """Entity reading values from DSMR telegram."""

    entity_description: DSMRSensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entity_description: DSMRSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize entity."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._entry = entry
        self.telegram: dict[str, tuple[str, UnitType]] = {}

        device_serial = entry.data[CONF_SERIAL_ID]
        device_name = DEVICE_NAME_ELECTRICITY
        if device_serial is None:
            device_serial = entry.entry_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_serial)},
            name=device_name,
        )
        self._attr_unique_id = f"{device_serial}_{entity_description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.telegram = self.coordinator.data
        if self.entity_description.obis_reference in self.coordinator.data:
            value = self.coordinator.data[self.entity_description.obis_reference]
            self._attr_native_value = value[0]
            self._attr_native_unit_of_measurement = value[1]
        else:
            self._attr_native_value = None
            self._attr_native_unit_of_measurement = (
                self.entity_description.native_unit_of_measurement
            )
        self.async_write_ha_state()
