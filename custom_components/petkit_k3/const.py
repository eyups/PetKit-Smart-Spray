# const.py
DOMAIN = "petkit_k3"
PLATFORMS = ["light", "button", "sensor"]

DEFAULT_REGION = "US"
DEFAULT_TIMEZONE = ""

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_TIMEZONE = "timezone"
CONF_DEVICES = "devices"

# Bluetooth constants
# Characteristic for writing commands (write / write-without-response)
CHAR_UUID = "0000aaa2-0000-1000-8000-00805f9b34fb"
# Characteristic on which the device sends responses/status (notify)
NOTIFY_CHAR_UUID = "0000aaa1-0000-1000-8000-00805f9b34fb"

INIT_CMD = "fafcfdd501000000fb"

# Authentication command – the secret is inserted between the prefix and suffix
AUTH_CMD_PREFIX = "fafcfd56010108000000"
AUTH_CMD_SUFFIX = "fb"

# Control commands
SPRAY_CMD = "fafcfddc010a02000103fb"
LIGHT_CMD = "fafcfddc010b02000203fb"

# Protocol frame format (derived from analysis of the PetKit app's btsnoop
# capture; the structure matches BLE_START_TRAME/BLE_END_TRAME from the
# official pypetkitapi library):
#   FA FC FD | CMD | DIR | SEQ | LEN_L LEN_H | PAYLOAD... | FB
# where DIR: 0x01 = request, 0x02 = response/event.
FRAME_MAGIC = b"\xfa\xfc\xfd"
FRAME_FOOTER = 0xFB
DIR_REQUEST = 0x01
DIR_RESPONSE = 0x02

# Command to query device telemetry (battery/liquid level).
# CMD=0xD3, DIR=request, no payload. The device replies with a CMD=0xD3
# frame containing a set of [id, value, 0x7f] triplets, one per channel.
STATUS_QUERY_CMD = "fafcfdd3010c0000fb"
STATUS_CMD = 0xD3
# Periodic push notifications after spray/light commands arrive with CMD=0xE6
# and contain the same triplet structure.
PUSH_STATUS_CMD = 0xE6

# A single-byte value of "01" in the response means the command succeeded
# (confirmed by the capture: responses to auth/spray/light contain payload=01).
ACK_OK = "01"

# Telemetry channel mapping (id -> name), determined empirically from the
# traffic capture (filtered.log). All channel values in the capture were in
# the 0-100 range, which corresponds to a percentage. Needs verification on
# a real device: if the readings don't match the PetKit app, swap the ids.
BATTERY_CHANNEL_ID = 2
LIQUID_CHANNEL_ID = 3

# Telemetry polling interval (battery/liquid), in seconds.
STATUS_POLL_INTERVAL = 300

SCAN_INTERVAL = 60  # heartbeat period in seconds