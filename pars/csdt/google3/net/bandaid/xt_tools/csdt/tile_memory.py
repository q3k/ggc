"""Console Status Display Tool memory status tile."""

import re

from google3.net.bandaid.xt_tools.csdt import tile


RE_MEMTOTAL = re.compile(r'^MemTotal:\s+(\d+)\s+kB$')


class MemoryStatusTile(tile.InformationTile):
  """RAM status information tile."""

  @staticmethod
  def GetTileName():
    return 'Memory status'

  def GetTileData(self):
    tile_data = {}
    with open('/proc/meminfo', 'r') as file_handle:
      for line in file_handle:
        match = RE_MEMTOTAL.match(line.strip())
        if match:
          tile_data['meminfo_memtotal'] = int(match.group(1))
          return tile_data
    return tile_data

  def GetTileContent(self, tile_data):
    memory_total = tile_data.get('meminfo_memtotal', 0)
    if memory_total:
      return 'Detected: %d GB' % int(memory_total / 1024 / 1024)
    else:
      raise tile.Error('Unable to get the total amount of memory detected.')
