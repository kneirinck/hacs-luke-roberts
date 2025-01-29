"""The Luke Roberts Luvo BLE integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

PLATFORMS: list[Platform] = [Platform.LIGHT]


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
