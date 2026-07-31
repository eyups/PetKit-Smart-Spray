# petkit_device.py
import asyncio
import logging

from bleak import BleakClient
from bleak.exc import BleakError

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

# NOTE: import the function below
# to get the Bluetooth device via Home Assistant
from homeassistant.components.bluetooth import async_ble_device_from_address

from .const import (
    CHAR_UUID,
    NOTIFY_CHAR_UUID,
    INIT_CMD,
    AUTH_CMD_PREFIX,
    AUTH_CMD_SUFFIX,
    SCAN_INTERVAL,
    SPRAY_CMD,
    LIGHT_CMD,
    STATUS_QUERY_CMD,
    STATUS_CMD,
    PUSH_STATUS_CMD,
    FRAME_MAGIC,
    FRAME_FOOTER,
    DIR_RESPONSE,
    ACK_OK,
    BATTERY_CHANNEL_ID,
    LIQUID_CHANNEL_ID,
    STATUS_POLL_INTERVAL,
    DEFAULT_SPRAY_REPEAT_COUNT,
    SPRAY_REPEAT_WAIT,
)

_LOGGER = logging.getLogger(__name__)


def decode_frame(value: bytes):
    """Parses a PetKit BLE protocol frame.

    Format: FA FC FD | CMD | DIR | SEQ | LEN_L LEN_H | PAYLOAD... | FB
    Returns a dict with cmd/dir/seq/payload fields, or None if the frame
    is not recognized (too short or doesn't start with the magic prefix).
    """
    if len(value) < 8 or value[:3] != FRAME_MAGIC:
        return None
    cmd = value[3]
    direction = value[4]
    seq = value[5]
    length = value[6] | (value[7] << 8)
    payload = value[8:8 + length]
    if len(payload) != length:
        return None
    return {"cmd": cmd, "dir": direction, "seq": seq, "payload": payload}


def decode_status_channels(payload: bytes) -> dict:
    """Parses device telemetry (battery/liquid level, etc.).

    Based on analysis of the PetKit app's btsnoop capture, status frames
    (CMD=0xD3 in response to a query, CMD=0xE6 as a push notification)
    contain, after a few header bytes, a list of triplets in the form
    [id, value, 0x7f], where id is the telemetry channel number and value
    is the channel's value (0-100). The exact id -> "battery"/"liquid"
    mapping was determined empirically (see BATTERY_CHANNEL_ID/LIQUID_CHANNEL_ID
    in const.py) and may need calibration against a real device.
    """
    channels = {}
    # Triplets are 3 bytes each; the last byte of each triplet is always 0x7f in the capture.
    for i in range(0, len(payload) - 2):
        chan_id, value, marker = payload[i], payload[i + 1], payload[i + 2]
        if marker == 0x7F and 0 <= value <= 100:
            channels[chan_id] = value
    return channels


class PetkitK3Device:
    def __init__(self, hass, name: str, mac: str, secret: str):
        self.hass = hass
        self.name = name
        self.mac = self.format_mac(mac)
        self.secret = secret
        self.client = None
        self.available = False
        self.light_on = False
        # Device telemetry (populated from notifications/status polling)
        self.battery_level = None
        self.liquid_level = None
        # How many times async_spray() repeats the fixed-length spray cycle
        # (there's no BLE parameter for spray duration, see SPRAY_REPEAT_WAIT).
        self.spray_repeat_count = DEFAULT_SPRAY_REPEAT_COUNT
        self._shutdown = False
        self._notify_started = False
        self.lock = asyncio.Lock()  # Lock for sequential command execution
        self._connect_lock = asyncio.Lock()  # Lock for connecting
        self._connect_attempts = 0  # Connection attempt counter
        self._max_connect_attempts = 5  # Maximum number of attempts before delay
        self._reconnect_delay = 10  # Initial delay in seconds
        # Future objects waiting for the device's response to a specific command (cmd -> Future)
        self._pending: dict[int, asyncio.Future] = {}

    def format_mac(self, mac_str: str) -> str:
        mac_str = mac_str.replace(":", "").upper()
        if len(mac_str) != 12:
            raise ValueError("Invalid MAC address format")
        return ":".join(mac_str[i:i + 2] for i in range(0, 12, 2))

    def _handle_disconnect(self, client):
        self.available = False
        self._notify_started = False
        _LOGGER.warning(f"Device {self.mac} disconnected")
        # Auto-reconnect
        asyncio.create_task(self.async_connect())

    def _handle_notification(self, sender, data: bytearray):
        """Notification handler for the NOTIFY_CHAR_UUID characteristic."""
        frame = decode_frame(bytes(data))
        if frame is None:
            _LOGGER.debug(f"Received an unrecognized packet from {self.mac}: {bytes(data).hex()}")
            return

        _LOGGER.debug(
            f"Frame from {self.mac}: cmd=0x{frame['cmd']:02x} dir=0x{frame['dir']:02x} "
            f"seq=0x{frame['seq']:02x} payload={frame['payload'].hex()}"
        )

        # If this is a response to a command we're waiting for, resolve the Future
        if frame["dir"] == DIR_RESPONSE:
            future = self._pending.get(frame["cmd"])
            if future and not future.done():
                future.set_result(frame["payload"])

        # Device telemetry (battery/liquid level, etc.)
        if frame["cmd"] in (STATUS_CMD, PUSH_STATUS_CMD):
            channels = decode_status_channels(frame["payload"])
            updated = False
            if BATTERY_CHANNEL_ID in channels:
                self.battery_level = channels[BATTERY_CHANNEL_ID]
                updated = True
            if LIQUID_CHANNEL_ID in channels:
                self.liquid_level = channels[LIQUID_CHANNEL_ID]
                updated = True
            if updated:
                _LOGGER.debug(
                    f"Telemetry {self.mac}: battery={self.battery_level}% "
                    f"liquid={self.liquid_level}% (channels={channels})"
                )

    async def async_connect(self) -> bool:
        async with self._connect_lock:
            if self._connect_attempts >= self._max_connect_attempts:
                _LOGGER.warning(
                    f"Maximum number of attempts reached for {self.mac}, waiting {self._reconnect_delay} sec"
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    300,
                    self._reconnect_delay * 2
                )  # Exponentially increase the delay up to 5 minutes
                self._connect_attempts = 0

            # If already connected, reset the counters
            if self.client and getattr(self.client, "is_connected", False):
                self._connect_attempts = 0
                self._reconnect_delay = 10
                return True

            # Try to get the Bluetooth device via Home Assistant
            ble_device = async_ble_device_from_address(self.hass, self.mac, connectable=True)
            if not ble_device:
                _LOGGER.error(
                    f"Could not find Bluetooth device for address {self.mac}. It may be out of range."
                )
                self.available = False
                return False

            try:
                # If a client was previously created, try disconnecting it first
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception as e:
                        _LOGGER.debug(f"Error disconnecting before reconnecting: {e}")

                # Use bleak_retry_connector for a reliable connection
                self.client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    name=self.name,
                    disconnected_callback=self._handle_disconnect,
                    retry_interval=5.0,
                    max_attempts=5,
                    loop=self.hass.loop,
                    timeout=20.0
                )

                _LOGGER.info(f"Connected to {self.mac}")
                self.available = True

                # Subscribe to notifications on the response/status characteristic,
                # otherwise we won't be able to receive command responses (incl. battery/liquid)
                try:
                    await self.client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)
                    self._notify_started = True
                except BleakError as e:
                    self._notify_started = False
                    _LOGGER.error(f"Failed to subscribe to notifications for {self.mac}: {e}")

                self._connect_attempts = 0
                self._reconnect_delay = 10
                return True
            except BleakError as e:
                _LOGGER.error(f"Connection error to {self.mac}: {e}")
                self.available = False
                self.client = None
                self._connect_attempts += 1
                return False

    async def _write_command(self, command_hex: str, timeout: float = 3.0):
        if not self.client or not self.client.is_connected:
            connected = await self.async_connect()
            if not connected:
                return None
        if not self._notify_started:
            # Without a notification subscription we won't get the device's response
            try:
                await self.client.start_notify(NOTIFY_CHAR_UUID, self._handle_notification)
                self._notify_started = True
            except BleakError as e:
                _LOGGER.debug(f"Failed to (re)subscribe to notifications for {self.mac}: {e}")

        data = bytes.fromhex(command_hex)
        cmd = data[3] if len(data) > 3 else None
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        if cmd is not None:
            self._pending[cmd] = future
        try:
            # The characteristic supports write-without-response
            await self.client.write_gatt_char(CHAR_UUID, data, response=False)
            _LOGGER.debug(f"Command {command_hex} sent")
            if cmd is None:
                return None
            try:
                payload = await asyncio.wait_for(future, timeout=timeout)
                resp_hex = payload.hex()
                _LOGGER.debug(f"Response: {resp_hex}")
                return resp_hex
            except asyncio.TimeoutError:
                _LOGGER.debug(f"No response to command {command_hex} received within {timeout} sec")
                return None
        except Exception as e:
            _LOGGER.error(f"Error sending command {command_hex} to {self.mac}: {e}")
            if self.client and self.client.is_connected:
                try:
                    await self.client.disconnect()
                except Exception as e2:
                    _LOGGER.debug(f"Error while disconnecting: {e2}")
            self.client = None
            self._notify_started = False
            return None
        finally:
            if cmd is not None:
                self._pending.pop(cmd, None)

    async def send_command(self, command: str):
        async with self.lock:
            # Initialization and authentication before running the main command
            await self._write_command(INIT_CMD)
            auth_command = AUTH_CMD_PREFIX + self.secret + AUTH_CMD_SUFFIX
            auth_resp = await self._write_command(auth_command)
            if auth_resp != ACK_OK:
                _LOGGER.warning(f"Invalid authentication response for {self.mac}: {auth_resp}")
                self.available = False
                return None
            resp = await self._write_command(command)
            if resp == ACK_OK:
                self.available = True
            else:
                self.available = False
            return resp

    async def async_spray(self):
        """Triggers the spray and turns on the light right after it.

        The command order (spray, then light) was observed in the official
        PetKit app's traffic capture — this is how the light stays on during
        spraying (the "light on during spray" feature).

        There's no BLE parameter for spray duration (each SPRAY_CMD triggers
        one fixed-length cycle), so a longer spray is done by repeating the
        command `spray_repeat_count` times, waiting for one cycle to finish
        (SPRAY_REPEAT_WAIT) between repeats.
        """
        resp = None
        for i in range(max(1, self.spray_repeat_count)):
            if i > 0:
                await asyncio.sleep(SPRAY_REPEAT_WAIT)
            resp = await self.send_command(SPRAY_CMD)
            if resp != ACK_OK:
                break
        # LIGHT_CMD toggles the light (there's no separate on/off command),
        # so only send it if the light is currently off, otherwise spraying
        # while the light is already on would turn it off instead.
        if resp == ACK_OK and not self.light_on:
            light_resp = await self.send_command(LIGHT_CMD)
            if light_resp == ACK_OK:
                self.light_on = True
        return resp

    async def async_query_status(self):
        """Requests telemetry from the device (battery/liquid level)."""
        return await self.send_command(STATUS_QUERY_CMD)

    async def heartbeat_loop(self):
        while not self._shutdown:
            try:
                # Instead of connecting immediately, add a check
                if not self.client or not self.client.is_connected:
                    # Try to connect with a limit
                    if self._connect_attempts < self._max_connect_attempts:
                        await self.async_connect()
                    else:
                        await asyncio.sleep(self._reconnect_delay)

                async with self.lock:
                    await self._write_command(INIT_CMD)
                    auth_command = AUTH_CMD_PREFIX + self.secret + AUTH_CMD_SUFFIX
                    auth_resp = await self._write_command(auth_command)
                    if auth_resp == ACK_OK:
                        _LOGGER.debug(f"Heartbeat successful for {self.mac}")
                        self.available = True
                    else:
                        _LOGGER.debug(f"Heartbeat failed for {self.mac}, trying to reconnect")
                        self.available = False
                        await self.async_connect()
            except Exception as e:
                _LOGGER.exception(f"Error in heartbeat_loop: {e}")

            await asyncio.sleep(SCAN_INTERVAL)

    async def status_poll_loop(self):
        """Periodically polls telemetry (battery/liquid level)."""
        while not self._shutdown:
            try:
                if self.client and self.client.is_connected:
                    await self.async_query_status()
            except Exception as e:
                _LOGGER.exception(f"Error in status_poll_loop: {e}")

            await asyncio.sleep(STATUS_POLL_INTERVAL)

    async def shutdown(self):
        self._shutdown = True
        if self.client and self.client.is_connected:
            if self._notify_started:
                try:
                    await self.client.stop_notify(NOTIFY_CHAR_UUID)
                except Exception as e:
                    _LOGGER.debug(f"Error unsubscribing from notifications: {e}")
            await self.client.disconnect()

