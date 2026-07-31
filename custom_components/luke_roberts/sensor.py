"""Platform for sensor integration."""

from __future__ import annotations

import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
import bleak_retry_connector

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .light import LukeRobertsLuvoBleLight

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Luke Roberts diagnostic sensor."""
    ble_device = bluetooth.async_ble_device_from_address(
        hass, entry.unique_id.upper(), True
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Unable to find device with address {entry.unique_id}, ensure it's powered on"
        )

    async_add_entities([LukeRobertsApiVersionSensor(ble_device)])


class LukeRobertsApiVersionSensor(SensorEntity):
    """Sensor showing the lamp's API version."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _unavailable_logged: bool = False

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialize the sensor."""
        self._ble_device = ble_device
        self._api_version: int | None = None

        self._attr_unique_id = f"{ble_device.address}_api_version"
        self._attr_name = "API Version"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ble_device.address)},
            manufacturer="Luke Roberts",
            model="Luvo BLE Light",
            connections={(dr.CONNECTION_BLUETOOTH, ble_device.address)},
        )

    @property
    def native_value(self) -> int | None:
        """Return the API version."""
        return self._api_version

    async def async_update(self) -> None:
        """Fetch API version from device."""
        _LOGGER.info("Fetching API version")

        device = None
        try:
            device = await bleak_retry_connector.establish_connection(
                BleakClient, self._ble_device, self._attr_unique_id
            )
        except bleak_retry_connector.BleakError as ex:
            self._attr_available = False
            if not self._unavailable_logged:
                _LOGGER.info("API version sensor is unavailable: %s", ex)
                self._unavailable_logged = True
        else:
            self._attr_available = True

            # Send Ping V2 command and await response
            # Command: A0 02 00 (Ping V2)
            command = bytearray([0xA0, 0x02, 0x00])
            received_data = await LukeRobertsLuvoBleLight.send_and_await_response(device, command)

            # Response: 00 VV (status, version)
            if len(received_data) >= 2 and received_data[0] == 0x00:
                self._api_version = received_data[1]
                _LOGGER.info("API version: %d", self._api_version)
            else:
                _LOGGER.warning("Unexpected ping response: %s", received_data.hex())

            if self._unavailable_logged:
                _LOGGER.info("API version sensor is back online")
                self._unavailable_logged = False
        finally:
            if device:
                await device.disconnect()
