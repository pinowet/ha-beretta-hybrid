"""Sensors for the Beretta hybrid integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BerettaConfigEntry
from .decoding import PDC_MODE_SET, PDC_OPERATING_STATE, SENSOR_POINTS
from .entity import BerettaEntity

PARALLEL_UPDATES = 0

_TEMP = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    "state_class": SensorStateClass.MEASUREMENT,
}
_DIAG = {"entity_category": EntityCategory.DIAGNOSTIC}
_HIDDEN = {"entity_category": EntityCategory.DIAGNOSTIC, "entity_registry_enabled_default": False}

_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    # ---------------------------------------------------------------- PdC
    "pdc_mode_set": {
        "device_class": SensorDeviceClass.ENUM,
        "options": list(PDC_MODE_SET.values()),
    },
    "pdc_operating_state": {
        "device_class": SensorDeviceClass.ENUM,
        "options": list(PDC_OPERATING_STATE.values()),
    },
    "pdc_water_setpoint_zone1": _TEMP,
    "pdc_water_setpoint_zone2": {**_TEMP, "entity_registry_enabled_default": False},
    "pdc_compressor_frequency": {
        "device_class": SensorDeviceClass.FREQUENCY,
        "native_unit_of_measurement": UnitOfFrequency.HERTZ,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pdc_water_return": _TEMP,
    "pdc_water_flow_temp": _TEMP,
    "pdc_outdoor_temp": _TEMP,
    "pdc_discharge_temp": _TEMP,
    "pdc_suction_temp": _TEMP,
    "pdc_exchanger_refrigerant_temp": _TEMP,
    "pdc_condenser_refrigerant_temp": _TEMP,
    "pdc_compressor_hours": {
        "device_class": SensorDeviceClass.DURATION,
        "native_unit_of_measurement": UnitOfTime.HOURS,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        **_DIAG,
    },
    "pdc_capacity": {
        "device_class": SensorDeviceClass.POWER,
        "native_unit_of_measurement": UnitOfPower.KILO_WATT,
        **_DIAG,
    },
    "pdc_error_code": _DIAG,
    "pdc_status_128": _HIDDEN,
    "pdc_status_129": _HIDDEN,
    "pdc_water_flow": {
        "device_class": SensorDeviceClass.VOLUME_FLOW_RATE,
        "native_unit_of_measurement": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        "state_class": SensorStateClass.MEASUREMENT,
        "suggested_display_precision": 2,
    },
    "pdc_thermal_power": {
        "device_class": SensorDeviceClass.POWER,
        "native_unit_of_measurement": UnitOfPower.KILO_WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "suggested_display_precision": 2,
    },
    "pdc_energy_consumed": {
        "device_class": SensorDeviceClass.ENERGY,
        "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    # ------------------------------------------------------------- Caldaia
    "boiler_pressure": {
        "device_class": SensorDeviceClass.PRESSURE,
        "native_unit_of_measurement": UnitOfPressure.BAR,
        "state_class": SensorStateClass.MEASUREMENT,
        "suggested_display_precision": 1,
    },
    "boiler_flow_temp": {**_TEMP, "suggested_display_precision": 1},
    "boiler_return_temp": {**_TEMP, "suggested_display_precision": 1},
    "boiler_dhw_temp": {**_TEMP, "suggested_display_precision": 1},
    "boiler_flue_temp": {**_TEMP, "suggested_display_precision": 1},
    "boiler_outdoor_temp": {
        **_TEMP,
        "suggested_display_precision": 1,
        "entity_registry_enabled_default": False,
    },
    "boiler_fan_speed": {
        "native_unit_of_measurement": REVOLUTIONS_PER_MINUTE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "boiler_fan_target": {
        "native_unit_of_measurement": REVOLUTIONS_PER_MINUTE,
        "state_class": SensorStateClass.MEASUREMENT,
        **_HIDDEN,
    },
    "boiler_status": _HIDDEN,
    "boiler_dhw_setpoint": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "suggested_display_precision": 0,
    },
    # ----------------------------------------------------------------- T300
    "t300_command_word": _HIDDEN,
    "t300_params_update": {"device_class": SensorDeviceClass.TIMESTAMP, **_DIAG},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BerettaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    hub = entry.runtime_data
    async_add_entities(
        BerettaSensor(
            hub,
            entry,
            SensorEntityDescription(
                key=point.key, translation_key=point.key, **_DESCRIPTIONS[point.key]
            ),
            point,
        )
        for point in SENSOR_POINTS
    )


class BerettaSensor(BerettaEntity, SensorEntity):
    """A value decoded from the Modbus bus."""

    def _set_value(self, value: Any) -> None:
        if (
            value is not None
            and self.entity_description.device_class == SensorDeviceClass.TIMESTAMP
        ):
            value = dt_util.utc_from_timestamp(value)
        self._attr_native_value = value
