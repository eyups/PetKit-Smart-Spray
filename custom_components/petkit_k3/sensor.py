# sensor.py
import logging
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    domain_data = hass.data[DOMAIN]
    entities = []
    for device_id, device in domain_data.items():
        entities.append(PetkitK3BatterySensor(device_id, device))
        entities.append(PetkitK3LiquidLevelSensor(device_id, device))
    async_add_entities(entities, update_before_add=True)


class PetkitK3BaseSensor(SensorEntity):
    def __init__(self, device_id, device_controller):
        self._device_id = device_id
        self._controller = device_controller

    @property
    def available(self):
        return self._controller.available

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._controller.name,
            manufacturer="Petkit",
            model="K3"
        )

    async def async_update(self):
        # Values are updated by the device's background tasks
        # (BLE notifications and the periodic status_poll_loop),
        # so we simply do nothing here — HA reads the state from
        # the native_value property on every entity poll.
        pass


class PetkitK3BatterySensor(PetkitK3BaseSensor):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, device_id, device_controller):
        super().__init__(device_id, device_controller)
        self._attr_name = f"{device_controller.name} Battery"
        self._attr_unique_id = f"{device_id}_battery"

    @property
    def native_value(self):
        return self._controller.battery_level


class PetkitK3LiquidLevelSensor(PetkitK3BaseSensor):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:spray-bottle"

    def __init__(self, device_id, device_controller):
        super().__init__(device_id, device_controller)
        self._attr_name = f"{device_controller.name} Liquid Level"
        self._attr_unique_id = f"{device_id}_liquid_level"

    @property
    def native_value(self):
        return self._controller.liquid_level
