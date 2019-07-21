"""Console Status Display Tool ethtool library."""

import logging
import os
import re
import textwrap

from google3.net.bandaid.xt_tools.csdt import lib_commands


_ETHTOOL_PATHS = [
    '/export/hda3/bandaid/third_party/ethtool',
    '/sbin/ethtool',
]


def _StrToBool(value):
  """Translate a boolean string value into an actual boolean.

  Args:
    value: String to evaluate, must be 'yes' or 'no'.

  Returns:
    Boolean.

  Raises:
    ValueError: value did not match any valid string.
  """
  if value.lower() == 'yes':
    return True
  if value.lower() == 'no':
    return False
  raise ValueError('Unexpected value')


_LIGHT_PARSE_SPEC = [
    ('Laser output power', 'laser_tx_power_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser output power', 'laser_tx_power_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser output power high warning threshold',
     'laser_tx_power_high_warning_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser output power high warning threshold',
     'laser_tx_power_high_warning_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser output power high alarm threshold',
     'laser_tx_power_high_alarm_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser output power high alarm threshold',
     'laser_tx_power_high_alarm_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser output power low warning threshold',
     'laser_tx_power_low_warning_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser output power low warning threshold',
     'laser_tx_power_low_warning_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser output power low alarm threshold',
     'laser_tx_power_low_alarm_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser output power low alarm threshold',
     'laser_tx_power_low_alarm_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Receiver signal average optical power', 'rx_power_mw',
     r'^([-.\d]+) mW /', float),
    ('Receiver signal average optical power', 'rx_power_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser rx power high warning threshold',
     'rx_power_high_warning_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser rx power high warning threshold',
     'rx_power_high_warning_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser rx power high alarm threshold',
     'rx_power_high_alarm_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser rx power high alarm threshold',
     'rx_power_high_alarm_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser rx power low warning threshold',
     'rx_power_low_warning_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser rx power low warning threshold',
     'rx_power_low_warning_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser rx power low alarm threshold',
     'rx_power_low_alarm_mw',
     r'^([-.\d]+) mW /', float),
    ('Laser rx power low alarm threshold',
     'rx_power_low_alarm_dbm',
     r'/ ([-.\d]+) dBm', float),
    ('Laser wavelength', 'laser_wavelength_nm',
     r'^(\d+)nm$', int),
    ('Module temperature', 'temperature_cel',
     r'^([.\d]+) degrees C /', float),
    ('Module temperature', 'temperature_far',
     r' / ([.\d]+) degrees F$', float),
    ('Vendor name', 'vendor_name', r'^(.*)$', str),
    ('Vendor PN', 'vendor_pn', r'^(.*)$', str),
    ('Vendor SN', 'vendor_sn', r'^(.*)$', str),
    ('Vendor rev', 'vendor_rev', r'^(.*)$', str),
    ('Transceiver type', 'transceiver_type', r'^(.*)$', str),
]
_LINK_PARSE_SPEC = [
    ('Link detected', 'link_state',
     r'^(?i)(yes|no)$', _StrToBool),
    ('Speed', 'speed', r'([0-9]+)', int),
    ('Port', 'port', r'^(.*)', str),
]


class Error(Exception):
  pass


def SanitizeData(raw_dict, parse_spec):
  """Select and sanitize interesting data.

  This function looks for a specific set of keys in raw_dict, renames the key
  appropriately, extracts the desired string from raw_dict[key], and change it
  to the correct type.

  Args:
    raw_dict: Unsanitized key/value data in a dict.
    parse_spec: List of tuples, each containing 4 values:
        1) The key we are looking for in raw_dict (if the key is not found, it
        is not added to the returned dict),
        2) What the key must be called in the returned dict,
        3) A regex used to extract the desired string from raw_dict[key] (if
        regex does not match, the key does not go into the returned dict). The
        regex should be as specific as possible, in order to fail if ethtool
        output changes,
        4) A function that is run against the output value, typically to
        convert it to a proper variable type.

  Returns:
    A dict that is a subset of raw_data, cleaned.
  """
  data = {}

  for input_key, output_key, pattern, type_func in parse_spec:
    if input_key in raw_dict:
      raw_value = raw_dict[input_key]

      if isinstance(raw_value, list):
        sanitized_values_list = []
        for value in raw_value:
          match = re.search(pattern, value)
          if match:
            sanitized_values_list.append(type_func(match.group(1)))
          else:
            logging.debug(
                "Regexp didn't match any value for key %s", output_key)
        data[output_key] = sanitized_values_list
      else:
        match = re.search(pattern, raw_value)
        if match:
          sanitized_value = type_func(match.group(1))
          data[output_key] = sanitized_value
        else:
          logging.debug("Regexp didn't match any value for key %s", output_key)

  return data


def SanitizeOpticsData(raw_dict):
  """Calls SanitizeData() with _LIGHT_PARSE_SPEC parse spec."""
  return SanitizeData(raw_dict, _LIGHT_PARSE_SPEC)


def ParseKeyValueLines(text):
  """Convert text into a dict.

  Each line is in the form of "key : value". Lines starting with whitespace
  are treated as a continuation of the previous value.

  Lines that are not part of a key/value pair are ignored.

  Args:
    text: String containing "key : value" lines.

  Returns:
     A dict containing the raw key/value strings. Whitespace is stripped from
     the start and end of each string.
  """
  data = {}
  current_key = None
  for line in text.splitlines():
    # Get rid of empty line
    if not line.strip():
      continue
    # Continuation of the previous value?
    if line.startswith(' '):
      # Only if we have encountered a key
      if current_key is not None:
        data[current_key] += ' ' + line.strip()
      # Else ignore the line
      continue

    fields = line.split(':', 1)
    if len(fields) != 2:
      continue
    current_key = fields[0].strip()
    # Build list of values for lines with the same key.
    if current_key in data:
      if isinstance(data[current_key], list):
        data[current_key].append(fields[1].strip())
      else:
        data[current_key] = [data[current_key], fields[1].strip()]
    else:
      data[current_key] = fields[1].strip()

  return data


def _GetCommandOutput(command_runner, command):
  """Helper function for testing."""
  try:
    result = command_runner.Run(command)
    output = result.output.strip()
    if result.exit_code:
      output = ''
  except lib_commands.Error as e:
    logging.exception(e)
    output = ''
  return output


def _GetEthtoolPath():
  """Find the correct ethtool binary path."""
  for path in _ETHTOOL_PATHS:
    if os.path.isfile(path):
      logging.debug('Using ethtool found at %s.', path)
      return path
  raise Error('Missing ethtool binary.')


def GetEthtoolDetails(command_runner, ethtool_cmd, parse_spec, header_lines=0):
  """Runs given ethtool command, and requests its parsing and sanitizing.

  Args:
    command_runner: lib_commands.CommandRunner instance.
    ethtool_cmd: ethtool path and arguments (str).
    parse_spec: List used to know what data to keep and how to sanatize it.
    header_lines: Number of lines to be stripped from the header.

  Returns:
    A dict containing filtered and sanitized data.
  """
  output = _GetCommandOutput(command_runner, ethtool_cmd)
  lines = output.splitlines()
  # Getting rid of header line that has no value
  lines = lines[header_lines:]
  output = textwrap.dedent('\n'.join(lines))
  data = ParseKeyValueLines(output)
  return SanitizeData(data, parse_spec)


def GetNicDetails(
    command_runner, device, ethtool_path=None, get_optics_details=False):
  """Requests ethtool outputs parsing, and sanitizing.

  Args:
    command_runner: lib_commands.CommandRunner instance.
    device: interface name.
    ethtool_path: ethtool binary to run.
    get_optics_details: collect optics related details if supported by
                        interface (WARNING: might cause interface flap).

  Returns:
    A dict containing filtered and sanitized data.
  """
  if ethtool_path is None:
    ethtool_path = _GetEthtoolPath()

  ethtool_cmd = '%s %s' % (ethtool_path, device)
  data = GetEthtoolDetails(
      command_runner, ethtool_cmd, _LINK_PARSE_SPEC, header_lines=1)
  if (data.get('port', '') == 'FIBRE' and data.get('link_state', False) and
      get_optics_details):
    ethtool_cmd = '%s -m %s' % (ethtool_path, device)
    data.update(GetEthtoolDetails(
        command_runner, ethtool_cmd, _LIGHT_PARSE_SPEC))

  if 'port' in data:
    try:
      with open('/sys/class/net/'+device+'/carrier_changes') as file_handle:
        data['carrier_changes'] = int(file_handle.read().rstrip())
    except IOError:
      data['carrier_changes'] = None

  return data
