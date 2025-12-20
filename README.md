# Luke Roberts HACS Integration

Home Assistant Custom Component for controlling Luke Roberts smart lamps via Bluetooth LE.

## Features

- **Light Control**
  - On/Off switching via scenes
  - Brightness slider (0-100%)
  - RGB color picker for uplight (top light)
  - Color temperature slider for downlight (bottom light, 2700K-4000K)
  - Scene/effect selection

- **Scene Navigation**
  - Button entities to cycle through scenes by brightness
  - "Next Brighter Scene" / "Next Dimmer Scene"

- **Services**
  - `luke_roberts.adjust_brightness` - Relative brightness adjustment for automations

- **Diagnostics**
  - API version sensor

## Installation

1. Copy the `custom_components/luke_roberts` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services → Add Integration → Luke Roberts

## Sources & References

### Official Documentation

- **Luke Roberts Lamp Control API v1.6** (2021-05-18)
  - BLE protocol specification for controlling Luke Roberts smart lamps
  - Defines GATT service/characteristic UUIDs
  - Command structure and response codes

### Code References

Parts of this integration were inspired by or adapted from:

- **[pyLukeRoberts](https://github.com/tpulatha/pyLukeRoberts)** - Python library for Luke Roberts Bluetooth API
  - HSB color conversion utilities
  - BLE command structure examples
  - Scene query implementation patterns

### BLE Protocol Summary

| Command | Opcode | Description |
|---------|--------|-------------|
| Ping | `A0 02 00` | Test connection, get API version |
| Query Scene | `A0 01 01 II` | Get scene name by ID |
| Immediate Light | `A0 01 02 XX ...` | Set uplight/downlight colors |
| Modify Brightness | `A0 01 03 PP` | Set brightness (0-100%) |
| Select Scene | `A0 02 05 II` | Activate a scene |
| Next Scene | `A0 02 06 DD` | Cycle scenes by brightness |
| Relative Brightness | `A0 02 08 PP` | Adjust brightness relatively |

### GATT UUIDs

```
Service:        44092840-0567-11E6-B862-0002A5D5C51B
API Endpoint:   44092842-0567-11E6-B862-0002A5D5C51B
Current Scene:  44092844-0567-11E6-B862-0002A5D5C51B
```

## License

This project is provided as-is for personal use with Luke Roberts smart lamps.

## Acknowledgments

- [Luke Roberts](https://luke-roberts.com/) for the smart lamp and API documentation
- [pyLukeRoberts](https://github.com/tpulatha/pyLukeRoberts) by @tpulatha for the Python BLE implementation reference
