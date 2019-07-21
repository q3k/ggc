"""Console Status Display Tool power supply status tile."""

import re

from google3.net.bandaid.xt_tools.csdt import lib_sensors
from google3.net.bandaid.xt_tools.csdt import lib_status
from google3.net.bandaid.xt_tools.csdt import tile

SENSOR_MAPS = [
    'sensor-psu-status-map',
    'sensor-psu-presence-map',
    'sensor-psu-voltage-map',
    'sensor-psu-current-map',
]


class PsuStatusTile(tile.InformationTile):
  """Power supply status information tile."""

  @staticmethod
  def GetTileName():
    return 'Power supply status'

  def GetTileData(self):
    tile_data = {
        'all_psus': set(),
        'failed_psus': set(),
    }
    sensors = lib_sensors.GetSensors(command_runner=self.runner)
    for sensor_map in SENSOR_MAPS:
      current_map_sensors = sensors.get(sensor_map, {})

      for sensor_name in current_map_sensors.iterkeys():
        psu_number = int(re.sub('[^0-9]', '', sensor_name)) + 1
        tile_data['all_psus'].add(psu_number)

        # TODO(morda): this is a hack that relies on the fact that an actual
        # sensor value is always a float and in such a case doesn't modify it.
        if isinstance(current_map_sensors[sensor_name], float):
          continue

        # Treat non-OK status of any sensor as an error.
        if current_map_sensors[sensor_name] != lib_status.OK:
          tile_data['failed_psus'].add(psu_number)

    tile_data['all_psus'] = sorted(list(tile_data['all_psus']))
    tile_data['failed_psus'] = sorted(list(tile_data['failed_psus']))
    return tile_data

  def GetTileContent(self, tile_data):
    all_psus = [str(f) for f in tile_data['all_psus']]
    failed_psus = [str(f) for f in tile_data['failed_psus']]

    output = []

    if not all_psus:
      raise tile.Error('BMC unresponsive')

    if failed_psus:
      if len(all_psus) == len(failed_psus):
        output.append('{c.red}Both PSUs have failed{c.reset}')
      else:
        output.append('{c.red}PSUs in slots below have failed{c.reset}')
        output.append(' '.join(failed_psus))
    else:
      output.append('{c.green}Both power supplies are healthy{c.reset}')

    return '\n'.join(output).format(c=self.color_codes)
