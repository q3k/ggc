# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/installer.py
# Compiled at: 2019-06-18 16:41:38
"""Runs the Dell installer.

This file directs the overall flow of the Dell installer.  It does the
following:

  - retrieves system information
  - prompts user for configuration information
  - configures RAID controller
  - partitions disks
  - unpacks install-image tarball to future root partition
  - writes minimal network configuration
  - writes /etc/fstab
  - configures bootloader
  - sets root password
  - reboots

Each step is implemented as a method of the Installer class.
"""
__author__ = 'devink@google.com (Devin Kennedy)'
import base64
import crypt
import errno
import httplib
import logging
import os
import re
import stat
import sys
import urllib
import urlparse
import zlib
import ipaddr
from google3.net.bandaid.xt_installer.setup import callhome
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils

class Error(Exception):
    """Base class for all module errors."""
    pass


class LinkLocationError(Error):
    """Raised when link is not detected on first port of configured NIC."""
    pass


class LinkMismatchError(Error):
    """Raised when link is detected on different NIC that is configured."""
    pass


class Installer(object):
    """Tracks the state of the installation.
    
    This class holds all state related to the progress and configuration of the
    current installation.
    
    This is a generic class covering support for XT, XT+ and Islands deployments.
    
    """
    PLATFORM = 'GGC'
    MIN_PREFIX_LEN = 24
    MAX_PREFIX_LEN = 28
    FIRST_HOST_INDEX = 4
    LAST_HOST_INDEX = 19
    GATEWAY_INDEX = 1
    IPV6_PREFIX_LEN = 64
    _DOWNLOAD_URL = 'http://dl.google.com/ggc/install/ggc-setup-latest.img'
    _DOWNLOAD_URL_RE = re.compile('.*/ggc-setup[^0-9]*([0-9_\\.]+).img')

    def __init__(self, machine, configuration, logger, quiet=False, dry_run=False, debug_mode=False, allow_any_ipv6=False, allow_special_ip=False, install_fs='ext2', install_mountpoint='/mnt', ping_options='-n -c 4 -w 4 -i0.3', ping_retries=15, prospective_root_partition='/dev/sda1', remote_logging_url='http://cache-management-prod.google.com/mgmt/machine/checkin/', install_srcpath='/install', persistent_log_path='var/log', grub_install_path='/usr/sbin/grub-install', arping_path='/usr/bin/arping', ifdown_path='/sbin/ifdown', ifup_path='/sbin/ifup', parted_path='/sbin/parted', udevadm_path='/sbin/udevadm', ggc_boot_root='/', proc_cmdline='/proc/cmdline', timeout=30):
        """Initialize Installer object.
        
        Args:
          machine: instance of machine.Machine or derived class.
          configuration: instance of installer.Configuration class.
          logger: instance of utils.Logger class.
          quiet: Do not print detailed messages in user prompts (bool).
          dry_run: Do not run external commands (bool).
          debug_mode: Run the program in debug mode (bool).
          allow_any_ipv6: Allow use of any IPv6 address space (bool).
          allow_special_ip: Allow installation in special-purpose networks (e.g.
                            private IPv4 networks) (bool).
          install_fs: File system for the Install Image (str).
          install_mountpoint: Mountpoint for the Install Image (str).
          ping_options: Ping probe options (str).
          ping_retries: Number of pings to try (int).
          prospective_root_partition: Partition to use for Install Image (str).
          remote_logging_url: URL for machine registration and installation log
                              upload (str).
          install_srcpath: Path to the Install Image source (str).
          persistent_log_path: Path relative to the install image where
                               logs are stored (str).
          grub_install_path: Path to grub-install program (str).
          arping_path: Path to arping (str).
          ifdown_path: Path to ifdown script (str).
          ifup_path: Path to ifup script (str).
          parted_path: Path to parted program (str).
          udevadm_path: Path to udevadm program (str).
          ggc_boot_root: Path to root filesystem of ggc-boot stage (str).
          proc_cmdline: Path to the file containing kernel parameters (str).
          timeout: HTTP connection timeout (int).
        """
        self.machine = machine
        self.config = configuration
        self.logger = logger
        self._quiet = quiet
        self._dry_run = dry_run
        self._debug_mode = debug_mode
        self._allow_any_ipv6 = allow_any_ipv6
        self._allow_special_ip = allow_special_ip
        self._install_fs = install_fs
        self._install_mountpoint = install_mountpoint
        self._ping_options = ping_options
        self._ping_retries = ping_retries
        self._remote_logging_url = remote_logging_url
        self._root_partition = prospective_root_partition
        self._grub_install_path = grub_install_path
        self._install_srcpath = install_srcpath
        self._persistent_log_path = persistent_log_path
        self._arping_path = arping_path
        self._ifdown_path = ifdown_path
        self._ifup_path = ifup_path
        self._parted_path = parted_path
        self._udevadm_path = udevadm_path
        self._ggc_boot_root = ggc_boot_root
        self._proc_cmdline = proc_cmdline
        self._timeout = timeout
        self._interfaces_to_configure = []
        self._lacp_guess = True
        self._network_connectivity = False
        self._version = None
        self._version_full = None
        self._kmod_blacklist = None
        self._steps = []
        self.SetSteps(self.DEFAULT_STEPS)
        return

    DEFAULT_STEPS = [
     'gathernicinformation',
     'read_start_check_network',
     'checkinstallerversion',
     'gathersysteminformation',
     'configureraid',
     'partitiondisks',
     'mkfs',
     'mountinstallimage',
     'copyinstallimage',
     'writenetworkconfiguration',
     'writeresolvconf',
     'writehosts',
     'writefstab',
     'configurebootloader',
     'registermachine',
     'configurebios',
     'configurebootorder',
     'createbiosjobqueue',
     'setpassword',
     'finalizeinstall',
     'writelogstoimage',
     'unmountinstallimage']

    class InvalidParameterError(Exception):
        pass

    class Operation(object):
        REGISTER = 'REGISTER'
        INSTALL_SUCCEEDED = 'INSTALL_SUCCEEDED'
        INSTALL_FAILED = 'INSTALL_FAILED'

    def ReadVersion(self, root='/'):
        """Read installer image version from /etc/ggc_version.
        
        Store version identifier in self._version, full contents of the file in
        self._version_full for password generation.
        
        Args:
          root: system root location.
        """
        installer_version_re = re.compile('^[^0-9]*([0-9\\.]+).*$')
        ggc_version_path = os.path.join(root, 'etc/ggc_version')
        try:
            with open(ggc_version_path, 'r') as version_fd:
                version_str = version_fd.readline().strip()
                match = installer_version_re.match(version_str)
                if not match:
                    logging.error('%s has invalid contents: %r', ggc_version_path, version_str)
                else:
                    self._version = match.group(1)
                    self._version_full = version_str
        except IOError:
            logging.exception('Cannot access %s.', ggc_version_path)

    def SetSteps(self, stepnames_list):
        """Set the sequence of steps we want to execute.
        
        Args:
          stepnames_list: list of step names we intend to run.
        
        Raises:
          InvalidParameterError: invalid parameter.
        """
        steps_by_name = {'gathernicinformation': self.GatherNicInformation,
           'gathersysteminformation': self.GatherSystemInformation,
           'getnicconfiguration': self.GetNicConfigFromUser,
           'readconfigurationfromstdin': self.GetNetworkConfigFromUser,
           'reconfigurenetwork': self.ReconfigureNetwork,
           'checknetworkconnectivity': self.CheckNetworkConnectivity,
           'read_start_check_network': self.ReadStartCheckNetwork,
           'checkinstallerversion': self.CheckInstallerVersion,
           'configureraid': self.ConfigureRaid,
           'partitiondisks': self.PartitionDisks,
           'mkfs': self.MkFs,
           'mountinstallimage': self.MountInstallImage,
           'copyinstallimage': self.CopyInstallImage,
           'writenetworkconfiguration': self.WriteNetworkConfiguration,
           'writeresolvconf': self.WriteResolvConf,
           'writehosts': self.WriteHosts,
           'writefstab': self.WriteFstab,
           'configurebootloader': self.ConfigureBootloader,
           'registermachine': self.RegisterMachine,
           'configurebios': self.ConfigureBIOS,
           'configurebootorder': self.ConfigureBootOrder,
           'createbiosjobqueue': self.CreateBIOSJobQueue,
           'setpassword': self.SetRootPassword,
           'finalizeinstall': self.FinalizeInstall,
           'writelogstoimage': self.WriteLogsToImage,
           'unmountinstallimage': self.UMountInstallImage
           }
        steps_to_skip = []
        if self.config.pxe:
            steps_to_skip = [
             'configurebootorder']
        self._steps = []
        for step_name in stepnames_list:
            if step_name in steps_to_skip:
                logging.info('Not adding step %s to sequence.', step_name)
                continue
            step = steps_by_name.get(step_name, None)
            if step is None:
                raise Installer.InvalidParameterError('Invalid step "%s".' % step_name)
            self._steps.append(step)

        return

    def Run(self):
        """Execute the steps we set with SetSteps."""
        self.ReadVersion()
        logging.info('Running installer version: %s', self._version or 'UNKNOWN')
        self.SetRootPassword(root='/')
        print 'Starting %s installer, version %s.' % (
         self.PLATFORM, self._version or 'unknown')
        print
        logging.info('Starting %s installer.', self.PLATFORM)
        success = True
        for step in self._steps:
            logging.info("Starting step '%s'...", step.func_name)
            if step():
                logging.info("Completed step '%s'.", step.func_name)
            else:
                logging.info("Failed step '%s'!", step.func_name)
                success = False
                break

        if self._network_connectivity:
            self.UploadLog(success)
        return success

    def CheckInstallerVersion(self):
        """Check if running image version is latest.
        
        Compare running image version with latest available for download, based on
        a known, stable URL.
        
        Returns:
          True. If there is version mismatch installer will complain but mismatch
          itself should not block installation.
        """
        if not self._network_connectivity:
            logging.info('Unable to verify if the installer image is latest: no network connectivity.')
            return True
        if not self._version:
            logging.info('Unable to verify if the installer image is latest: local version is unknown.')
            return True
        parsed_url = urlparse.urlparse(self._DOWNLOAD_URL, allow_fragments=True)
        conn = httplib.HTTPConnection(parsed_url.netloc, timeout=self._timeout)
        try:
            conn.request('HEAD', parsed_url.path)
            http_response = conn.getresponse()
            http_headers = dict(http_response.getheaders())
            if 'location' not in http_headers:
                logging.info('Unable to verify if the installer image is latest: unable to fetch HTTP headers for %s (status: %s).', self._DOWNLOAD_URL, str(http_response.status))
                return True
            versioned_url = http_headers['location']
        except (IOError, httplib.HTTPException):
            logging.exception('Unable to verify if the installer image is latest')
            return True

        match = self._DOWNLOAD_URL_RE.match(versioned_url)
        if not match:
            logging.info('Unable to verify if the installer image is latest: cannot find version in dowload URL %s.', versioned_url)
            return True
        dotted_version = match.group(1).replace('_', '.')
        logging.info('Latest installer version is %s, running version is %s', dotted_version, self._version)
        if dotted_version != self._version:
            print '\nWARNING: '.join([
             '',
             'This GGC Install Image is out of date.',
             'Latest version: {latest}, running version: {running}.',
             'Please use the latest image in case of installation problems.',
             'Please refer to the GGC Installation Guide for details\n']).format(latest=dotted_version, running=self._version)
        return True

    def ValidateIPConfig(self, network, address, allow_special_ip=False, allow_any_ipv6=False):
        """Checks an IP configuration for validity.
        
        Arguments:
          network: IP network as ipaddr.IPNetwork.
          address: IP host address as ipaddr.IPAddress.
          allow_special_ip: whether to accept private IP address
          allow_any_ipv6: whether to accept any IPv6 address.
        
        Returns:
          A list of strings with reasons why the configuration has been rejected.
          An empty list if the configuration is valid.
        """
        if address.version == 6:
            return self._ValidateIPv6Config(network=network, address=address, allow_any_ipv6=allow_any_ipv6)
        return self._ValidateIPv4Config(network=network, address=address, allow_special_ip=allow_special_ip)

    def _ValidateIPv6Config(self, network, address, allow_any_ipv6=False):
        """Checks an ipv6 configuration for validity.
        
        Arguments:
          network: IPv6 network as ipaddr.IPv6Network.
          address: IPv6 host address as ipaddr.IPAddress.
          allow_any_ipv6: whether to accept any IPv6 address.
        
        Returns:
          A list of strings with reasons why the configuration has been rejected.
          An empty list if the configuration is valid.
        """
        result = []
        if not allow_any_ipv6 and address not in ipaddr.IPNetwork('2000::/3'):
            result.append('Only Global Unicast (2000::/3) IPv6 addresses are allowed.')
        if address == network.network:
            result.append('Invalid IP for this netmask (network IP).')
        if address == network.broadcast:
            result.append('Invalid IP for this netmask (broadcast IP).')
        if address not in network:
            result.append('IP not within the specified network.')
        if network.prefixlen != self.IPV6_PREFIX_LEN:
            result.append('Invalid network bitmask (prefix length must be %d).' % self.IPV6_PREFIX_LEN)
        elif network.network < address < network[self.FIRST_HOST_INDEX]:
            result.append('This IP shall not be used for any GGC server.')
        elif network[self.LAST_HOST_INDEX] < address < network.broadcast:
            result.append('This IP is reserved for the node.')
        return result

    def _ValidateIPv4Config(self, network, address, allow_special_ip=False):
        """Checks an ipv4 configuration for validity.
        
        Arguments:
          network: network/netmask as ipaddr.IPNetwork
          address: host address as ipaddr.IPAddress
          allow_special_ip: whether to accept private IP address
        
        Returns:
          A list of strings with reasons why the configuration has been rejected.
          An empty list if the configuration is valid.
        """
        result = []
        special_ip_networks = (
         ipaddr.IPv4Network('0.0.0.0/8'),
         ipaddr.IPv4Network('10.0.0.0/8'),
         ipaddr.IPv4Network('100.64.0.0/10'),
         ipaddr.IPv4Network('127.0.0.0/8'),
         ipaddr.IPv4Network('169.254.0.0/16'),
         ipaddr.IPv4Network('172.16.0.0/12'),
         ipaddr.IPv4Network('192.0.0.0/24'),
         ipaddr.IPv4Network('192.0.2.0/24'),
         ipaddr.IPv4Network('192.88.99.0/24'),
         ipaddr.IPv4Network('192.168.0.0/16'),
         ipaddr.IPv4Network('198.18.0.0/15'),
         ipaddr.IPv4Network('198.51.100.0/24'),
         ipaddr.IPv4Network('203.0.113.0/24'),
         ipaddr.IPv4Network('224.0.0.0/4'),
         ipaddr.IPv4Network('240.0.0.0/4'))
        if address == network.network:
            result.append('Invalid IP for this netmask (network IP).')
        if address == network.broadcast:
            result.append('Invalid IP for this netmask (broadcast IP).')
        if ipaddr.IPAddress(address) not in network:
            result.append('IP not within the specified network.')
        if not self.MIN_PREFIX_LEN <= network.prefixlen <= self.MAX_PREFIX_LEN:
            result.append('Invalid network bitmask (prefix length must be between %d and %d).' % (
             self.MIN_PREFIX_LEN, self.MAX_PREFIX_LEN))
        elif network.network < address < network[self.FIRST_HOST_INDEX]:
            result.append('This IP is reserved for the gateway and HSRP/GLBP.')
        elif network[min(self.LAST_HOST_INDEX, network.numhosts - 1)] < address < network.broadcast:
            result.append('This IP is reserved for the node.')
        if any((network.overlaps(reserved_net) for reserved_net in special_ip_networks)):
            if allow_special_ip:
                logging.warning('Network overlaps special_ip_networks.')
            else:
                result.append('The specified network overlaps a reserved network.')
        if any((address in network for network in special_ip_networks)):
            if allow_special_ip:
                logging.warning('IP in special_ip_networks.')
            else:
                result.append('This IP is in a reserved network.')
        return result

    def WriteEtcNetworkInterfaces(self, root='/'):
        """Writes /etc/network/interfaces.
        
        This function writes a Debian network config file based on the state.
        
        Arguments:
          root: system root location.
        
        Returns:
          False if there was an error.
        """
        interfaces = [ iface.name for iface in self._interfaces_to_configure ]
        if not interfaces:
            return False
        fname = os.path.join(root, 'etc/network/interfaces')
        inet_family = 'inet'
        if ipaddr.IPAddress(self.config.ipaddress).version == 6:
            inet_family = 'inet6'
        if self.config.lacp:
            interfaces = '# GGC installer network configuration\nauto lo bond0\n\n# The loopback network interface\niface lo inet loopback\n\n# The bonded network interface\niface bond0 %s static\n     bond-mode 802.3ad\n     bond-miimon 100\n     bond-xmit-hash-policy layer3+4\n     bond-lacp-rate slow\n     bond-slaves %s\n     address %s\n     netmask %s\n' % (
             inet_family,
             ' '.join(interfaces),
             self.config.ipaddress,
             self.config.netmask)
        else:
            interfaces = '# GGC installer network configuration\nauto lo %s\n\n# The loopback network interface\niface lo inet loopback\n\n# The plain Ethernet network interface\niface %s %s static\n     address %s\n     netmask %s\n' % (
             interfaces[0],
             interfaces[0],
             inet_family,
             self.config.ipaddress,
             self.config.netmask)
        if ipaddr.IPAddress(self.config.ipaddress).version == 6:
            interfaces += '     # Fallback route in case there are no RAs present\n     post-up ip -6 route add default via %s metric 1025\n' % self.config.gateway
        else:
            interfaces += '     gateway %s\n' % self.config.gateway
        try:
            with open(fname, 'w') as f:
                f.write(interfaces)
        except IOError:
            logging.error('Cannot write %s', fname)
            return False

        return True

    def _ConfirmDetectedNicLink(self):
        """Propose which NIC(s) need to configure and ask for confirmation.
        
        This function verifies NICs available for configuration, asks user for
        confirmation and stores the data in the object.
        
        NIC selection order:
        - no 10Ge -> configure all NICs in LACP bundle ignoring link state
        - NICs with link:
          - 1Ge -> all 1Ge NICs in LACP bundle
          - 10Ge -> connected 10Ge NICs, LACP enabled if more than one NIC with link
        
        There is no differentiation between builtin and addon (Mellanox) 10Ge NICs.
        
        Returns:
          Boolean indicating if user confirmed proposed configuration.
        """
        if not self.machine.ten_ge_interfaces and not self.machine.forty_ge_interfaces:
            self._lacp_guess = True
            self._interfaces_to_configure = self.machine.interfaces
            return True
        forty_ge_ifaces_up = [ iface for iface in self.machine.forty_ge_interfaces if iface in self.machine.interfaces_with_link
                             ]
        ten_ge_ifaces_up = [ iface for iface in self.machine.ten_ge_interfaces if iface in self.machine.interfaces_with_link
                           ]
        one_ge_ifaces_up = [ iface for iface in self.machine.one_ge_interfaces if iface in self.machine.interfaces_with_link
                           ]
        if forty_ge_ifaces_up:
            self._lacp_guess = False
            self._interfaces_to_configure = forty_ge_ifaces_up
            if not self.config.prompt:
                return True
            print 'Link has been detected on 40Ge NIC.'
            return utils.PromptUserForBool(prompt='Do you want to configure this NIC?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
        if len(ten_ge_ifaces_up) == 1:
            self._lacp_guess = False
            self._interfaces_to_configure = ten_ge_ifaces_up
            if not self.config.prompt:
                return True
            print 'Link has been detected on 10Ge NIC.'
            return utils.PromptUserForBool(prompt='Do you want to configure this NIC?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
        if len(ten_ge_ifaces_up) > 1:
            self._lacp_guess = True
            self._interfaces_to_configure = ten_ge_ifaces_up
            if not self.config.prompt:
                return True
            print 'Link has been detected on 10Ge NICs.'
            return utils.PromptUserForBool(prompt='Do you want to configure these NICs?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
        if one_ge_ifaces_up:
            self._lacp_guess = True
            self._interfaces_to_configure = self.machine.one_ge_interfaces
            if not self.config.prompt:
                return True
            print 'Link has been detected on 1Ge NICs.'
            return utils.PromptUserForBool(prompt='Do you want to configure these NICs?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
        return False

    def _PromptUserForNicConfiguration(self):
        """Query user for NIC configuration.
        
        If addon (Mellanox) 10Ge NIC is present it will be selected if user
        chooses to configure 10Ge NIC(s).
        """
        self._lacp_guess = True
        self._interfaces_to_configure = self.machine.interfaces
        if not self.config.prompt:
            return
        else:
            print 'Please choose link settings for this machine from the options below:'
            print '[1] Configure a standalone 10Ge interface.'
            print '[2] Configure a LACP bundle of 1Ge interfaces.'
            print '[3] Configure a LACP bundle of 10Ge interfaces.'
            print '[4] Configure a standalone 40Ge interface.'
            choice = utils.PromptUserForChoice(prompt='Choose option 1 or 2 or 3 or 4', choices=('1',
                                                                                                 '2',
                                                                                                 '3',
                                                                                                 '4'), default=None, quiet=self._quiet, debug_mode=self._debug_mode)
            if choice == '1':
                self._lacp_guess = False
                if self.machine.mlx_interfaces:
                    self._interfaces_to_configure = self.machine.mlx_interfaces
                else:
                    self._interfaces_to_configure = self.machine.ten_ge_interfaces
            elif choice == '2':
                self._lacp_guess = True
                self._interfaces_to_configure = self.machine.one_ge_interfaces
            elif choice == '3':
                self._lacp_guess = True
                if self.machine.mlx_interfaces:
                    self._interfaces_to_configure = self.machine.mlx_interfaces
                else:
                    self._interfaces_to_configure = self.machine.ten_ge_interfaces
            elif choice == '4':
                self._lacp_guess = False
                self._interfaces_to_configure = self.machine.forty_ge_interfaces
            else:
                logging.error('_PromptUserForNicConfiguration: Unexpected return value from utils.PromptUserForChoice: %s', choice)
            return

    def _PromptUserForLacp(self):
        """Query user for LACP configuration."""
        if not self.config.prompt:
            return self._lacp_guess
        if not self.machine.ten_ge_interfaces and not self.machine.forty_ge_interfaces:
            return self._lacp_guess
        return utils.PromptUserForBool(prompt='Configure LACP bundle of interfaces in this machine?', default=self._lacp_guess, quiet=self._quiet, debug_mode=self._debug_mode)

    def ValidateLinkLocation(self):
        """Checks NIC link state for validity.
        
        Validation conditions:
        - no link detected: no checks performed
        - if there is a 40Ge interfacce, only one must be present
        - link MUST be on the interface type that is configured (1Ge/10Ge/40Ge)
        - link SHOULD be on the first port of configured 10Ge NIC
        - link MUST NOT be on both onboard and addon 10Ge NICs
        - if addon/mlx NIC is present, link MUST be on that NIC
        
        Raises:
          LinkMismatchError: Raised when link is not detected on first
            port of configured NIC.
          LinkLocationError: Raised when link is detected on different NIC
            that is configured.
        """
        if not self._interfaces_to_configure:
            message = 'No interfaces selected for configuration.'
            if self.machine.forty_ge_interfaces:
                message += '\nPlease select 40Ge interface to configure.'
            elif self.machine.ten_ge_interfaces:
                message += '\nPlease select 10Ge interface(s) to configure.'
            elif self.machine.one_ge_interfaces:
                message += '\nPlease select 1Ge interface(s) to configure.'
            raise LinkMismatchError(message)
        if not self.machine.interfaces_with_link:
            return
        if len(self.machine.forty_ge_interfaces) > 1:
            raise LinkMismatchError('Please connect only the second port on the 40Ge network card.\nPlease reboot the machine after moving the link.')
        is_forty_ge_configured = any((iface for iface in self.machine.forty_ge_interfaces if iface in self._interfaces_to_configure))
        is_forty_ge_up = any((iface for iface in self.machine.forty_ge_interfaces if iface in self.machine.interfaces_with_link))
        if is_forty_ge_configured and not is_forty_ge_up:
            raise LinkMismatchError('No link detected on any 40Ge interface.\nPlease connect the second port on the 40Ge network card.')
        is_ten_ge_configured = any((iface for iface in self.machine.ten_ge_interfaces if iface in self._interfaces_to_configure))
        is_ten_ge_up = any((iface for iface in self.machine.ten_ge_interfaces if iface in self.machine.interfaces_with_link))
        if is_ten_ge_configured and not is_ten_ge_up:
            raise LinkMismatchError('No link detected on any 10Ge interface.\nPlease connect the first port on the 10Ge network card.')
        is_mlx_configured = any((iface for iface in self.machine.mlx_interfaces if iface in self._interfaces_to_configure))
        is_non_mlx_configured = any((iface for iface in self.machine.ten_ge_interfaces + self.machine.forty_ge_interfaces if iface in self._interfaces_to_configure and iface not in self.machine.mlx_interfaces))
        if is_mlx_configured:
            if is_non_mlx_configured:
                raise LinkMismatchError('Link detected on both onboard and addon 10Ge network cards.\nPlease connect only the first port on the 10Ge addon network card.')
            if self.machine.mlx_interfaces[0] not in self.machine.interfaces_with_link:
                raise LinkLocationError('No link detected on the first port of the 10Ge addon network card.\nPlease connect the first port on the 10Ge addon network card.')
            return
        if self.machine.mlx_interfaces:
            raise LinkMismatchError('No link detected on the 10Ge addon network card.\nPlease connect the first port on the 10Ge addon network card.')
        non_mlx_interfaces = [ iface for iface in self.machine.ten_ge_interfaces if iface not in self.machine.mlx_interfaces
                             ]
        if is_non_mlx_configured:
            if non_mlx_interfaces[0] not in self.machine.interfaces_with_link:
                raise LinkLocationError('No link detected on the first port of the 10Ge onboard network card.\nPlease connect the first port on the 10Ge onboard network card.')
        is_one_ge_configured = any((iface for iface in self.machine.one_ge_interfaces if iface in self._interfaces_to_configure))
        is_one_ge_up = any((iface for iface in self.machine.one_ge_interfaces if iface in self.machine.interfaces_with_link))
        if is_one_ge_configured:
            if not is_one_ge_up:
                raise LinkMismatchError('No link detected on any 1Ge interface.\nPlease connect 1Ge network interface(s).')
            return

    def _EnslaveSameTypeNICs(self):
        """Adds all interfaces of the same type to bond set."""
        if any((iface in self.machine.one_ge_interfaces for iface in self._interfaces_to_configure)):
            self._interfaces_to_configure = self.machine.one_ge_interfaces
        elif any((iface in self.machine.forty_ge_interfaces for iface in self._interfaces_to_configure)):
            self._interfaces_to_configure = self.machine.forty_ge_interfaces
        elif any((iface in self.machine.mlx_interfaces for iface in self._interfaces_to_configure)):
            self._interfaces_to_configure = self.machine.mlx_interfaces
        else:
            non_mlx_interfaces = [ iface for iface in self.machine.ten_ge_interfaces if iface not in self.machine.mlx_interfaces ]
            if any((iface in non_mlx_interfaces for iface in self._interfaces_to_configure)):
                self._interfaces_to_configure = non_mlx_interfaces

    def _FinalizeNICConfiguration(self, lacp):
        """Configure final LACP setting and log user NIC choice.
        
        Args:
          lacp: bool indicating if LACP should be configured.
        """
        if self.config.prompt or self.config.lacp is None:
            self.config.SetNetworkParameter('lacp', lacp)
        if self.config.lacp:
            self._EnslaveSameTypeNICs()
        logging.info('Interfaces selected for configuration: %s', [ iface.name for iface in self._interfaces_to_configure ])
        logging.info('LACP is %s on selected interfaces.', 'enabled' if self.config.lacp else 'disabled')
        return

    def GetNicConfigFromUser(self):
        """Reads NIC configuration information from stdin.
        
        This function reads NIC configuration information from stdin, validates it,
        and then stores the values in the object.
        
        Returns:
          True if the selected NIC is valid
        """
        valid_config = False
        while not valid_config:
            self.machine.GatherNicLinkStatus()
            if self._ConfirmDetectedNicLink():
                lacp = self._PromptUserForLacp()
            else:
                self._PromptUserForNicConfiguration()
                lacp = self._lacp_guess
            self._FinalizeNICConfiguration(lacp)
            can_continue = False
            try:
                self.ValidateLinkLocation()
                valid_config = True
            except LinkMismatchError as e:
                reason = str(e)
            except LinkLocationError as e:
                reason = str(e)
                can_continue = self.config.lacp

            if not valid_config:
                if not self._quiet:
                    print
                    print 'Incorrect network interface connected:'
                    print
                    print reason
                    print
                    if self.config.prompt:
                        if can_continue:
                            valid_config = utils.PromptUserForBool(prompt='Are you sure you want to continue?', default=False, quiet=False, debug_mode=self._debug_mode)
                        else:
                            utils.PromptUserForContinuation('Please check network interface connections and try again.', debug_mode=self._debug_mode)
                if not self.config.prompt:
                    return can_continue

        return True

    def PrintNetworkConfiguration(self):
        """Prints the currently configured network configuration."""
        print '\nNetwork configuration:'
        print ' LACP is', 'enabled' if self.config.lacp else 'disabled'
        print ' Node IP subnet: %s' % self.config.subnet
        print ' Machine number in the node: %d' % self.config.machine_number
        print ' Machine IP address: %s' % self.config.ipaddress
        print ' Default gateway: %s' % (self.config.gateway if self.config.gateway.version == 4 else 'IPv6 Router Advertisements with fallback to %s.' % self.config.gateway)

    def _SetIPConfigurationFromSubnetAndMachine(self):
        """Derive IP addressing settings from subnet and machine number."""
        self.config.SetNetworkParameter('ipaddress', self.config.subnet[self.FIRST_HOST_INDEX + self.config.machine_number - 1])
        if self.config.ipaddress.version == 6:
            self.config.SetNetworkParameter('netmask', self.IPV6_PREFIX_LEN)
            self.config.SetNetworkParameter('gateway', self.config.subnet[65536 + self.GATEWAY_INDEX & 65535])
        else:
            self.config.SetNetworkParameter('netmask', self.config.subnet.netmask)
            self.config.SetNetworkParameter('gateway', self.config.subnet[self.GATEWAY_INDEX])

    def _SetMachineNumberFromSubnetAndIPAddress(self):
        """Derive machine number from subnet and IP address."""
        if not self.config.ipaddress or not self.config.subnet:
            return
        ip_index = int(self.config.ipaddress) - int(self.config.subnet.network)
        machine_number = ip_index - self.FIRST_HOST_INDEX + 1
        if machine_number < 1 or machine_number > self.LAST_HOST_INDEX - self.FIRST_HOST_INDEX + 1:
            return
        self.config.SetNetworkParameter('machine', machine_number)

    def _PromptUserForNetworkConfiguration(self):
        """Query user for network configuration parameters."""
        self.config.SetNetworkParameter('subnet', utils.PromptUserForIPNetwork(prompt='Node IP subnet (x.x.x.x/nn or x:x:x:x::/64)', default=self.config.subnet, quiet=self._quiet, debug_mode=self._debug_mode))
        machine_number = self.config.machine_number
        if self.config.machine_number < 1 or self.config.machine_number > self.LAST_HOST_INDEX - self.FIRST_HOST_INDEX + 1:
            machine_number = 1
        self.config.SetNetworkParameter('machine', utils.PromptUserForInt(prompt='Machine number in this node', min_value=1, max_value=self.LAST_HOST_INDEX - self.FIRST_HOST_INDEX + 1, default=machine_number, quiet=self._quiet, debug_mode=self._debug_mode))

    def GetNetworkConfigFromUser(self):
        """Reads configuration information from stdin.
        
        This function reads configuration information from stdin, validates it, and
        then stores the values in the object.
        
        Returns:
          True if the network config is valid
        """
        if not self.config.prompt:
            if not self.config.machine_number:
                self._SetMachineNumberFromSubnetAndIPAddress()
            if not self.config.subnet or self.config.machine_number < 1 or self.config.machine_number > self.LAST_HOST_INDEX - self.FIRST_HOST_INDEX + 1:
                print
                print 'Missing or incorrect network configuration.'
                print
                return False
        valid_config = False
        while not valid_config:
            if self.config.prompt:
                print
                self._PromptUserForNetworkConfiguration()
            self._SetIPConfigurationFromSubnetAndMachine()
            rejection_reasons = self.ValidateIPConfig(network=self.config.subnet, address=self.config.ipaddress, allow_special_ip=self._allow_special_ip, allow_any_ipv6=self._allow_any_ipv6)
            if not rejection_reasons:
                self.PrintNetworkConfiguration()
                if not self.config.prompt:
                    valid_config = True
                else:
                    valid_config = utils.PromptUserForBool(prompt='Is this correct?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
            else:
                if not self._quiet:
                    print
                    print 'Invalid network configuration:'
                    print
                    for reason in rejection_reasons:
                        print '-', reason

                    print
                    print 'Please try again.'
                    print
                if not self.config.prompt:
                    return False

        if not self._dry_run:
            self.config.Write()
        else:
            logging.info('Dry run, not writing network.cfg.')
        return True

    def StopNetworking(self):
        """Stop the automatic network interfaces (if any).
        
        Returns:
          True if successful
        """
        unused_stdout, unused_err, ret_code = utils.RunCommand('%s -a' % self._ifdown_path)
        return ret_code == 0

    def StartNetworking(self):
        """Start the automatic network interfaces (if any).
        
        Returns:
          True if successful
        """
        unused_stdout, unused_err, ret_code = utils.RunCommand('%s -a' % self._ifup_path)
        return ret_code == 0

    def UpdateGatewayARPCache(self, local_address, gateway_address, interface):
        """Update gateway's ARP cache sending unsolicit ARP packets.
        
        Update gateway's ARP cache sending unsolicit ARP packets.
        It won't hurt, but it can be necessary when re-IPing or if the bonded
        interface implies a different MAC address.
        
        Args:
          local_address: local IP address.
          gateway_address: gateway's IP address.
          interface: network interface to send ARP request from
                     (machine.NetworkInterface instance)
        
        Returns:
          True if successful
        """
        unused_stdout, unused_err, ret_code = utils.RunCommand('%s -s %s -U %s -I %s -c 5 -w0.2' % (
         self._arping_path, local_address, gateway_address, interface.name))
        return ret_code == 0

    def ReconfigureNetwork(self):
        """Starts the network interface.
        
        This function gets the network configuration from
        the object and activates the interface
        
        Returns:
          True if the network is started
        """
        if self._dry_run:
            logging.info('Dry run, not touching network configuration.')
            return True
        self.StopNetworking()
        self.WriteEtcNetworkInterfaces()
        self.WriteResolvConf(root=self._ggc_boot_root)
        self.WriteHosts(root=self._ggc_boot_root)
        if not self.StartNetworking():
            return False
        if ipaddr.IPAddress(self.config.ipaddress).version == 4 and self._interfaces_to_configure:
            self.UpdateGatewayARPCache(self.config.ipaddress, self.config.gateway, self._interfaces_to_configure[0])
        return True

    def CheckNetworkConnectivity(self):
        """Performs some ping tests.
        
        Returns:
          True if the ping tests succeed
        """

        def PingTest(dest, quiet):
            """Ping an host."""
            success = False
            if not quiet:
                sys.stdout.write('Pinging %s' % dest)
            for unused_n in range(self._ping_retries):
                if not quiet:
                    sys.stdout.write('.')
                if ipaddr.IPAddress(self.config.ipaddress).version == 6:
                    unused_stdout, unused_stderr, ret_code = utils.RunCommand(' '.join(['ping6', self._ping_options, dest]))
                else:
                    unused_stdout, unused_stderr, ret_code = utils.RunCommand(' '.join(['ping', self._ping_options, dest]))
                if ret_code != 0:
                    logging.error('Ping to %s failed.', dest)
                else:
                    success = True
                    break

            if not quiet:
                print
                if not success:
                    print
                    print 'Unable to reach %s.' % dest
            return success

        def IPv6RATest():
            """Check IPv6 RAs are present."""
            ret_stdout, _, ret_code = utils.RunCommand('ip -6 route show default')
            if ret_stdout:
                logging.info('IPv6 default gateway: %s', ret_stdout)
                return ret_code == 0
            else:
                logging.info('IPv6 default gateway not found.')
                return False

        if not self._quiet:
            print 'Testing network connectivity...'
        if ipaddr.IPAddress(self.config.ipaddress).version == 6:
            self._network_connectivity = PingTest('2001:4860:4860::8888', self._quiet) and PingTest('ipv6.google.com', self._quiet) and IPv6RATest()
        else:
            self._network_connectivity = PingTest(str(self.config.gateway), self._quiet) and PingTest('8.8.8.8', self._quiet) and PingTest('www.google.com', self._quiet)
        if not self._quiet:
            print
            print 'Network test:',
            print 'successful' if self._network_connectivity else 'failed'
            print
        return self._network_connectivity

    def ReadStartCheckNetwork(self):
        """Macro step to run ReadConfiguration, ReconfigureNetwork and CheckNetwork.
        
        Although the individual steps are valid steps, they should be invoked
        individually only for debugging purposes.
        This macro step will take care of invoking them and repeating the steps if
        something goes wrong.
        
        Returns:
           True if it succeeds.
        """
        if not self.GetNicConfigFromUser():
            return False
        connectivity = False
        while not connectivity:
            if not self.GetNetworkConfigFromUser():
                return False
            print
            print 'Setting network configuration...'
            if not self.ReconfigureNetwork():
                if not self._quiet:
                    print
                    print 'Error loading this network configuration.'
                    print 'Please re-enter your data.'
                if not self.config.prompt:
                    return False
            elif not self.CheckNetworkConnectivity():
                if not self._quiet:
                    print
                    print 'The network configuration is valid, but there is no connectivity.'
                if not self.config.prompt:
                    return True
                connectivity = utils.PromptUserForBool(prompt='Are you sure you want to continue?', default=True, quiet=self._quiet, debug_mode=self._debug_mode)
            else:
                connectivity = True

        return True

    def RemoteURL(self):
        """Builds the remote URL.
        
        Returns:
          The URL, properly encoded, used for machine registration
          and log file upload.
        """
        url = self._remote_logging_url
        query = {}
        if self.machine.svctag:
            query['svctag'] = self.machine.svctag
        if self.machine.sysid:
            query['sysid'] = self.machine.sysid
        if query:
            url += '?' + urllib.urlencode(query)
        return url

    def PostData(self, operation, data=None):
        """Builds the data to be posted to the portal.
        
        Args:
          operation: see class Operation
          data: extra data (eg logs)
        
        Returns:
          The postdata, properly encoded.
        """
        postdata = {}
        postdata['operation_type'] = operation
        if data:
            postdata['data'] = base64.b64encode(zlib.compress(data))
        return urllib.urlencode(postdata)

    def RegisterMachine(self):
        """Registers the machine in the ISP Portal.
        
        Returns:
          Always True: the installer should continue even if the registration fails
        """
        if not self._network_connectivity:
            logging.info('Registration skipped, configured network is not working')
            if not self._quiet:
                print 'Skipping machine registration...'
            return True
        if not self._quiet:
            print 'Registering machine...'
        if self._dry_run:
            logging.info('Dry run, registration skipped.')
            return True
        logging.info('Registration URL: %s', self._remote_logging_url)
        registered = callhome.CheckIn(self._remote_logging_url, self.Operation.REGISTER, self._timeout)
        if registered:
            logging.info('Registration successful.')
            if not self._quiet:
                print 'Registration successful.'
        else:
            logging.error('Registration failed.')
            if not self._quiet:
                print
                print 'Unable to register. Please notify <ggc@google.com>.'
                print
        return True

    def UploadLog(self, success):
        """Uploads the installation log to the GGC admin panel.
        
        Args:
          success: Indicates whether or not the installation failed.
        
        Returns:
          True if the upload succeeds (or if flag dry_run is set)
        """
        if self._dry_run:
            logging.info('Dry run, log upload skipped.')
            return True
        url = self.RemoteURL()
        logging.info('Log upload URL: %s', url)
        operation = self.Operation.INSTALL_SUCCEEDED if success else self.Operation.INSTALL_FAILED
        postdata = self.PostData(operation, self.logger.ReadLogs())
        try:
            fd = urllib.urlopen(url, postdata)
            code = fd.getcode()
            fd.read()
            fd.close()
            if code == 204:
                logging.info('Log file upload succeeded.')
            else:
                logging.error('Log file upload error (HTTPError: %i)', fd.getcode())
        except IOError:
            logging.error('Log file upload error: connection failed')

        return True

    @staticmethod
    def CheckBlockDevice(name):
        """Check if filename exists and is a block device.
        
        Arguments:
          name: device name.
        
        Returns:
          True if name is a block device, False if it isn't and None if it doesn't
              exist.
        """
        try:
            mode = os.stat(name).st_mode
        except OSError:
            return None

        if not stat.S_ISBLK(mode):
            return False
        else:
            return True

    def PartitionDisks(self):
        """Partitions disks.
        
        This function shells out to GNU parted to write GPT-style partition tables
        to all configured disks.
        
        Returns:
          True if the partitions were created correctly; False if there was an
          error.
        """
        if not self._quiet:
            print 'Partitioning disks...'
        if self._dry_run:
            logging.info('Dry run, disk partitioning skipped.')
            return True
        else:
            root_disk = self.machine.root_disk
            logging.info("Partitioning '%s'...", root_disk)
            is_block = Installer.CheckBlockDevice(root_disk)
            if is_block is None:
                logging.error("Root disk '%s' is missing!", root_disk)
                return False
            if not is_block:
                logging.error("Root disk '%s' is not a block device!", root_disk)
                return False
            success = 0
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -s %s -- mklabel gpt' % (self._parted_path, root_disk))
            success += ret_code
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -s %s -- mkpart Install 6144s 7818580s' % (
             self._parted_path, root_disk))
            success += ret_code
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -s %s -- mkpart Grub 64s 2147s' % (self._parted_path, root_disk))
            success += ret_code
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('%s -s %s -- set 2 bios_grub on' % (self._parted_path, root_disk))
            success += ret_code
            self._root_partition = root_disk + '1'
            utils.RunCommand('%s settle --exit-if-exists %s' % (
             self._udevadm_path, self._root_partition))
            return success == 0

    def MkFs(self):
        """Create the new install file system.
        
        This function creates the file system.
        
        Returns:
          True if the file system creation succeeds.
          False if there was an error.
        
        """
        if not self._quiet:
            print 'Creating file system...'
        if self._dry_run:
            logging.info('Dry run, filesystem creation skipped.')
            return True
        else:
            is_block = Installer.CheckBlockDevice(self._root_partition)
            if is_block is None:
                logging.error("Root partition '%s' is missing!", self._root_partition)
                return False
            if not is_block:
                logging.error("Root partition '%s' is not a block device!", self._root_partition)
                return False
            logging.info("Creating filesystem '%s' in '%s'...", self._install_fs, self._root_partition)
            unused_stdout, unused_stderr, ret_code = utils.RunCommand('mkfs.%s -L GGCInstall "%s"' % (self._install_fs, self._root_partition))
            return ret_code == 0

    def MountInstallImage(self):
        """Mount the new install file system.
        
        This function mounts the newly created file system.
        
        Returns:
          True if the mount succeeds.
          False if there was an error.
        
        """
        if self._dry_run:
            logging.info('Dry run, nothing to mount.')
            return True
        else:
            is_block = Installer.CheckBlockDevice(self._root_partition)
            if is_block is None:
                logging.error("'%s' is missing!", self._root_partition)
                return False
            if not is_block:
                logging.error("'%s' is not a block device!", self._root_partition)
                return False
            logging.info("Mounting '%s' (%s) in '%s'...", self._root_partition, self._install_fs, self._install_mountpoint)
            unused_stdout, unused_stderr, exitcode = utils.RunCommand('/bin/mount -t %s %s %s' % (
             self._install_fs, self._root_partition,
             self._install_mountpoint))
            if exitcode != 0:
                logging.error('Cannot mount %s.', self._root_partition)
                return False
            return True

    def CopyInstallImage(self):
        """Copies the Install Image to the new file system.
        
        This function takes a directory with a full copy of the Install Image and
        copies it to the new file system's mount point.
        
        Returns:
          True if the system image was successfully copied to the new file system;
          False if there was an error.
        """
        if not self._quiet:
            print 'Installing system...'
        if self._dry_run:
            logging.info('Dry run, installation skipped.')
            return True
        if not os.path.isdir(self._install_srcpath):
            logging.error("Source '%s' is not a directory!", self._install_srcpath)
            return False
        if not os.path.ismount(self._install_mountpoint):
            logging.error("Destination '%s' is not a mountpoint!", self._install_mountpoint)
            return False
        for item in os.listdir(self._install_srcpath):
            item_path = os.path.join(self._install_srcpath, item)
            dst_path = os.path.join(self._install_mountpoint, item)
            unused_stdout, unused_stderr, exitcode = utils.RunCommand('cp -a "%s" "%s"' % (item_path, dst_path))
            if exitcode != 0:
                return False

        return True

    def WriteNetworkConfiguration(self):
        """Writes network configuration to the system image.
        
        This function takes the network configuration specified in the object and
        writes out a basic /etc/network/interfaces file to the system image, as well
        as an /etc/resolv.conf.  It does not configure LACP or tune network
        parameters.
        
        Returns:
          True if the configuration files were successfully written to the system
          image; False if there was an error.
        """
        if self._dry_run:
            logging.info('Dry run, not writing network configuration.')
            return True
        if not os.path.ismount(self._install_mountpoint):
            logging.error("Destination '%s' is not a mountpoint!", self._install_mountpoint)
            return False
        return self.WriteEtcNetworkInterfaces(self._install_mountpoint)

    def WriteResolvConf(self, root=None):
        """Set up /etc/resolv.conf based on configured IP address faimly.
        
        Args:
          root: Path to root filesystem (str)
        
        Returns:
          True if the configuration file was successfully written to the system
          image; False if there was an error.
        """
        resolvers_ipv4 = 'nameserver 8.8.8.8\nnameserver 8.8.4.4\n'
        resolvers_ipv6 = 'nameserver 2001:4860:4860::8888\nnameserver 2001:4860:4860::8844\n'
        if self._dry_run:
            logging.info('Dry run, not writing /etc/resolv.conf.')
            return True
        if not root:
            root = self._install_mountpoint
        if ipaddr.IPAddress(self.config.ipaddress).version == 6:
            resolvers = resolvers_ipv6 + resolvers_ipv4
        else:
            resolvers = resolvers_ipv4 + resolvers_ipv6
        resolv_conf_path = os.path.join(root, 'etc/resolv.conf')
        try:
            logging.info('Writing %s:\n%s', resolv_conf_path, resolvers)
            with open(resolv_conf_path, 'w') as f:
                f.write(resolvers)
        except IOError:
            logging.error('Cannot write %s', resolv_conf_path)
            return False

        return True

    def WriteHosts(self, root=None):
        """Add configured IP address to /etc/hosts for second stage hostname.
        
        Args:
          root: Path to root filesystem (str)
        
        Returns:
          True if the configuration file was successfully written to the system
          image; False if there was an error.
        """
        if self._dry_run:
            logging.info('Dry run, not writing /etc/hosts.')
            return True
        if not root:
            root = self._install_mountpoint
        hostname = 'ggc-install'
        hostname_path = os.path.join(root, 'etc/hostname')
        try:
            with open(hostname_path, 'r') as f:
                hostname = f.readline().rstrip()
        except IOError:
            logging.error('Cannot read %s, using default ggc-install hostname', hostname_path)

        hosts = '127.0.0.1 localhost debian\n::1 ip6-localhost ip6-loopback\nfe00::0 ip6-localnet\nff00::0 ip6-mcastprefix\nff02::1 ip6-allnodes\nff02::2 ip6-allrouters\nff02::3 ip6-allhosts\n%s %s\n' % (
         self.config.ipaddress, hostname)
        hosts_path = os.path.join(root, 'etc/hosts')
        try:
            logging.info('Writing %s:\n%s', hosts_path, hosts)
            with open(hosts_path, 'w') as f:
                f.write(hosts)
        except IOError:
            logging.error('Cannot write %s', hosts_path)
            return False

        return True

    def WriteFstab(self):
        """Writes /etc/fstab to the system image.
        
        This function takes the partition configuration specified by the object
        object and writes out a simple /etc/fstab entry using partition GUIDs.
        
        Returns:
          True if /etc/fstab was written successfully; False if there was an error.
        """
        if self._dry_run:
            logging.info('Dry run, not writing fstab.')
            return True
        fstab = '# fstab\n%s / ext2 errors=remount-ro,relatime 0 1\n' % self._root_partition
        fstab_path = os.path.join(self._install_mountpoint, 'etc/fstab')
        try:
            logging.info('Writing %s:\n%s', fstab_path, fstab)
            with open(fstab_path, 'w') as f:
                f.write(fstab)
        except IOError:
            logging.error('Cannot write %s', fstab_path)
            return False

        return True

    def ConfigureBootloader(self):
        """Configures the bootloader on the system image.
        
        This function takes the partition configuration specified by the object and
        runs the configuration program for the bootloader to install it to the
        appropriate partition.  Then it writes the configuration file for the
        bootloader to the appropriate path.
        
        Returns:
          True if the bootloader was installed and configured successfully; False if
          there was an error.
        """
        if not self._quiet:
            print 'Configuring boot loader...'
        if self._dry_run:
            logging.info('Dry run, skipping bootloader configuration.')
            return True
        bootpath = os.path.join(self._install_mountpoint, 'boot')
        bootlistdir = os.listdir(bootpath)
        vmlinuzlist = [ f for f in bootlistdir if f.startswith('vmlinuz-') ]
        if not vmlinuzlist:
            logging.error('No kernel image!')
            return False
        vmlinuzlist.sort()
        vmlinuz = vmlinuzlist[-1]
        initrdlist = [ f for f in bootlistdir if f.startswith('initrd.img-') ]
        if not initrdlist:
            logging.error('No initrd!')
            return False
        initrdlist.sort()
        initrd = initrdlist[-1]
        kernel_cmdline = utils.ParseProcCmdline(self._proc_cmdline)
        try:
            self._kmod_blacklist = kernel_cmdline['modprobe.blacklist']
        except KeyError:
            pass

        return self._WriteLiloConfig(vmlinuz, initrd, root=self._ggc_boot_root) and self._WriteLiloConfig(vmlinuz, initrd, root=self._install_mountpoint) and self._InstallGrub(vmlinuz, initrd)

    def _WriteLiloConfig(self, vmlinuz, initrd, root):
        """Write Lilo configuration.
        
        Write a templated Lilo config with vmlinuz and initrd to etc/lilo.conf on
        root.
        
        Args:
          vmlinuz: Path to kernel image (str).
          initrd: Path to init ramdisk (str).
          root: Path to root file system mount point (str).
        
        Returns:
          True if the lilo config was written successfully; False if there was an
          error.
        """
        kernel_cmdline = 'console=tty0 console=ttyS%d,115200n8 nomodeset net.ifnames=0' % self.machine.serial_unit
        if self._kmod_blacklist:
            kernel_cmdline += ' modprobe.blacklist=%s' % self._kmod_blacklist
        lilocfg = '# GGC lilo configuration\nboot=/dev/sda\ndelay=10\nmap=/boot/map\nlba32\ninstall=text\nroot=/dev/sda1\nread-only\ndefault=GGCInstall\n\nimage=/boot/%s\n\tlabel=GGCInstall\n\tinitrd=/boot/%s\n\troot=/dev/sda1\n\tappend="%s"\n\toptional\n' % (
         vmlinuz, initrd, kernel_cmdline)
        fname = os.path.join(root, 'etc/lilo.conf')
        try:
            logging.info('Writing %s:\n%s', fname, lilocfg)
            with open(fname, 'w') as f:
                f.write(lilocfg)
        except IOError:
            logging.error('Cannot write %s', fname)
            return False

        return True

    def _InstallGrub(self, vmlinuz, initrd):
        """Write Grub configuration and install Grub.
        
        Write a templated Grub config with vmlinuz and initrd to the install mount
        point and install grub to the root disk.
        
        Args:
          vmlinuz: Path to kernel image (str).
          initrd: Path to init ramdisk (str).
        
        Returns:
          True if the grub was installed successfully; False if there was an error.
        """
        kernel_cmdline = 'root=/dev/sda1 ro console=tty0 console=ttyS%d,115200n8 nomodeset net.ifnames=0' % self.machine.serial_unit
        if self._kmod_blacklist:
            kernel_cmdline += ' modprobe.blacklist=%s' % self._kmod_blacklist
        grubcfg = '# GGC grub2 configuration\nset default=0\nset timeout=5\n\nserial --unit=%d --speed=115200\nterminal_input --append serial\nterminal_output --append serial\n\ninsmod ext2\nset root=(hd0,1)\n\nmenuentry "GGC Installer 2nd stage" {\n\tlinux /boot/%s %s\n\tinitrd /boot/%s\n}\n' % (
         self.machine.serial_unit,
         vmlinuz, kernel_cmdline, initrd)
        bootpath = os.path.join(self._install_mountpoint, 'boot')
        grub_path = os.path.join(bootpath, 'grub')
        try:
            os.makedirs(grub_path)
        except OSError as e:
            if e.errno != errno.EEXIST:
                logging.error('Cannot create dir %s: %s', grub_path, e.strerror)
                return False

        fname = os.path.join(grub_path, 'grub.cfg')
        try:
            logging.info('Writing %s:\n%s', fname, grubcfg)
            with open(fname, 'w') as f:
                f.write(grubcfg)
        except IOError:
            logging.error('Cannot write %s', fname)
            return False

        logging.info('Installing bootloader.')
        unused_std_out, std_err, ret_code = utils.RunCommand('%s --boot-directory=%s %s' % (self._grub_install_path,
         bootpath, self.machine.root_disk))
        if ret_code != 0:
            logging.error('%s failed: %s', self._grub_install_path, std_err)
            return False
        return True

    def UMountInstallImage(self):
        """Unmount the new install file system.
        
        This function unmounts the newly created file system.
        
        Returns:
          True if the umount succeeds.
          False if there was an error.
        
        """
        if self._dry_run:
            logging.info('Dry run, nothing to umount.')
            return True
        logging.info("Unmounting '%s'...", self._install_mountpoint)
        unused_stdout, unused_stderr, exitcode = utils.RunCommand('/bin/umount %s' % self._install_mountpoint)
        if exitcode != 0:
            logging.error('Cannot umount %s.', self._install_mountpoint)
            return False
        return True

    def WriteLogsToImage(self):
        """Writes logs.
        
        This function writes logs.
        
        Returns:
          True. If something fails, we try to log it, but we treat it as a soft
          failure because if everything else worked, it's better to try and complete
          the installation anyway.
        """
        if self._dry_run:
            logging.info('Dry run, not writing logs to boot medium.')
            return True
        if not os.path.ismount(self._install_mountpoint):
            logging.error("Destination '%s' is not a mountpoint!", self._install_mountpoint)
            return True
        log_path = os.path.join(self._install_mountpoint, self._persistent_log_path)
        if not os.path.isdir(log_path):
            logging.error("Destination '%s' is not a directory!", log_path)
            return True
        self.logger.CopyLogs(log_path)
        return True

    def _UpdateEtcIssue(self, root=None):
        """Write installer version and machine service tag to /etc/issue.
        
        Adds information about running installer and hardware to provide necessary
        data for password derivation.
        
        Args:
          root: Path to root file system mount point (str).
        """
        if not root:
            root = self._install_mountpoint
        issue_path = os.path.join(root, 'etc/issue')
        if self._dry_run:
            logging.info('Dry run, not updating %s', issue_path)
            return
        version_st_data = '%s / %s\n\n' % (self._version_full, self.machine.svctag)
        try:
            with open(issue_path, 'a') as f:
                f.write(version_st_data)
        except IOError:
            logging.error('Cannot access %s to add version and service tag information', issue_path)

    def SetRootPassword(self, root=None):
        """Sets the root password on the system image.
        
        This function writes to the appropriate files to set the root password on
        the system image.
        
        Args:
          root: Path to root filesystem (str)
        
        Returns:
          Always True.
          Root password is only needed for debugging installation problems and
          inability to set it should not break install.
        """
        if not root:
            root = self._install_mountpoint
        if not self._version:
            logging.error('Cannot set password: missing version.')
            return True
        if not self.machine.svctag:
            logging.error('Cannot set password: missing service tag.')
            return True
        if self._version_full and 'Dev' in self._version_full:
            logging.info('Skipping password setup on development image (%s).', self._version_full)
            return True
        salt = '$1$%s$' % self._version
        password = crypt.crypt(self.machine.svctag, salt)
        if not password or len(password) <= len(salt):
            logging.error('Cannot set password: generator failed.')
            return True
        utils.RunCommand('/usr/sbin/chpasswd --root %s --crypt-method SHA512' % root, dry_run=self._dry_run, input_buffer='root:%s' % password[len(salt):])
        self._UpdateEtcIssue(root)
        return True

    def FinalizeInstall(self):
        """Update modification time of ggc_version file on the installed image."""
        if self._dry_run:
            logging.info('Dry run, nothing to finalize.')
            return True
        else:
            ggc_version_path = os.path.join(self._install_mountpoint, 'etc/ggc_version')
            try:
                with open(ggc_version_path, 'a'):
                    os.utime(ggc_version_path, None)
            except IOError:
                logging.exception('Cannot access /etc/ggc_version on the installed image.')

            return True

    def GatherNicInformation(self):
        try:
            return self.machine.GatherNicInformation()
        except platformutils.RebootNeeded:
            self.machine.Reboot()

    def GatherSystemInformation(self):
        try:
            return self.machine.GatherSystemInformation()
        except platformutils.RebootNeeded:
            self.machine.Reboot()

    def ConfigureRaid(self):
        return self.machine.ConfigureRaid()

    def ConfigureBIOS(self):
        return self.machine.ConfigureBIOS()

    def ConfigureBootOrder(self):
        return self.machine.ConfigureBootOrder()

    def CreateBIOSJobQueue(self):
        return self.machine.CreateBIOSJobQueue()
# okay decompiling ./google3/net/bandaid/xt_installer/setup/installer.pyc
