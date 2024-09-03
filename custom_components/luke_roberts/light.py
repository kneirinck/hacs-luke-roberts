"""Platform for light integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient, BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import bleak_retry_connector

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.light import (
    ATTR_EFFECT,
    LightEntity,
    LightEntityFeature,
    ColorMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import API_UUID, DOMAIN, SCENE_UUID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Luke Roberts Luvo BLE Light."""
    ble_device = bluetooth.async_ble_device_from_address(
        hass, entry.unique_id.upper(), True
    )
    async_add_entities([LukeRobertsLuvoBleLight(ble_device)])


class LukeRobertsLuvoBleLight(LightEntity):
    """Representation of a Luke Roberts Luvo BLE Light."""

    EFFECT_ID_DEFAULT = 255
    EFFECT_ID_OFF = 0

    _attr_supported_features = LightEntityFeature(LightEntityFeature.EFFECT)
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialize an LukeRobertsLuvoBleLight."""
        self._state = None
        self._ble_device = ble_device
        self._device: BleakClient | None = None
        self._attr_unique_id = ble_device.address

        self._effect_map: dict[str, int] = {}
        self._effect = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Luke Roberts",
            model="Luvo BLE Light",
            connections={(dr.CONNECTION_BLUETOOTH, ble_device.address)},
        )

    @property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return list(self._effect_map.keys())

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        _LOGGER.info(
            "Current effect %s %s", self._effect, self._effect_map.get(self._effect)
        )
        return self._effect_map.get(self._effect) != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""

        if ATTR_EFFECT in kwargs:
            effect_name = kwargs.get(ATTR_EFFECT)
            effect_id = self._effect_map.get(effect_name)
            if effect_id is None:
                return

            if await self._set_effect(effect_id):
                self._effect = effect_name
        else:
            await self._set_effect(self.EFFECT_ID_DEFAULT)


    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""

        if await self._set_effect(self.EFFECT_ID_OFF):
            self._effect = self._get_effect_name_by_id(self.EFFECT_ID_OFF)

    async def async_update(self) -> None:
        """Fetch new state data for this light.

        This is the only method that should fetch new data for Home Assistant.
        """
        _LOGGER.info("FETCHING DATA")
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )
        _LOGGER.info("GOT CONNECTION")
        if not self._effect_map:
            await self._update_effect_list()
        await self._update_effect()
        _LOGGER.info("DONE FETCHING DATA")

    async def _update_effect_list(self) -> None:
        effect_map = {}
        scene_id = 0
        scene_data = await self._get_scene(scene_id)
        while True:
            if scene_data[0] != 0x00:
                _LOGGER.warning("Failed to retrieve scene data for %d", scene_id)
                break

            effect_map[scene_data[3:].decode()] = scene_id

            scene_id = scene_data[2]
            if scene_id == 0xFF:
                # No more scenes, we're done
                break
            scene_data = await self._get_scene(scene_id)
        self._effect_map = effect_map

    async def _get_scene(self, id: int) -> bytearray:
        _LOGGER.info("Getting scene %d", id)
        return await self._send_and_await_response(data=b"\xa0\x01\x01" + bytes([id]))

    async def _send_and_await_response(self, data: bytearray) -> bytearray:
        data_received_flag = asyncio.Event()
        received_data = bytearray()

        def handle_notification(_: BleakGATTCharacteristic, data: bytearray):
            nonlocal received_data
            received_data = data
            data_received_flag.set()

        await self._device.start_notify(API_UUID, handle_notification)
        await self._device.write_gatt_char(API_UUID, data=data, response=True)
        await data_received_flag.wait()
        await self._device.stop_notify(API_UUID)
        return received_data

    async def _update_effect(self) -> None:
        current_scene_id_byte_array = await self._device.read_gatt_char(SCENE_UUID)
        current_scene_id = int.from_bytes(current_scene_id_byte_array)
        _LOGGER.info("Current scene id %s", current_scene_id)
        self._effect = self._get_effect_name_by_id(current_scene_id)
        _LOGGER.info("Current scene name %s", self._effect)

    async def _set_effect(self, effect_id: int) -> bool:
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )
        response = await self._send_and_await_response(
            data=b"\xa0\x02\x05" + bytes([effect_id])
        )
        return response == 0x00

    def _get_effect_name_by_id(self, effect_id: int) -> str | None:
        for name, id in self._effect_map.items():
            if id == effect_id:
                return name
        return None
