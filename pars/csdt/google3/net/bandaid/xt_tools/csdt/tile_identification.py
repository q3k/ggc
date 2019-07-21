"""Console Status Display Tool top status bar (host identification) tile."""

from google3.net.bandaid.xt_tools.csdt import lib_common
from google3.net.bandaid.xt_tools.csdt import tile


class IdentificationTile(tile.InformationTile):
  """Machine indentification tile."""

  @staticmethod
  def GetTileName():
    return 'Top status bar'

  def DisplayTileName(self):
    return False

  def GetRefreshInterval(self):
    return 60

  def GetTileData(self):
    tile_data = {
        'hostname': self.hostname,
        'service_tag': self.service_tag,
        'hardware_model': self.hardware_model,
        'uptime': lib_common.GetUptime(),
    }

    # This is an IPv4 machine.
    if self.ipv4_address:
      tile_data['ip_address'] = self.ipv4_address
    # This is an IPv6-only machine.
    elif self.ipv6_address:
      tile_data['ip_address'] = self.ipv6_address
    # This is something less useful: a machine with no network configuration.
    else:
      tile_data['ip_address'] = 'unknown'

    return tile_data

  def GetTileContent(self, tile_data):
    output = []

    rows = [
        [
            ' ',
            'Host: ',
            tile_data['hostname'],
            'Hardware: ',
            tile_data['hardware_model'],
            ' ',
        ], [
            ' ',
            'IP: ',
            tile_data['ip_address'],
            'Service tag: ',
            tile_data['service_tag'],
            ' ',
        ], [
            ' ',
            '',
            '',
            'Uptime: ',
            tile_data['uptime'],
            ' ',
        ],
    ]
    column_widths = [0, 0, 0, 0, 0, 0]

    # Calculate appropriate column widths.
    for row in rows:
      for column, field in enumerate(row):
        field_length = len(str(field))
        if field_length > column_widths[column]:
          column_widths[column] = field_length

    # Assign remaining space to the column holding hostname and IP address.
    column_widths[2] += 80 - sum(column_widths)

    for row in rows:
      current_row = []
      for column, field in enumerate(row):
        # Right-align content.
        if column in [1, 3]:
          current_row.append(
              '{field:>{column_width}}'.format(
                  field=field,
                  column_width=column_widths[column]))
        # Left-align content.
        else:
          current_row.append(
              '{field:<{column_width}}'.format(
                  field=field,
                  column_width=column_widths[column]))
      output.append(''.join(current_row).rstrip())

    return '\n'.join(output)
