"""Console Status Display Tool fan status tile."""

from google3.net.bandaid.xt_tools.csdt import lib_sensors
from google3.net.bandaid.xt_tools.csdt import tile


class FanStatusTile(tile.InformationTile):
  """Fan status information tile."""

  @staticmethod
  def GetTileName():
    return 'Fan status'

  def GetTileData(self):
    tile_data = {
        'all_fans': [],
        'failed_fans': [],
    }
    sensors = lib_sensors.GetSensors(command_runner=self.runner)
    fans = sensors.get('sensor-fan-map', {})

    for sensor_name, sensor_value in fans.iteritems():
      # Physical fans are labelled starting with 1.
      fan_id = int(sensor_name.replace('sensor-fan', '')) + 1
      tile_data['all_fans'].append(fan_id)
      # Positive fan sensor values mean fans are operational.
      if sensor_value <= 0:
        tile_data['failed_fans'].append(fan_id)

    tile_data['all_fans'].sort()
    tile_data['failed_fans'].sort()
    return tile_data

  def GetTileContent(self, tile_data):
    all_fans = [str(f) for f in tile_data['all_fans']]
    failed_fans = [str(f) for f in tile_data['failed_fans']]

    output = []

    if not all_fans:
      raise tile.Error('BMC unresponsive')

    if failed_fans:
      if len(all_fans) == len(failed_fans):
        output.append('{c.red}All fans have failed{c.reset}')
      elif len(failed_fans) > 5:
        output.append('{c.red}More than 5 fans have failed{c.reset}')
      else:
        output.append('{c.red}Fans in slots below have failed{c.reset}')
        output.append(' '.join(failed_fans))
    else:
      output.append('{c.green}All fans are healthy{c.reset}')

    return '\n'.join(output).format(c=self.color_codes)
