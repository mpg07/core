"""Support for Dutch Smart Meter (also known as Smartmeter or P1 port)."""
from __future__ import annotations

import asyncio
from asyncio import BaseTransport, CancelledError
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

import serial
from serial_asyncio import create_serial_connection

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import EventType, StateType
from homeassistant.util import Throttle

from .const import (
    CONF_SERIAL_ID,
    CONF_TIME_BETWEEN_UPDATE,
    DATA_TASK,
    DEFAULT_TIME_BETWEEN_UPDATE,
    DEVICE_NAME_ELECTRICITY,
    DOMAIN,
    LOGGER,
)
from .obis_references import ObisReferences


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
        key="current_electricity_usage",
        name="Power consumption",
        # obis_reference=obis_references.CURRENT_ELECTRICITY_USAGE,
        obis_reference="",
        device_class=SensorDeviceClass.POWER,
        force_update=True,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key="current_electricity_delivery",
        name="Power production",
        # obis_reference=obis_references.CURRENT_ELECTRICITY_DELIVERY,
        obis_reference="",
        device_class=SensorDeviceClass.POWER,
        force_update=True,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_total",
        name="Energy consumption (total)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TOTAL,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_total",
        name="Energy production (total)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TOTAL,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_tariff_1",
        name="Energy consumption (tarif 1)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TARIFF_1,
        device_class=SensorDeviceClass.ENERGY,
        force_update=True,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key="electricity_used_tariff_2",
        name="Energy consumption (tarif 2)",
        obis_reference=ObisReferences.ELECTRICITY_USED_TARIFF_2,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_tariff_1",
        name="Energy production (tarif 1)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TARIFF_1,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key="electricity_delivered_tariff_2",
        name="Energy production (tarif 2)",
        obis_reference=ObisReferences.ELECTRICITY_DELIVERED_TARIFF_2,
        force_update=True,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
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
        obis_reference=ObisReferences.POWER_FAIL_COUNT,
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
    ),
    DSMRSensorEntityDescription(
        key="instantaneous_voltage_l2",
        name="Voltage phase L2",
        obis_reference=ObisReferences.INSTANTANEOUS_VOLTAGE_L2,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DSMRSensorEntityDescription(
        key="instantaneous_voltage_l3",
        name="Voltage phase L3",
        obis_reference=ObisReferences.INSTANTANEOUS_VOLTAGE_L3,
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class OutputProtocol(asyncio.Protocol):
    """Test class."""

    transport: BaseTransport

    def connection_made(self, transport):
        """Handle connected."""
        self.transport = transport
        print("port opened", transport)
        transport.serial.rts = False  # You can manipulate Serial object via transport
        transport.write(b"Hello, World!\n")  # Write serial data via transport

    def data_received(self, data):
        """Handle connected."""
        print("data received", repr(data))
        if b"\n" in data:
            self.transport.close()

    def connection_lost(self, exc):
        """Handle disconnected."""
        print("port closed")
        self.transport.loop.stop()

    def pause_writing(self):
        """Handle pasue writing."""
        print("pause writing")
        print(self.transport.get_write_buffer_size())

    def resume_writing(self):
        """Handle resme writing."""
        print(self.transport.get_write_buffer_size())
        print("resume writing")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the DSMR sensor."""
    entities = [DSMREntity(description, entry) for description in SENSORS]
    async_add_entities(entities)

    min_time_between_updates = timedelta(
        seconds=entry.options.get(CONF_TIME_BETWEEN_UPDATE, DEFAULT_TIME_BETWEEN_UPDATE)
    )

    @Throttle(min_time_between_updates)
    def update_entities_telegram(telegram: dict[str, str]) -> None:
        """Update entities with latest telegram and trigger state update."""
        # Make all device entities aware of new telegram
        for entity in entities:
            entity.update_data(telegram)

    # Creates an asyncio.Protocol factory for reading DSMR telegrams from
    # serial and calls update_entities_telegram to update entities on arrival
    reader_factory = partial(
        create_serial_connection,
        loop=hass.loop,
        protocol_factory=OutputProtocol,
        # entry.data[CONF_PORT],
        # update_entities_telegram,
    )

    async def connect_and_reconnect() -> None:
        """Connect to DSMR and keep reconnecting until Home Assistant stops."""
        stop_listener = None
        transport = None
        protocol = None

        while hass.state == CoreState.not_running or hass.is_running:
            # Start DSMR asyncio.Protocol reader
            try:
                transport, protocol = await hass.loop.create_task(reader_factory())

                if transport:
                    # Register listener to close transport on HA shutdown
                    @callback
                    def close_transport(_event: EventType) -> None:
                        """Close the transport on HA shutdown."""
                        if not transport:
                            return
                        transport.close()

                    stop_listener = hass.bus.async_listen_once(
                        EVENT_HOMEASSISTANT_STOP, close_transport
                    )

                    # Wait for reader to close
                    await protocol.wait_closed()

                    # Unexpected disconnect
                    if hass.state == CoreState.not_running or hass.is_running:
                        stop_listener()

                transport = None
                protocol = None

                # Reflect disconnect state in devices state by setting an
                # empty telegram resulting in `unknown` states
                update_entities_telegram({})

                # throttle reconnect attempts
                await asyncio.sleep(
                    entry.data.get(
                        CONF_TIME_BETWEEN_UPDATE, DEFAULT_TIME_BETWEEN_UPDATE
                    )
                )

            except (serial.serialutil.SerialException, OSError):
                # Log any error while establishing connection and drop to retry
                # connection wait
                LOGGER.exception("Error connecting to DSMR")
                transport = None
                protocol = None

                # throttle reconnect attempts
                await asyncio.sleep(
                    entry.data.get(
                        CONF_TIME_BETWEEN_UPDATE, DEFAULT_TIME_BETWEEN_UPDATE
                    )
                )
            except CancelledError:
                if stop_listener and (
                    hass.state == CoreState.not_running or hass.is_running
                ):
                    stop_listener()  # pylint: disable=not-callable

                if transport:
                    transport.close()

                if protocol:
                    await protocol.wait_closed()

                return

    # Can't be hass.async_add_job because job runs forever
    task = asyncio.create_task(connect_and_reconnect())

    @callback
    async def _async_stop(_: Event) -> None:
        task.cancel()

    # Make sure task is cancelled on shutdown (or tests complete)
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )

    # Save the task to be able to cancel it when unloading
    hass.data[DOMAIN][entry.entry_id][DATA_TASK] = task


class DSMREntity(SensorEntity):
    """Entity reading values from DSMR telegram."""

    entity_description: DSMRSensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entity_description: DSMRSensorEntityDescription, entry: ConfigEntry
    ) -> None:
        """Initialize entity."""
        self.entity_description = entity_description
        self._entry = entry
        self.telegram: dict[str, str] = {}

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
    def update_data(self, telegram: dict[str, str]) -> None:
        """Update data."""
        self.telegram = telegram
        if self.hass and self.entity_description.obis_reference in self.telegram:
            self.async_write_ha_state()

    def get_dsmr_object_attr(self, attribute: str) -> str | None:
        """Read attribute from last received telegram for this DSMR object."""
        # Make sure telegram contains an object for this entities obis
        if self.entity_description.obis_reference not in self.telegram:
            return None

        # Get the attribute value if the object has it
        dsmr_object = self.telegram[self.entity_description.obis_reference]
        attr: str | None = getattr(dsmr_object, attribute)
        return attr

    @property
    def native_value(self) -> StateType:
        """Return the state of sensor, if available, translate if needed."""
        value: StateType
        if (value := self.get_dsmr_object_attr("value")) is None:
            return None

        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement of this entity, if any."""
        unit_of_measurement = self.get_dsmr_object_attr("unit")
        return unit_of_measurement
