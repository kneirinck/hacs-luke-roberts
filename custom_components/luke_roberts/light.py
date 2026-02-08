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
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    LightEntity,
    LightEntityFeature,
    ColorMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
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
    if not ble_device:
        raise ConfigEntryNotReady(
            f"Unable to find device with address {entry.unique_id}, ensure it's powered on"
        )
    async_add_entities([LukeRobertsLuvoBleLight(ble_device)], update_before_add=True)


class LukeRobertsLuvoBleLight(LightEntity):
    """Representation of a Luke Roberts Luvo BLE Light."""

    EFFECT_ID_DEFAULT = 255
    EFFECT_ID_OFF = 0

    # Kelvin range for the downlight (from API docs)
    MIN_KELVIN = 2700
    MAX_KELVIN = 4000

    _attr_supported_features = LightEntityFeature(LightEntityFeature.EFFECT)
    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS, ColorMode.COLOR_TEMP}
    _attr_min_color_temp_kelvin = 2700
    _attr_max_color_temp_kelvin = 4000

    def __init__(self, ble_device: BLEDevice) -> None:
        """Initialize an LukeRobertsLuvoBleLight."""
        self._state = None
        self._ble_device = ble_device
        self._device: BleakClient | None = None
        self._attr_unique_id = ble_device.address

        self._effect_map: dict[str, int] = {}
        self._effect = None

        # Brightness (0-255 for HA, we'll convert to 0-100 for API)
        self._brightness: int = 255
        # HS color for uplight (top) - hue 0-360, saturation 0-100
        self._hs_color: tuple[float, float] = (0.0, 0.0)
        # Color temperature in Kelvin for downlight (bottom)
        self._color_temp_kelvin: int = 3350

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
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation color value [float, float]."""
        return self._hs_color

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._color_temp_kelvin

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        _LOGGER.info(
            "Current effect %s %s", self._effect, self._effect_map.get(self._effect)
        )
        return self._effect_map.get(self._effect) != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        _LOGGER.info("Turn on called with kwargs: %s", kwargs)

        # Handle effect selection
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs.get(ATTR_EFFECT)
            effect_id = self._effect_map.get(effect_name)
            if effect_id is None:
                return

            if await self._set_effect(effect_id):
                self._effect = effect_name
            return

        # Handle brightness
        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]
            # Convert 0-255 to 0-100 for the API
            brightness_percent = int((self._brightness / 255) * 100)
            await self._set_brightness(brightness_percent)

        # Handle HS color (uplight/top)
        if ATTR_HS_COLOR in kwargs:
            self._hs_color = kwargs[ATTR_HS_COLOR]
            self._attr_color_mode = ColorMode.HS
            await self._set_uplight_color(
                hue=self._hs_color[0],
                saturation=self._hs_color[1],
                brightness=self._brightness
            )

        # Handle color temperature (downlight/bottom)
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            # Clamp to valid range
            self._color_temp_kelvin = max(
                self.MIN_KELVIN, min(self.MAX_KELVIN, self._color_temp_kelvin)
            )
            self._attr_color_mode = ColorMode.COLOR_TEMP
            await self._set_downlight_color_temp(
                kelvin=self._color_temp_kelvin,
                brightness=self._brightness
            )

        # If no specific attributes, just turn on with default scene
        if not any(k in kwargs for k in [ATTR_EFFECT, ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_COLOR_TEMP_KELVIN]):
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

    async def _set_brightness(self, brightness_percent: int) -> bool:
        """Set the brightness of the lamp (0-100%)."""
        _LOGGER.info("Setting brightness to %d%%", brightness_percent)
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )
        # Command: A0 01 03 PP (Modify Brightness)
        # PP = brightness in percent 0-100
        command = bytes([0xA0, 0x01, 0x03, brightness_percent])
        response = await self._send_and_await_response(data=command)
        return response[0] == 0x00 if response else False

    async def _set_uplight_color(self, hue: float, saturation: float, brightness: int) -> bool:
        """Set the uplight (top) color using HSB.

        Args:
            hue: 0-360 degrees
            saturation: 0-100 percent
            brightness: 0-255 (HA brightness)
        """
        _LOGGER.info("Setting uplight color: hue=%f, sat=%f, bright=%d", hue, saturation, brightness)
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )

        # Convert hue from 0-360 to 0-65535
        hue_int = int((hue / 360) * 65535)
        hue_bytes = hue_int.to_bytes(2, byteorder='big')

        # Convert saturation from 0-100 to 0-255
        saturation_byte = int((saturation / 100) * 255)

        # Convert brightness from 0-255 HA to 0-255 API
        brightness_byte = brightness

        # Duration: 0 for infinite
        duration_bytes = (0).to_bytes(2, byteorder='big')

        # Command: A0 01 02 XX DD DD SS HH HH BB
        # XX = 0x01 (uplight flag)
        # DD DD = duration in ms
        # SS = saturation 0-255
        # HH HH = hue 0-65535
        # BB = brightness 0-255
        command = bytes([
            0xA0, 0x01, 0x02, 0x01,  # Prefix, version, opcode, flags
            duration_bytes[0], duration_bytes[1],  # Duration
            saturation_byte,  # Saturation
            hue_bytes[0], hue_bytes[1],  # Hue
            brightness_byte  # Brightness
        ])

        response = await self._send_and_await_response(data=command)
        return response[0] == 0x00 if response else False

    async def _set_downlight_color_temp(self, kelvin: int, brightness: int) -> bool:
        """Set the downlight (bottom) color temperature.

        Args:
            kelvin: 2700-4000 Kelvin
            brightness: 0-255 (HA brightness)
        """
        _LOGGER.info("Setting downlight color temp: kelvin=%d, bright=%d", kelvin, brightness)
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )

        # Clamp kelvin to valid range
        kelvin = max(self.MIN_KELVIN, min(self.MAX_KELVIN, kelvin))
        kelvin_bytes = kelvin.to_bytes(2, byteorder='big')

        # Convert brightness from 0-255 HA to 0-255 API
        brightness_byte = brightness

        # Duration: 0 for infinite
        duration_bytes = (0).to_bytes(2, byteorder='big')

        # Command: A0 01 02 XX DD DD KK KK BB
        # XX = 0x02 (downlight flag)
        # DD DD = duration in ms
        # KK KK = kelvin 2700-4000
        # BB = brightness 0-255
        command = bytes([
            0xA0, 0x01, 0x02, 0x02,  # Prefix, version, opcode, flags
            duration_bytes[0], duration_bytes[1],  # Duration
            kelvin_bytes[0], kelvin_bytes[1],  # Kelvin
            brightness_byte  # Brightness
        ])

        response = await self._send_and_await_response(data=command)
        return response[0] == 0x00 if response else False

    async def _set_both_lights(
        self,
        hue: float,
        saturation: float,
        uplight_brightness: int,
        kelvin: int,
        downlight_brightness: int
    ) -> bool:
        """Set both uplight and downlight in a single BLE command.

        Args:
            hue: 0-360 degrees (for uplight)
            saturation: 0-100 percent (for uplight)
            uplight_brightness: 0-255 (for uplight)
            kelvin: 2700-4000 Kelvin (for downlight)
            downlight_brightness: 0-255 (for downlight)
        """
        _LOGGER.info(
            "Setting both lights: hue=%f, sat=%f, up_bright=%d, kelvin=%d, down_bright=%d",
            hue, saturation, uplight_brightness, kelvin, downlight_brightness
        )
        self._device = await bleak_retry_connector.establish_connection(
            BleakClient, self._ble_device, self.unique_id
        )

        # Uplight parameters
        hue_int = int((hue / 360) * 65535)
        hue_bytes = hue_int.to_bytes(2, byteorder='big')
        saturation_byte = int((saturation / 100) * 255)

        # Downlight parameters
        kelvin = max(self.MIN_KELVIN, min(self.MAX_KELVIN, kelvin))
        kelvin_bytes = kelvin.to_bytes(2, byteorder='big')

        # Duration: 0 for infinite
        duration_bytes = (0).to_bytes(2, byteorder='big')

        # Command: A0 01 02 03 DD DD SS HH HH BB KK KK BB
        # Flag 0x03 = uplight (0x01) + downlight (0x02)
        # First sub-packet: uplight (SS HH HH BB)
        # Second sub-packet: downlight (KK KK BB)
        command = bytes([
            0xA0, 0x01, 0x02, 0x03,  # Prefix, version, opcode, flags (both)
            duration_bytes[0], duration_bytes[1],  # Duration
            # Uplight sub-packet
            saturation_byte,  # Saturation
            hue_bytes[0], hue_bytes[1],  # Hue
            uplight_brightness,  # Uplight brightness
            # Downlight sub-packet
            kelvin_bytes[0], kelvin_bytes[1],  # Kelvin
            downlight_brightness  # Downlight brightness
        ])

        response = await self._send_and_await_response(data=command)
        return response[0] == 0x00 if response else False
