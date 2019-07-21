# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/platform_hp.py
# Compiled at: 2019-06-18 16:41:38
"""HP platform specific identification implementation."""
__author__ = 'baggins@google.com (Jan Rekorajski)'
import logging
import os
import re
import tempfile
import time
from xml.etree import ElementTree
from defusedxml.cElementTree import parse as defused_parse
from google3.net.bandaid.xt_installer.setup import ifconfig
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils

class PlatformHP(platformutils.PlatformBase):
    """Generic HP machine."""
    DEFAULT_HPSSACLI_PATH = '/usr/sbin/hpssacli'
    DEFAULT_CONREP_PATH = '/sbin/conrep'
    DEFAULT_SETBOOTORDER_PATH = '/sbin/setbootorder'
    DEFAULT_MSTCONFIG_PATH = '/usr/bin/mstconfig'
    DISK_CONTROLLER_COUNT_UNKNOWN = 0
    DISK_CONTROLLER_COUNT_SINGLE = 1
    DISK_CONTROLLER_COUNT_DUAL = 2
    CONTROLLER_MODE_HBA = 'HBA'
    CONTROLLER_MODE_RAID = 'RAID'
    DISK_CONTROLLER_HPSA_ID_UNKNOWN = -1
    DISK_CONTROLLER_HPSA_ID_EMBEDDED = 0
    DISK_CONTROLLER_HPSA_ID_PCI = 1

    def __init__(self):
        super(PlatformHP, self).__init__()
        self._bios_configuration = {}
        self._bios_boot_sequence = []
        self._root_disk = None
        self._skip_reboot = False
        self._quiet = False
        self._dry_run = True
        self._hpssacli_path = self.DEFAULT_HPSSACLI_PATH
        self._conrep_path = self.DEFAULT_CONREP_PATH
        self._setbootorder_path = self.DEFAULT_SETBOOTORDER_PATH
        self._mstconfig_path = self.DEFAULT_MSTCONFIG_PATH
        self._disk_controller_count = self.DISK_CONTROLLER_COUNT_UNKNOWN
        return

    def PassEnv(self, env):
        self._skip_reboot = env.skip_reboot
        self._dry_run = env.dry_run
        self._quiet = env.quiet
        self._hpssacli_path = env.hpssacli_path or self.DEFAULT_HPSSACLI_PATH
        self._conrep_path = env.conrep_path or self.DEFAULT_CONREP_PATH
        self._setbootorder_path = env.setbootorder_path or self.DEFAULT_SETBOOTORDER_PATH
        self._mstconfig_path = env.mstconfig_path or self.DEFAULT_MSTCONFIG_PATH

    @classmethod
    def GetName(cls):
        return 'Generic HP'

    @classmethod
    def Match(cls, sysinfo):
        return cls._CheckVendor(sysinfo['vendor']) and cls._CheckModel(sysinfo['model']) and cls._CheckNetwork(sysinfo['network']) and cls._CheckStorage(sysinfo['storage'])

    @classmethod
    def _CheckVendor(cls, vendor):
        return 'hp' in vendor.lower()

    @classmethod
    def _CheckModel(cls, model):
        return True

    @classmethod
    def _CheckNetwork(cls, network):
        return True

    @classmethod
    def _CheckStorage(cls, storage):
        return True

    @property
    def root_disk(self):
        return self._root_disk

    def PrepareBootDevice(self, live_device):
        """Preliminary boot device configuration.
        
        HP servers must be rebooted if RAID controller mode has been changed.
        Configure RAID mode on the right controller and check if we need to reboot.
        
        Args:
          live_device: device booted from (LiveDevice) (unused).
        
        Returns:
          False if the configuration failed.
        
        Raises:
          RebootNeeded if the machine needs to be rebooted for the changes
              to take effect.
        """
        if not self._InitializeDiskControllerCount():
            return False
        if self._disk_controller_count == self.DISK_CONTROLLER_COUNT_DUAL:
            root_controller_hpsa_id = self.DISK_CONTROLLER_HPSA_ID_PCI
        else:
            root_controller_hpsa_id = self.DISK_CONTROLLER_HPSA_ID_EMBEDDED
        if self._GetControllerMode(root_controller_hpsa_id) == self.CONTROLLER_MODE_HBA:
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d modify hbamode=off forced' % (
             self._hpssacli_path, root_controller_hpsa_id), dry_run=self._dry_run)
            if ret_code != 0:
                logging.error('Failed to disable HBA mode on RAID controller!')
                utils.Print('\nGGC install: RAID configuration error (code: 008).', self._quiet)
                return False
        if self._GetControllerModeRebootRequired(root_controller_hpsa_id) or self._DisableSATARAID():
            utils.Print('A reboot is required to reconfigure RAID controller.', self._quiet)
            if not self._skip_reboot:
                raise platformutils.RebootNeeded
        return True

    def _DisableSATARAID(self):
        """Disable onboard SATA RAID controller if needed.
        
        Returns:
          True if controller mode has been changed to AHCI, False otherwise.
        """
        if not self._GetBIOSConfiguration():
            return False
        if self._GetBIOSOption('Embedded_SATA_Configuration') == 'SATA_AHCI_Enabled':
            return False
        if not self._SetBIOSConfiguration({'Embedded_SATA_Configuration': 'SATA_AHCI_Enabled'}):
            logging.error('Failed to disable onboard SATA RAID controller.')
            return False
        return True

    def _InitializeDiskControllerCount(self):
        """Initialize disk controller count.
        
        Get the number of controllers and store it as self._disk_controller_count.
        
        Returns:
          False if the configuration failed.
        """
        if self._disk_controller_count != self.DISK_CONTROLLER_COUNT_UNKNOWN:
            return True
        hosts = platformutils.GetHostSysEntry(proc_name='hpsa')
        if len(hosts) < 1:
            logging.error('Unexpected number of disk controllers (%d)!', len(hosts))
            utils.Print('\nGGC install: RAID controller(s) not detected (code: 009).', self._quiet)
            return False
        if len(hosts) == 1:
            self._disk_controller_count = self.DISK_CONTROLLER_COUNT_SINGLE
        elif len(hosts) == 2:
            self._disk_controller_count = self.DISK_CONTROLLER_COUNT_DUAL
        elif len(hosts) > 2:
            logging.error('Unexpected number of disk controllers (%d)!', len(hosts))
            utils.Print('\nGGC install: RAID controller detection error (code: 010).', self._quiet)
            return False
        logging.info('Disk controller count = %d', self._disk_controller_count)
        return True

    def PrepareNetworkDevice(self):
        """Set sane ports types on ConnectX3 40G NIC.
        
        Since OOB on HP works only on the 2nd port, set 2nd port to Ethernet
        to force the NIC to always bring up an eth interface, even if nothing is
        plugged in.
        
        Returns:
          Configuration status from ifconfig.ConfigureMellanoxNic()
          or True if no setup is necessary.
        """
        mlx_address = platformutils.GetDevicePciAddress(platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'], True)
        if not mlx_address:
            return True
        vendor_id, device_id = platformutils.GetDeviceSubsystemId(mlx_address)
        if vendor_id == platformutils.PCI_VENDOR_HP and device_id == platformutils.PCI_SUBSYSTEM_DEVICE_HP_MELLANOX40G:
            return ifconfig.ConfigureMellanoxNic(mlx_address, self._mstconfig_path, {1: ifconfig.MLX_LINK_TYPE_INFINIBAND,2: ifconfig.MLX_LINK_TYPE_ETHERNET
               })
        return True

    def _ParseControllerStatus(self, slot, regexp):
        """Find entry in controller status information.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
          regexp: Data to look for in command output (regular expression object).
        
        Returns:
          MatchObject instance if entry was found, None if not found or command
          failure.
        """
        stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d show' % (self._hpssacli_path, slot), dry_run=self._dry_run)
        if ret_code != 0:
            return None
        else:
            for line in stdout.splitlines():
                entry = regexp.match(line)
                if entry:
                    return entry

            return None

    def _GetControllerMode(self, slot):
        """Find what operating mode is set on the controller.
        
        Find if specified controller is running in RAID or HBA mode.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
        
        Returns:
          One of self.CONTROLLER_MODE_HBA or self.CONTROLLER_MODE_RAID string
          constants or None if there were errors running hpssacli tool or hpssacli
          did not return required information.
        """
        mode_re = re.compile('^\\s*Controller Mode: (?P<Mode>(%s|%s))$' % (
         self.CONTROLLER_MODE_RAID, self.CONTROLLER_MODE_HBA))
        entry = self._ParseControllerStatus(slot, mode_re)
        if entry:
            return entry.group('Mode')
        else:
            return None

    def _GetControllerModeRebootRequired(self, slot):
        """Find if the machine must be rebooted after controller mode change.
        
        Find if we must reboot the machine after changing controller operating mode
        between RAID and HBA for the change to take effect.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
        
        Returns:
          True if reboot is required, False otherwise.
        """
        reboot_re = re.compile('^\\s*Controller Mode Reboot: (?P<Reboot>(Not )?Required)$')
        entry = self._ParseControllerStatus(slot, reboot_re)
        if entry:
            if 'Not' in entry.group('Reboot'):
                return False
            else:
                return True

        return False

    def _GetControllerHost(self, slot):
        """Find sysfs SCSI host corresponding to HPSA controller slot.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
        
        Returns:
          Sysfs SCSI host name for specified HPSA slot or None in case of errors.
        """
        pci_re = re.compile('^\\s*PCI Address \\(Domain:Bus:Device.Function\\): (?P<PCI>\\d+:\\d+:\\d+\\.\\d+)$')
        entry = self._ParseControllerStatus(slot, pci_re)
        if entry:
            return platformutils.GetHostFromPCI(entry.group('PCI'))
        else:
            return None

    def _ClearControllerConfiguration(self, slot, host):
        """Clear controller configuration and remove all defined logical devices.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
          host: Sysfs SCSI host identifier (str)
        
        Returns:
          True if clearing configuration succeeded, False in case of errors.
        """
        if self._GetControllerMode(slot) == self.CONTROLLER_MODE_HBA:
            logging.info('Controller in slot %d is set to HBA mode, configuration clearing skipped.', slot)
            return True
        stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d clearencryptionconfig forced' % (
         self._hpssacli_path, slot), dry_run=self._dry_run)
        if ret_code != 0:
            if 'Encryption must be enabled using' not in stdout:
                return False
        if not self._GetLDList(slot):
            logging.info('Controller in slot %d does not have any logical drives, configuration clearing skipped.', slot)
            return True
        unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d delete forced' % (self._hpssacli_path, slot), dry_run=self._dry_run)
        if ret_code != 0:
            return False
        platformutils.RescanScsiHost(host)
        timeout = 60
        while platformutils.GetBlockDevicesByHost(host):
            time.sleep(1)
            timeout -= 1
            if timeout == 0:
                return False

        return True

    def _ConfigureMirroredRootDisk(self, slot, drive_ids, physical_drives):
        """Configures a RAID 1 array.
        
        Arguments:
          slot: The controller slot as understood by hpssacli tool (int).
          drive_ids: List of physical disk ids that should be part of the array.
          physical_drives: List of physical drives
        
        Returns:
          True if the RAID array was created, False in case of errors.
        """
        raid_members = []
        for candidate in drive_ids:
            if candidate in physical_drives:
                raid_members.append(candidate)

        if not raid_members:
            logging.error('Not enough physical drives to build the root logical drive!')
            utils.Print('\nGGC install: RAID configuration error (code: 003).', self._quiet)
            return False
        logging.info('Configuring the boot logical drive with these members: [%s]', ','.join(raid_members))
        raid_level = 1 if len(raid_members) > 1 else 0
        logging.info('Creating RAID %s logical disk with disks at slots: %s.', raid_level, ','.join(map(str, raid_members)))
        unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d create type=ld drives=%s raid=%d forced' % (
         self._hpssacli_path, slot, ','.join(raid_members), raid_level), dry_run=self._dry_run)
        if ret_code != 0:
            logging.warning('Failed to create boot logical drive!')
            return False
        return True

    def _GetPDList(self, slot):
        """Get information about the physical drives from the RAID controller.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
        
        Returns:
          An set of physical drive ids.
        """
        pdlist = set()
        stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%s pd all show' % (self._hpssacli_path, slot), dry_run=self._dry_run)
        if ret_code == 0:
            pd_re = re.compile('^\\s*physicaldrive (?P<Id>[\\w:]+) \\(.*, OK\\)$')
            for line in stdout.splitlines():
                entry = pd_re.match(line)
                if entry:
                    pdlist.add(entry.group('Id'))

        else:
            logging.warning('Failed to get the list of physical drives from controller in slot=%s', slot)
        return pdlist

    def _GetLDList(self, slot):
        """Get information about the logical drives from the RAID controller.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
        
        Returns:
          An set of logical drive ids.
        """
        ldlist = set()
        stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%s ld all show' % (self._hpssacli_path, slot), dry_run=self._dry_run)
        if ret_code == 0:
            ld_re = re.compile('^\\s*logicaldrive (?P<Id>\\d+) \\(.*\\)$')
            for line in stdout.splitlines():
                entry = ld_re.match(line)
                if entry:
                    ldlist.add(int(entry.group('Id')))

        else:
            logging.warning('Failed to get the list of logical drives from controller in slot=%s', slot)
        return ldlist

    def _ConfigureHBAController(self, slot, host):
        """Configure secondary SCSI controller in HBA mode.
        
        Args:
          slot: The controller slot as understood by hpssacli tool (int).
          host: Sysfs SCSI host identifier (str)
        """
        if not self._ClearControllerConfiguration(slot, host):
            logging.warning('Failed to clear SAS controller configuration!')
        if self._GetControllerMode(slot) != self.CONTROLLER_MODE_HBA:
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s controller slot=%d modify hbamode=on forced' % (
             self._hpssacli_path, slot), dry_run=self._dry_run)
            if ret_code != 0:
                logging.warning('Failed to set SAS controller to HBA mode!')
        utils.RunCommand('%s controller slot=%d modify drivewritecache=disable' % (
         self._hpssacli_path, slot), dry_run=self._dry_run)

    def ConfigureRaid(self):
        """Configures RAID controllers.
        
        This function configures the RAID controller and updates the object.
        
        Returns:
          True if the RAID controller has been configured correctly; False if there
          was an error.
        """
        if not self._InitializeDiskControllerCount():
            return False
        if self._disk_controller_count == self.DISK_CONTROLLER_COUNT_DUAL:
            root_controller_hpsa_id = self.DISK_CONTROLLER_HPSA_ID_PCI
            data_host = self._GetControllerHost(self.DISK_CONTROLLER_HPSA_ID_EMBEDDED)
            if not data_host:
                logging.error('Cannot find SCSI controller for data disks!')
                return False
            self._ConfigureHBAController(self.DISK_CONTROLLER_HPSA_ID_EMBEDDED, data_host)
        elif self._disk_controller_count == self.DISK_CONTROLLER_COUNT_SINGLE:
            root_controller_hpsa_id = self.DISK_CONTROLLER_HPSA_ID_EMBEDDED
        else:
            logging.error('Unsupported disk controller count (%d)', self._disk_controller_count)
            return False
        root_host = self._GetControllerHost(root_controller_hpsa_id)
        if not root_host:
            logging.error('Cannot find SCSI controller for root disks!')
            return False
        if not self._ClearControllerConfiguration(root_controller_hpsa_id, root_host):
            logging.warning('Failed to clear RAID controller configuration!')
            utils.Print('\nGGC install: RAID configuration error (code: 001).', self._quiet)
            return False
        if self._GetLDList(root_controller_hpsa_id):
            logging.error('Logical drives left after a CfgClr!')
            utils.Print('\nGGC install: RAID configuration error (code: 001).', self._quiet)
            return False
        physical_drives = self._GetPDList(root_controller_hpsa_id)
        if not physical_drives:
            logging.error("Can't retrieve the list of physical drives!")
            utils.Print('\nGGC install: RAID configuration error (code: 002).', self._quiet)
            return False
        if not self._ConfigureMirroredRootDisk(root_controller_hpsa_id, self.GetRootDiskPhysicalDriveIds(), physical_drives):
            return False
        platformutils.RescanScsiHost(root_host)
        if len(self._GetLDList(root_controller_hpsa_id)) != 1:
            logging.info('Unexpected logical drive configuration after initialization!')
            utils.Print('\nGGC install: RAID configuration error (code: 005).', self._quiet)
            return False
        unused_stdout, unused_err, ret_code = utils.RunCommand('%s controller slot=%d ld 1 modify bootvolume=primary' % (
         self._hpssacli_path, root_controller_hpsa_id), dry_run=self._dry_run)
        if ret_code:
            logging.info('Cannot set the controller boot device!')
            utils.Print('\nGGC install: RAID configuration error (code: 006).', self._quiet)
            return False
        utils.RunCommand('%s controller slot=%d modify drivewritecache=disable' % (
         self._hpssacli_path, root_controller_hpsa_id), dry_run=self._dry_run)
        block_devices = platformutils.GetBlockDevicesByHost(root_host)
        if len(block_devices) != 1:
            logging.error('Unexpected number of devices (%d)!', len(block_devices))
            utils.Print('\nGGC install: RAID configuration error (code: 007).', self._quiet)
            return False
        self._root_disk = block_devices[0]
        logging.info('Root logical device: %s', self._root_disk)
        return True

    def _GetBIOSConfiguration(self):
        """Read the current BIOS configuration.
        
        Get the current configuration for a HP machine using conrep tool
        and parse returned XML data into a dict.
        
        Returns:
          True if the data has been read correctly, False if there are any errors.
        """
        temp_dir = tempfile.mkdtemp()
        conrep_xml_path = os.path.join(temp_dir, 'conrep.xml')
        unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -s -f %s' % (self._conrep_path, conrep_xml_path), dry_run=self._dry_run)
        if ret_code != 0:
            return False
        try:
            xml_tree = defused_parse(conrep_xml_path)
        except IOError:
            logging.exception('Unable to open conrep XML file %s', conrep_xml_path)
            return False
        except ElementTree.ParseError:
            logging.exception('Unable to parse conrep XML file %s', conrep_xml_path)
            return False

        xml_root = xml_tree.getroot()
        if xml_root.tag != 'Conrep':
            logging.error("Malformed conrep XML, invalid root element '%s'.", xml_root.tag)
            return False
        for child in xml_root:
            if child.tag != 'Section':
                logging.warning("Unknown element '%s' in conrep XML.", child.tag)
                continue
            if 'name' not in child.attrib:
                logging.warning("Malformed conrep XML, 'name' attribute is missing for tag '%s'", child.tag)
                continue
            self._bios_configuration[child.attrib['name']] = child.text

        return True

    def _SetBIOSConfiguration(self, bios_config):
        """Set BIOS configuration.
        
        Load BIOS configuration to a HP machine using conrep tool.
        
        Args:
          bios_config: Dictionary with the keys and values of BIOS settings we want
                       to configure.
        
        Returns:
          True if setting BIOS configuration succeeded, False if there are any
          errors.
        """
        temp_dir = tempfile.mkdtemp()
        conrep_xml_path = os.path.join(temp_dir, 'conrep.xml')
        conrep_xml_tree = self._CreateConrepXML(bios_config)
        try:
            conrep_xml_tree.write(conrep_xml_path, encoding='UTF-8')
        except IOError:
            logging.error('Error saving conrep XML file %s', conrep_xml_path)
            return False

        unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -l -f %s' % (self._conrep_path, conrep_xml_path), dry_run=self._dry_run)
        if ret_code != 0:
            return False
        return True

    def _CreateConrepXML(self, bios_config):
        """Serialize BIOS configuration into xml.ElementTree hierarchy.
        
        Build xml.ElementTree hierarchy from provided dictionary in conrep format:
        
        <Conrep>
          <Section name='option'>value</Section>
          ...
        </Conrep>
        
        Args:
          bios_config: Dictionary with the keys and values of BIOS settings we want
                       to configure.
        
        Returns:
          xml.ElementTree.ElementTree hierarchy with conrep data.
        """
        conrep_xml = ElementTree.Element('Conrep')
        if bios_config:
            for item, text in bios_config.iteritems():
                child_xml = ElementTree.SubElement(conrep_xml, 'Section', name=item)
                child_xml.text = text

        return ElementTree.ElementTree(element=conrep_xml)

    def _GetBIOSOption(self, option):
        """Get BIOS option value.
        
        Args:
          option: Name of the option to get.
        
        Returns:
          Value of the option or None if it does not exist.
        """
        if option in self._bios_configuration:
            return self._bios_configuration[option]
        else:
            return None

    def ConfigureBIOS(self):
        """Setup BIOS with sane defaults.
        
        Returns:
          True
        """
        success = True
        new_config = {}
        if self._GetBIOSConfiguration():
            if self._GetBIOSOption('Boot_Mode') != 'Legacy_BIOS_Mode':
                new_config['Boot_Mode'] = 'Legacy_BIOS_Mode'
            if self._GetBIOSOption('Embedded_SATA_Configuration') != 'SATA_AHCI_Enabled':
                new_config['Embedded_SATA_Configuration'] = 'SATA_AHCI_Enabled'
            if self._GetBIOSOption('POST_F1_Prompt') != 'Delayed':
                new_config['POST_F1_Prompt'] = 'Delayed'
            if self._GetBIOSOption('System_Virtual_Serial_Port') != 'COM2':
                new_config['System_Virtual_Serial_Port'] = 'COM2'
        else:
            success = False
        if new_config:
            success = self._SetBIOSConfiguration(new_config)
        if not success:
            utils.Print('WARNING: BIOS settings update failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def _GetBootSequence(self):
        """Get current boot sequence.
        
        Returns:
          True if getting data succeeded, False if there are errors.
        """
        stdout, unused_stderr, ret_code = utils.RunCommand(self._setbootorder_path, dry_run=self._dry_run)
        if ret_code != 0:
            return False
        stdout_lines = stdout.splitlines(False)
        if not stdout_lines:
            return False
        boot_order = stdout_lines[0]
        prefix = 'Current Boot Order: '
        if not boot_order.startswith(prefix):
            return False
        self._bios_boot_sequence = boot_order[len(prefix):].split()
        logging.info('Current BIOS boot sequence: %s', ','.join(self._bios_boot_sequence))
        return True

    def ConfigureBootOrder(self):
        """Set boot sequence to HD first.
        
        Returns:
          True
        """
        success = True
        if not self._GetBootSequence():
            success = False
        new_boot_sequence = list(self._bios_boot_sequence)
        if 'hd' in self._bios_boot_sequence:
            new_boot_sequence.remove('hd')
            new_boot_sequence.insert(0, 'hd')
        else:
            success = False
        if new_boot_sequence != self._bios_boot_sequence:
            logging.info('Setting the BIOS boot sequence to: %s', ','.join(new_boot_sequence))
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s %s' % (self._setbootorder_path, ' '.join(new_boot_sequence)), dry_run=self._dry_run)
            if ret_code != 0:
                logging.info('Cannot set BIOS boot sequence to: %s!', ','.join(new_boot_sequence))
                success = False
        if not success:
            utils.Print('WARNING: BIOS boot order update failed. Please notify ggc@google.com if the next reboot fails.', self._quiet)
        return True

    def CreateBIOSJobQueue(self):
        return True


class PlatformHPApollo4200_MLX(PlatformHP):
    """HP Apollo 4200/Mellanox."""

    @classmethod
    def GetName(cls):
        return 'HP-Apollo-4200-mlx'

    @classmethod
    def _CheckModel(cls, model):
        return 'XL420' in model

    @classmethod
    def _CheckNetwork(cls, network):
        return platformutils.SUPPORTED_NETWORK_CARDS['MT27520'] in network or platformutils.SUPPORTED_NETWORK_CARDS['MLX_ConnectX3'] in network

    @classmethod
    def _CheckStorage(cls, storage):
        return any([
         platformutils.SUPPORTED_RAID_CONTROLLERS['HPSA'] in storage,
         platformutils.SUPPORTED_SAS_CONTROLLERS['HPSA'] in storage])

    def GetRootDiskPhysicalDriveIds(self):
        if not self._InitializeDiskControllerCount():
            return []
        if self._disk_controller_count == self.DISK_CONTROLLER_COUNT_SINGLE:
            return ['2I:1:1', '2I:1:2']
        if self._disk_controller_count == self.DISK_CONTROLLER_COUNT_DUAL:
            return ['1I:1:51', '1I:1:52']
        return []


platformutils.RegisterHardwarePlatform(PlatformHPApollo4200_MLX)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/platform_hp.pyc
