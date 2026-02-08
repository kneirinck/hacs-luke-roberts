"""Platform for button integration."""

from __future__ import annotations

import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
import bleak_retry_connector

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import API_UUID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Luke Roberts scene buttons."""
    ble_device = bluetooth.async_ble_device_from_address(
        hass, entry.unique_id.upper(), True
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Unable to find device with address {entry.unique_id}, ensure it's powered on"
        )
    
    async_add_entities([
        LukeRobertsSceneButton(ble_device, "brighter"),
        LukeRobertsSceneButton(ble_device, "dimmer"),
    ])


class LukeRobertsSceneButton(ButtonEntity):
    """Button to cycle to next brighter or dimmer scene."""

    def __init__(self, ble_device: BLEDevice, direction: str) -> None:
        """Initialize the button."""
        self._ble_device = ble_device
        self._direction = direction
        
        # Direction: 0x01 for brighter, 0xFF (-1 signed) for dimmer
        self._direction_byte = 0x01 if direction == "brighter" else 0xFF
        
        self._attr_unique_id = f"{ble_device.address}_{direction}_scene"
        self._attr_name = f"Next {'Brighter' if direction == 'brighter' else 'Dimmer'} Scene"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ble_device.address)},
            manufacturer="Luke Roberts",
            model="Luvo BLE Light",
            connections={(dr.CONNECTION_BLUETOOTH, ble_device.address)},
        )

    async def async_press(self) -> None:
        """Handle button press - cycle to next scene."""
        _LOGGER.info("Pressing %s scene button", self._direction)
        
        device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self._attr_unique_id
        )
        
        try:
            # Command: A0 02 06 DD (Next Scene by Brightness)
            # DD = 0x01 for brighter, 0xFF for dimmer
            command = bytes([0xA0, 0x02, 0x06, self._direction_byte])
            await device.write_gatt_char(API_UUID, data=command, response=True)
        finally:
            await device.disconnect()
