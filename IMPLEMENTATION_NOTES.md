# PetKit K3 — Battery / Liquid Level / Backlight-during-Spray Implementation

## Overview
This document describes the reverse-engineering work and code changes made to
implement the three features listed under "In Development" in the README:

- Battery level reading
- Liquid (detergent) level monitoring
- Backlight operation during spraying

Source of truth: `filtered.log`, a btsnoop capture of the official PetKit
Android app talking to the K3 device over BLE.

## Method

1. Parsed `filtered.log` (btsnoop format, HCI UART/H4 datalink).
2. Reassembled fragmented ACL packets into complete L2CAP/ATT PDUs
   (fragments use the ACL "PB flag"; a naive per-packet parser gives
   corrupted data for any ATT payload split across >1 ACL packet).
3. Extracted all ATT Write Command / Handle Value Notification frames.
4. Cross-checked the frame structure against PetKit's official
   `pypetkitapi` library (`BLE_START_TRAME = [0xFA, 0xFC, 0xFD]`,
   `BLE_END_TRAME = [0xFB]`) to confirm the framing wasn't a guess.

## Protocol Findings

Frame format (write and notify payloads both use this):

```
FA FC FD | CMD(1) | DIR(1) | SEQ(1) | LEN_L LEN_H | PAYLOAD(LEN bytes) | FB
```

- `DIR`: `0x01` = request, `0x02` = response/event.
- `SEQ`: correlation id, echoed back by the device in its response.
- Responses/events arrive as **notifications on `0000aaa1`**, not by
  reading `0000aaa2` (which is write-only). The original code read
  `0000aaa2` after writing, which cannot return real ack data — this made
  the existing `resp == "00"` success checks effectively dead code (real
  acks are single-byte payload `0x01`, not `0x00`).

### Telemetry frames (`CMD=0xD3` query / `CMD=0xE6` spontaneous push)

Payload contains repeated 3-byte triplets `[channel_id, value, 0x7F]`.
In the capture:

| channel_id | value | inferred meaning |
|---|---|---|
| 2 | 68 | battery % |
| 3 | 52 | liquid/detergent % |
| 4 | 96 | unused/unknown |

All three values stayed constant across the whole capture (short session,
consistent with slow-changing battery/liquid levels), which is expected
and doesn't invalidate the mapping, but **the id→meaning mapping is
inferred, not confirmed against the PetKit app UI**. See Caveats below.

### Spray + Light sequencing evidence

The capture shows the app sending the `LIGHT` command immediately after the
`SPRAY` command (`dc` cmd, action byte `01`=spray, `02`=light). This is
direct evidence the "backlight during spraying" feature works by sending
both commands back-to-back, not via a special combined command.

## Code Changes

| File | Change |
|---|---|
| `custom_components/petkit_k3/const.py` | Added `NOTIFY_CHAR_UUID`, frame format constants (`FRAME_MAGIC`, `DIR_REQUEST/RESPONSE`), `STATUS_QUERY_CMD`, `STATUS_CMD`/`PUSH_STATUS_CMD`, `ACK_OK`, `BATTERY_CHANNEL_ID`/`LIQUID_CHANNEL_ID`, `STATUS_POLL_INTERVAL`. Added `"sensor"` to `PLATFORMS`. |
| `custom_components/petkit_k3/petkit_device.py` | Added `decode_frame()` / `decode_status_channels()`. Subscribes to `NOTIFY_CHAR_UUID` via `start_notify` on connect. `_write_command` now writes without response and awaits a per-`cmd` `asyncio.Future` resolved by the notification handler (with timeout), instead of doing a (broken) direct read. Fixed ack check from `"00"` to `"01"` (`ACK_OK`). Added `battery_level`/`liquid_level` attributes, `async_spray()` (spray then light), `async_query_status()`, `status_poll_loop()`. |
| `custom_components/petkit_k3/sensor.py` | **New file.** `PetkitK3BatterySensor` (device_class battery, %) and `PetkitK3LiquidLevelSensor` (%, mdi:spray-bottle), reading from controller state. |
| `custom_components/petkit_k3/button.py` | Spray button now calls `controller.async_spray()` (spray + auto-light) instead of just sending `SPRAY_CMD`; ack check fixed to `"01"`. |
| `custom_components/petkit_k3/light.py` | Ack check fixed to `"01"`. |
| `custom_components/petkit_k3/__init__.py` | Spawns `status_poll_loop()` task alongside `heartbeat_loop()`. |
| `README.md` | Moved the three features from "In Development" to supported functionality; documented the telemetry channel mapping and caveat in both RU/EN sections. |

## Caveats / Follow-ups

- **Channel mapping is unverified**: `id=2`→battery, `id=3`→liquid was
  inferred from one capture where both values were static. If the
  displayed percentages don't match the PetKit app, swap
  `BATTERY_CHANNEL_ID`/`LIQUID_CHANNEL_ID` in `const.py`, or capture a
  new btsnoop while draining the battery / removing liquid to confirm.
- **`SEQ` handling**: kept the existing pattern of hardcoded per-command
  `SEQ` bytes (as the original code did for spray/light) rather than a
  monotonically incrementing counter, since the device didn't appear to
  enforce strict ordering in the capture. Revisit if commands start
  getting rejected.
- The `channel_id=4` (value 96 in the capture) is decoded but currently
  unused — could be exposed as a diagnostic sensor once its meaning is
  known.
- No hardware-in-the-loop testing was done (no physical device
  available); all changes are grounded in the packet capture plus static
  syntax validation (`python3 -m py_compile`).
