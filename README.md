# Petkit Smart Spray Bluetooth Integration

<div align="center">
<img src="https://static.insales-cdn.com/images/products/1/6584/558168504/IMG_7256.JPG" alt="Petkit K3" width="300"/>
</div>

## Functionality:
Current version supports:
- ✨ Spray function (operates for 10 seconds, then automatically turns off)
- 💡 Light function (turns on for 10 seconds)
- 💡 Light automatically turns on during spraying
- 🔋 Battery level reading
- 💧 Liquid (detergent) level monitoring

### Device Initialization:
Two steps are required:
1. Initialization: `fafcfdd501000000fb`
2. Authentication: `fafcfd560101080000001d7eaf21ed20fb`

### Control UUID:
Main UUID for command writing:
- `0000aaa2-0000-1000-8000-00805f9b34fb`

### Available Services and Characteristics:
```
Service: 00001800-0000-1000-8000-00805f9b34fb
├── Characteristic: 00002a00-0000-1000-8000-00805f9b34fb [read, notify]
├── Characteristic: 00002a01-0000-1000-8000-00805f9b34fb [read]
└── Characteristic: 00002a04-0000-1000-8000-00805f9b34fb [read]

Service: 00001801-0000-1000-8000-00805f9b34fb
└── Characteristic: 00002a05-0000-1000-8000-00805f9b34fb [indicate]

Service: 0000aaa0-0000-1000-8000-00805f9b34fb
├── Characteristic: 0000aaa2-0000-1000-8000-00805f9b34fb [write-without-response, write]
└── Characteristic: 0000aaa1-0000-1000-8000-00805f9b34fb [read, notify]
```

### Telemetry (battery/liquid):
The device periodically sends status on the `0000aaa1` notify
characteristic. The status frame (`CMD=0xD3`, also arrives as push
`CMD=0xE6`) contains `[id, value, 0x7f]` triplets. Analysis of the
`filtered.log` capture identified the mapping: `id=2` → battery (%),
`id=3` → liquid level (%). Value `id=4` is currently unused.

> ⚠️ The id mapping was inferred empirically from a single traffic
> capture where the readings stayed constant. If the percentages don't
> match the PetKit app, adjust `BATTERY_CHANNEL_ID`/`LIQUID_CHANNEL_ID`
> in `const.py`.

Special thanks to @Jezza34000 for his library, it helped in the development of this integration.