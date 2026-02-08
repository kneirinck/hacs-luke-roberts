"""The Luke Roberts Luvo BLE integration."""

from __future__ import annotations

import logging
import voluptuous as vol

from bleak import BleakClient
from bleak.backends.device import BLEDevice
import bleak_retry_connector

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN, API_UUID

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.BUTTON, Platform.SENSOR]

SERVICE_ADJUST_BRIGHTNESS = "adjust_brightness"
ATTR_DELTA = "delta"

SERVICE_ADJUST_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required(ATTR_DELTA): vol.All(
            vol.Coerce(int), vol.Range(min=-100, max=100)
        ),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Luke Roberts Luvo BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data

    ble_device = bluetooth.async_ble_device_from_address(
        hass, entry.unique_id.upper(), True
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Unable to find device with address {entry.unique_id}, ensure it's powered on"
        )

    # Store BLE device for service calls
    hass.data[DOMAIN][entry.entry_id] = {"ble_device": ble_device}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_adjust_brightness(call: ServiceCall) -> None:
        """Handle the adjust_brightness service call."""
        entity_ids = call.data[ATTR_ENTITY_ID]
        delta = call.data[ATTR_DELTA]

        entity_reg = er.async_get(hass)

        for entity_id in entity_ids:
            entity_entry = entity_reg.async_get(entity_id)
            if entity_entry is None:
                _LOGGER.warning("Entity %s not found", entity_id)
                continue

            # Get the BLE device from config entry
            config_entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
            if config_entry is None:
                continue

            ble_device = bluetooth.async_ble_device_from_address(
                hass, config_entry.unique_id.upper(), True
            )
            if ble_device is None:
                _LOGGER.warning("BLE device not found for %s", entity_id)
                continue

            await _adjust_brightness(ble_device, delta)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADJUST_BRIGHTNESS,
        handle_adjust_brightness,
        schema=SERVICE_ADJUST_BRIGHTNESS_SCHEMA,
    )

    return True


async def _adjust_brightness(ble_device: BLEDevice, delta: int) -> None:
    """Adjust brightness relatively using command 08."""
    _LOGGER.info("Adjusting brightness by %d%%", delta)

    device = await bleak_retry_connector.establish_connection(
        BleakClient, ble_device, ble_device.address
    )

    try:
        # Command: A0 02 08 PP (Relative Brightness)
        # PP = signed int8 (-100 to +100)
        delta_byte = delta & 0xFF  # Convert to unsigned byte representation
        command = bytes([0xA0, 0x02, 0x08, delta_byte])
        await device.write_gatt_char(API_UUID, data=command, response=True)
    finally:
        await device.disconnect()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    # Unregister service if no more entries
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_ADJUST_BRIGHTNESS)

    return unload_ok
