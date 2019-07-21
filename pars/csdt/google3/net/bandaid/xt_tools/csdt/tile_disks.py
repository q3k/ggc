"""Console Status Display Tool disk status tile."""

from google3.net.bandaid.xt_tools.csdt import lib_disk_parser
from google3.net.bandaid.xt_tools.csdt import lib_hpssacli
from google3.net.bandaid.xt_tools.csdt import lib_megacli
from google3.net.bandaid.xt_tools.csdt import lib_status
from google3.net.bandaid.xt_tools.csdt import tile


class DiskStatusTile(tile.InformationTile):
  """Disk status information tile."""

  @staticmethod
  def GetTileName():
    return 'Disk status'

  def GetSlotStatus(self, slot_data):
    if slot_data['predictive_failure'] > 0:
      return lib_status.ERROR

    if 'online' in slot_data['firmware_state'].lower():
      return lib_status.OK

    if slot_data['firmware_state'].lower() == 'ok':
      return lib_status.OK

    if 'good' in slot_data['firmware_state'].lower():
      return lib_status.OK

    if 'bad' in slot_data['firmware_state'].lower():
      return lib_status.ERROR

    if 'failed' in slot_data['firmware_state'].lower():
      return lib_status.ERROR

    return lib_status.UNKNOWN

  def GetTileData(self):
    tile_data = {
        'slots_all': [],
        'slots_failed': [],
    }
    for disk_library in [lib_megacli.MegaCLI, lib_hpssacli.Hpssacli]:
      try:
        disk_library_instance = disk_library(command_runner=self.runner)
        disk_slots = disk_library_instance.GetDiskInformation()
        if disk_slots:
          break
      except lib_disk_parser.Error:
        disk_slots = []

    for disk_slot in disk_slots:
      tile_data['slots_all'].append(disk_slot['slot'])
      if self.GetSlotStatus(disk_slot) != lib_status.OK:
        tile_data['slots_failed'].append(disk_slot['slot'])

    tile_data['slots_all'].sort()
    tile_data['slots_failed'].sort()
    return tile_data

  def GetTileContent(self, tile_data):
    output = []

    slots_all = [str(s) for s in tile_data['slots_all']]
    slots_failed = [str(s) for s in tile_data['slots_failed']]

    if not slots_all:
      raise tile.Error('Unable to query disk controller')

    if slots_failed:
      if slots_all == slots_failed:
        output.append('{c.red}All disks have failed{c.reset}')
      elif len(slots_failed) > 5:
        output.append('{c.red}More than 5 disks have failed{c.reset}')
      else:
        output.append('{c.red}Disks in slots below have failed{c.reset}')
        output.append(' '.join(slots_failed))
    else:
      output.append('{c.green}All disks are healthy{c.reset}')
    return '\n'.join(output).format(c=self.color_codes)
