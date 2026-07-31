# number.py
import logging
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, MIN_SPRAY_REPEAT_COUNT, MAX_SPRAY_REPEAT_COUNT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    domain_data = hass.data[DOMAIN]
    entities = []
    for device_id, device in domain_data.items():
        entities.append(PetkitK3SprayRepeatNumber(device_id, device))
    async_add_entities(entities, update_before_add=True)


class PetkitK3SprayRepeatNumber(NumberEntity):
    _attr_native_min_value = MIN_SPRAY_REPEAT_COUNT
    _attr_native_max_value = MAX_SPRAY_REPEAT_COUNT
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:repeat"

    def __init__(self, device_id, device_controller):
        self._device_id = device_id
        self._controller = device_controller
        self._attr_name = f"{device_controller.name} Spray Repeat Count"
        self._attr_unique_id = f"{device_id}_spray_repeat_count"

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

    @property
    def native_value(self):
        return self._controller.spray_repeat_count

    async def async_set_native_value(self, value: float) -> None:
        self._controller.spray_repeat_count = int(value)
        self.async_write_ha_state()

    async def async_update(self):
        # Nothing to fetch; this just makes HA re-evaluate `available` periodically.
        pass
