"""Console Status Display Tool IPMI sensor library."""

import collections
import logging
import re

from google3.net.bandaid.xt_tools.csdt import lib_status

PATH_IPMITOOL = '/usr/bin/ipmitool'


def ParseTextSensorValue(sensor_value):
  """Convert a textual sensor value to a status.

  This function always returns a numerical status code which allows mapping
  between textual sensor values and specific conditions and also helps to
  identify unhandled values.

  Args:
    sensor_value: sensor value from the output of `ipmitool sdr elist` (str).

  Returns:
    - Task status code if the sensor_value maps directly to it (int):
      http://cs/#piper///depot/google3/util/task/codes.proto
    - Task status code lib_status.UNIMPLEMENTED in all remaining cases.
      In such cases, the sensor_value will be logged and a bug should be raised
      (int).
  """
  normalised_sensor_value = str(sensor_value).strip().lower()

  # This is an ordered list of tuples of (string to search for, code).
  sensor_value_to_code_map = [
      ('connected', lib_status.OK),
      ('drive present', lib_status.OK),
      ('fully redundant', lib_status.OK),
      ('presence detected', lib_status.OK),
      ('watts, presence detected', lib_status.OK),
      ('present', lib_status.OK),
      ('state deasserted', lib_status.OK),
      ('absent', lib_status.NOT_FOUND),
      ('disabled', lib_status.UNAVAILABLE),
      ('presence detected, power supply ac lost', lib_status.UNAVAILABLE),
      ('presence detected, failure detected', lib_status.UNAVAILABLE),
      ('redundancy lost', lib_status.UNAVAILABLE),
      ('no reading', lib_status.UNAVAILABLE),
      ('oem specific', lib_status.UNAVAILABLE),
  ]
  # If sensor value maps to a specific code, return it.
  for sensor, sensor_code in sensor_value_to_code_map:
    if sensor in normalised_sensor_value:
      code = sensor_code
  if code is not None:
    return code

  # In all remaining cases, log a warning and return lib_status.UNIMPLEMENTED.
  logging.warning('Unhandled IPMI sensor value (please file a bug): %s',
                  sensor_value)
  return lib_status.UNKNOWN


def ParseNumericSensorValue(sensor_value):
  """Return value of a sensor without its unit.

  Args:
    sensor_value: sensor value from the output of `ipmitool sdr elist` (str).

  Returns:
    - sensor_value without a unit (float).
    - -1 if sensor value isn't in the expected format, for instance when instead
      of '230 Volts', it changes into 'No reading' due to a power supply being
      removed (int).
  """
  normalised_sensor_value = str(sensor_value).strip().lower()

  # If the sensor value contains a numerical value and a unit, return just the
  # numerical value converted to a float.
  match = _RE_SENSOR_VALUE_WITH_UNIT.match(normalised_sensor_value)
  if match:
    return float(match.group('value'))
  # In all other cases, return -1.
  return -1


# Define sensors we want to include and rename them so that their names are
# consistent across all supported platforms. We whitelist sensors by both their
# name and entity number, since there exist sensors by the same name but with
# different entity numbers, i.e. 'Presence' is a prime example.
# Each tuple in the whitelist must include:
#   - Unified sensor name (str).
#   - Regular expression to match raw sensor names (instance of re.compile).
#   - List of entities that the sensor may be associated with (set).
#   - One argument function to use to parse raw sensor value (function).
_SENSOR_WHITELIST = [
    # Ambient temperature on Dell R710.
    ('sensor-ambient-temp', re.compile(r'^ambient temp$', re.IGNORECASE),
     set(['7.1']), ParseNumericSensorValue),
    # Ambient temperature on Dell R720 and R730.
    ('sensor-ambient-temp', re.compile(r'^inlet temp$', re.IGNORECASE),
     set(['7.1']), ParseNumericSensorValue),
    ('sensor-fan', re.compile(r'^fan *[0-9]+[AB]? *(rpm)?$', re.IGNORECASE),
     set(['7.1']), ParseNumericSensorValue),
    ('sensor-psu-presence', re.compile(r'^Presence$', re.IGNORECASE),
     set(['10.1', '10.2']), ParseTextSensorValue),
    ('sensor-psu-status', re.compile(r'^Status$', re.IGNORECASE),
     set(['10.1', '10.2']), ParseTextSensorValue),
    ('sensor-psu-voltage', re.compile(r'^voltage( [0-9]+)?$', re.IGNORECASE),
     set(['10.1', '10.2']), ParseNumericSensorValue),
    ('sensor-psu-current', re.compile(r'^current( [0-9]+)?$', re.IGNORECASE),
     set(['10.1', '10.2']), ParseNumericSensorValue),
    ('sensor-psu-redundancy', re.compile(r'^PS Redundancy$', re.IGNORECASE),
     set(['7.1']), ParseTextSensorValue),
    ('sensor-fan-redundancy', re.compile(r'^Fan Redundancy$', re.IGNORECASE),
     set(['7.1']), ParseTextSensorValue),

    # HP Apollo temperature sensors
    ('sensor-cpu-temp', re.compile(r'^[0-9]+-CPU ([0-9]+)$', re.IGNORECASE),
     {'65.1', '65.2'}, ParseNumericSensorValue),
    ('sensor-ambient-temp',
     re.compile(r'^[0-9]+-Front Ambient$', re.IGNORECASE), {'64.1'},
     ParseNumericSensorValue),

    # HP Apollo PSU sensors
    ('sensor-psu-status', re.compile(r'^Power Supply .', re.IGNORECASE),
     set(['10.1', '10.2']), ParseTextSensorValue),
    ('sensor-psu-presence', re.compile(r'.*Presence detected$', re.IGNORECASE),
     set(['10.1', '10.2']), ParseTextSensorValue),

    # HP Apollo Fans
    ('sensor-fan', re.compile(r'^Fan [0-9]+ DutyCycle$', re.IGNORECASE),
     {'29.1', '29.2', '29.3', '29.4', '29.5', '29.6', '29.7', '29.8',
      '29.9', '29.10'}, ParseNumericSensorValue),
    ('sensor-fan-redundancy', re.compile(r'^Fans$', re.IGNORECASE),
     {'29.11'}, ParseTextSensorValue),

]

# Group sensor data, so that we can return maps such as temp-map containing
# multiple related variables
_SENSOR_GROUPS = {
    'sensor-temp-map': re.compile(r'^sensor-[a-z]+-temp[0-9]+$'),
    'sensor-psu-presence-map': re.compile(r'^sensor-psu-presence[0-9]+$'),
    'sensor-psu-status-map': re.compile(r'^sensor-psu-status[0-9]+$'),
    'sensor-psu-current-map': re.compile(r'^sensor-psu-current[0-9]+$'),
    'sensor-psu-voltage-map': re.compile(r'^sensor-psu-voltage[0-9]+$'),
    'sensor-fan-map': re.compile(r'^sensor-fan[0-9]+$'),
}

_RE_SENSOR_VALUE_WITH_UNIT = re.compile(
    r'^(?P<value>\d+(?:\.\d+)?)\s+'
    r'(?P<unit>(?:amps|watts|volts|rpm|degrees c|percent))$',
    re.IGNORECASE)


def MergeCompositeFans(parsed_sensor_lines):
  """Aggregate RPM values for composite fans into a single value.

  A composite fan is actually two physical fans in the same casing, which report
  individual speeds, but cannot be replaced independently. The composite case
  takes up a "fan slot", as such we need to replace the composite fan once any
  of the two integrated fans have failed.

  Args:
    parsed_sensor_lines: List containing all ipmitool provided sensor names and
    values

  Returns:
    A list where composite fan module RPMs have been aggregated to the minimum
    value.
  """
  fan_names = [
      sensor_line['name'] for sensor_line in parsed_sensor_lines
      if sensor_line['type'] == 'sensor-fan'
  ]

  fan_values = collections.OrderedDict()
  for fan_name in fan_names:
    fan_number = re.match(r'^fan *([0-9]+)', fan_name, re.IGNORECASE).group(0)
    for sensor_line in parsed_sensor_lines:
      if sensor_line['name'] == fan_name:
        break
    if fan_number in fan_values:
      fan_values[fan_number] = min(fan_values[fan_number], sensor_line['value'])
    else:
      fan_values[fan_number] = sensor_line['value']

  parsed_sensor_lines = [
      sensor_line for sensor_line in parsed_sensor_lines
      if sensor_line['name'] not in fan_names
  ]

  for fan, value in fan_values.items():
    parsed_sensor_lines.append({
        'name': fan,
        'entity': '7.1',
        'type': 'sensor-fan',
        'value': value
    })

  return parsed_sensor_lines


def ParseSensors(ipmitool_output):
  """Parse the output from 'ipmitool sdr elist' command.

  Args:
    ipmitool_output: a string containing raw output from
      'ipmitool sdr elist' (str).

  Returns:
    A dictionary with grouped IPMI sensors.
  """
  logging.debug('Parsing `ipmitool sdr elist` output')
  # All sensors that were caught by the SENSOR_WHITELIST filter.
  sensor_data = collections.defaultdict(list)
  # Indexed and grouped sensors.
  sensors_grouped = collections.defaultdict(dict)

  parsed_sensor_lines = []

  for line in ipmitool_output.splitlines():
    fields = [f.strip() for f in line.split('|')]
    if len(fields) != 5:
      continue  # Ignore unsupported line.
    sensor_name = fields[0]
    sensor_entity = fields[3]
    sensor_value = fields[4]

    # Ignore reporting disabled sensors.
    # Example: fans Fan6A and Fan6B on Dell R440s have blanks in their slots.
    if str(sensor_value).strip().lower() == 'disabled':
      continue

    for sensor, name_pattern, entities, parser_function in _SENSOR_WHITELIST:
      if name_pattern.search(sensor_name) and sensor_entity in entities:
        parsed_sensor_lines.append({
            'name': sensor_name,
            'entity': sensor_entity,
            'type': sensor,
            'value': parser_function(sensor_value)
        })
        break

  # b/28107320 R430, R440 and R630 run on "composite fans" - a single fan
  # chassis that contains and reports two independent fans, but which cannot be
  # replaced independently. A composite fan uses up a "fan slot" in the machine.
  # We run the data through a helper to aggregate speeds of composite fans and
  # provide output related to fan modules, rather than independent spinners.
  parsed_sensor_lines = MergeCompositeFans(parsed_sensor_lines)

  for sensor_line in parsed_sensor_lines:
    sensor_data[sensor_line['type']].append(sensor_line['value'])

  # Index and group sensors.
  for sensor_name, sensor_values in sensor_data.iteritems():
    for sensor_index, sensor_value in enumerate(sensor_values):
      sensor_indexed_name = '%s%d' % (sensor_name, sensor_index)
      for sensor_group, sensor_pattern in _SENSOR_GROUPS.iteritems():
        if sensor_pattern.match(sensor_indexed_name):
          sensors_grouped[sensor_group][sensor_indexed_name] = sensor_value
          break  # Sensor already grouped, skip checking other groups.
      # Add an ungrouped sensor.
      else:
        sensors_grouped[sensor_name] = sensor_value
  return sensors_grouped


def GetSensors(command_runner):
  command = '%s sdr elist' % PATH_IPMITOOL
  result = command_runner.Run(command)
  return ParseSensors(ipmitool_output=result.output)
