# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/platform_itami.py
# Compiled at: 2019-06-18 16:41:38
"""Itami platform specific identification implementation."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
import logging
from google3.net.bandaid.xt_installer.setup import platformutils

class PlatformItami(platformutils.PlatformBase):
    """Generic Itami machine."""

    def __init__(self):
        super(PlatformItami, self).__init__()
        self._root_disk = None
        self._skip_reboot = False
        self._quiet = False
        self._dry_run = True
        return

    def PassEnv(self, env):
        self._skip_reboot = env.skip_reboot
        self._dry_run = env.dry_run
        self._quiet = env.quiet
        self._root_disk = env.prospective_root_disk

    @classmethod
    def GetName(cls):
        return 'Generic Itami'

    @classmethod
    def Match(cls, sysinfo):
        return cls._CheckVendor(sysinfo['vendor']) and cls._CheckModel(sysinfo['model']) and cls._CheckBoard(sysinfo['board']) and cls._CheckNetwork(sysinfo['network']) and cls._CheckStorage(sysinfo['storage'])

    @classmethod
    def _CheckVendor(cls, vendor):
        return True

    @classmethod
    def _CheckModel(cls, model):
        return True

    @classmethod
    def _CheckBoard(cls, board):
        return 'itami' in board.lower()

    @classmethod
    def _CheckNetwork(cls, network):
        return True

    @classmethod
    def _CheckStorage(cls, storage):
        return True

    @property
    def root_disk(self):
        return self._root_disk

    @property
    def serial_unit(self):
        return 0

    @property
    def sysid(self):
        return 'Itami'

    def PrepareBootDevice(self, live_device):
        block_devices = []
        scsi_hosts = platformutils.GetHostSysEntry(proc_name='ahci')
        for host in scsi_hosts:
            block_devices.extend(platformutils.GetBlockDevicesByHost(host, removable=False))

        block_devices = sorted(block_devices)
        logging.info('Detected block devices: %r.', block_devices)
        if block_devices:
            logging.info('Setting %s as root disk.', block_devices[0])
            self._root_disk = block_devices[0]
            return True
        logging.error('Could not find any disks attached to AHCI controller.')
        return False

    def PrepareNetworkDevice(self):
        return True

    def ConfigureRaid(self):
        return True

    def ConfigureBIOS(self):
        return True

    def ConfigureBootOrder(self):
        return True

    def CreateBIOSJobQueue(self):
        return True


class PlatformItami28Disks_MLX(PlatformItami):
    """Itami/Mellanox."""

    @classmethod
    def GetName(cls):
        return 'Itami-28d-mlx'

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX4'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return platformutils.SUPPORTED_SAS_CONTROLLERS['LSISAS3224'] in storage

    @property
    def sysid(self):
        return platformutils.GetPlatformBoard()

    def GetRootDiskPhysicalDriveIds(self):
        return [
         0]


platformutils.RegisterHardwarePlatform(PlatformItami28Disks_MLX)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/platform_itami.pyc
