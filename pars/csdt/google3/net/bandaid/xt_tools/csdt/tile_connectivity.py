"""Console Status Display Tool connectivity status tile."""

import logging

from google3.net.bandaid.xt_tools.csdt import lib_commands
from google3.net.bandaid.xt_tools.csdt import lib_status
from google3.net.bandaid.xt_tools.csdt import tile


class ConnectivityStatusTile(tile.InformationTile):
  """Network connectivity status information tile."""

  @staticmethod
  def GetTileName():
    return 'Network connectivity'

  def PingTarget(self, target, interface=None, ip_version=4):
    if ip_version == 4:
      command = 'ping -c2 -i 0.3 %s' % target
    elif ip_version == 6 and interface:
      command = 'ping6 -c2 -i 0.3 -I%s %s' % (interface, target)
    else:
      raise ValueError('Unsupported IP version.')

    try:
      result = self.runner.Run(command, timeout=5)
      if result.exit_code == 0:
        return lib_status.OK
      else:
        return lib_status.ERROR
    except lib_commands.Error as e:
      logging.error('Unable to test connectivity to: %s', target)
      logging.exception(e)
      return lib_status.UNKNOWN

  def GetRefreshInterval(self):
    """"Get the minimum number of seconds between data refreshes."""
    return 30

  def GetTileData(self):
    tile_data = []

    # This is an IPv4 machine, test IPv4 connectivity.
    if self.ipv4_address:
      tile_data.append({
          'target': self.ipv4_gateway,
          'status': self.PingTarget(
              target=self.ipv4_gateway,
              ip_version=4),
      })
      tile_data.append({
          'target': '8.8.8.8',
          'status': self.PingTarget(
              target='8.8.8.8',
              ip_version=4),
      })
      tile_data.append({
          'target': '8.8.4.4',
          'status': self.PingTarget(
              target='8.8.4.4',
              ip_version=4),
      })
    # This is an IPv6-only machine, test IPv6 connectivity.
    elif self.ipv6_address:
      tile_data.append({
          'target': self.ipv6_gateway,
          'status': self.PingTarget(
              target=self.ipv6_gateway,
              interface=self.ipv6_interface,
              ip_version=6),
      })
      tile_data.append({
          'target': 'ipv6.google.com',
          'status': self.PingTarget(
              target='ipv6.google.com',
              interface=self.ipv6_interface,
              ip_version=6),
      })
    # This is something less useful: a machine with no network configuration.
    else:
      logging.error('This machine doesn\'t have usable network configuration.')

    return tile_data

  def GetTileContent(self, tile_data):
    output = []
    row_format = (
        '%(target)-30s '
        '%(status)7s'
    )
    if tile_data:
      for connectivity_test in tile_data:
        fields = {
            'target': connectivity_test['target'],
            'status': connectivity_test['status'].format(c=self.color_codes),
        }
        output.append(row_format % fields)
    else:
      output.append('This machine\'s network is not configured.')

    return '\n'.join(output)
