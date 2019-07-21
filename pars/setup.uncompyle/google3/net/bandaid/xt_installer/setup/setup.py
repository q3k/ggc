# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/setup.py
# Compiled at: 2019-06-18 16:41:38
"""Runs the GGC installer.

This program returns:

  0: on a successfull install.
  1: on a successfull reconfiguration when we need to reboot and rerun.
  2: on failure.
"""
__author__ = 'devink@google.com (Devin Kennedy)'
import argparse
import logging
import signal
import sys
from google3.net.bandaid.xt_installer.setup import configuration
from google3.net.bandaid.xt_installer.setup import installer
from google3.net.bandaid.xt_installer.setup import machine
from google3.net.bandaid.xt_installer.setup import platform_dell
from google3.net.bandaid.xt_installer.setup import platform_generic
from google3.net.bandaid.xt_installer.setup import platform_hp
from google3.net.bandaid.xt_installer.setup import platform_itami
from google3.net.bandaid.xt_installer.setup import platformutils
from google3.net.bandaid.xt_installer.setup import utils
try:
    import readline
    readline.set_completer(lambda : None)
except ImportError:
    pass

def ParseCommandlineArguments(args):
    """Wrapper for argparse command line arguments handling.
    
    Args:
      args: List of command line arguments.
    
    Returns:
      Command line arguments namespace built by argparse.ArgumentParser().
    """

    def list_string(string):
        try:
            return string.split(',')
        except AttributeError:
            msg = 'Incorrect argument: %r' % string
            raise argparse.ArgumentTypeError(msg)

    flag_parser = argparse.ArgumentParser(prog='setup', formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    flag_parser.add_argument('--dry_run', '-n', action='store_true', help='Just pretend.')
    flag_parser.add_argument('--quiet', '-q', action='store_true', help='No unnecessary output.')
    flag_parser.add_argument('--remote_logging_url', default='http://cache-management-prod.google.com/mgmt/machine/checkin/', help="URL for machine registration and installation log upload. (default: '%(default)s')")
    flag_parser.add_argument('--instlog_dir', default='/tmp', help="Path where log files reside. (default: '%(default)s')")
    flag_parser.add_argument('--instlog_name', default='g2c_install', help="Base name of the log file. (default: '%(default)s')")
    flag_parser.add_argument('--persistent_log_path', default='var/log', help="Path relative to the install image where we store logs. (default: '%(default)s')")
    flag_parser.add_argument('--timeout', default=30, help="HTTP Connection timeout. (default: '%(default)s')")
    flag_parser.add_argument('--ping_options', default='-nc 4 -w 4 -i0.3', help="Ping probe options. (default: '%(default)s')")
    flag_parser.add_argument('--ping_retries', default=15, help="Number of pings to try. (default: '%(default)s')")
    flag_parser.add_argument('--debug_mode', action='store_true', help='Run the program in debug mode.')
    flag_parser.add_argument('--allow_special_ip', '--allow_rfc5735', action='store_true', help='Allow installation in private networks.')
    flag_parser.add_argument('--allow_any_ipv6', action='store_true', help='Allow use of any IPv6 address space.')
    flag_parser.add_argument('--skip_reboot', action='store_true', help="Skip rebooting even if it's needed.")
    flag_parser.add_argument('--live_mountpoint', default='/lib/live/mount/medium', help="Mountpoint of the live CD/USB. (default: '%(default)s')")
    flag_parser.add_argument('--installer_config', default='/lib/live/mount/medium/installer.cfg', help="Path to the setup platform configuration file. (default: '%(default)s')")
    flag_parser.add_argument('--network_config', default='/lib/live/mount/medium/network.cfg', help="Path to the network configuration file. (default: '%(default)s')")
    flag_parser.add_argument('--rack_config', default='/lib/live/mount/medium/rack.cfg', help="Path to the multinode rack configuration file. (default: '%(default)s')")
    flag_parser.add_argument('--proc_cmdline', default='/proc/cmdline', help="Path to the file containing kernel parameters. (default: '%(default)s')")
    flag_parser.add_argument('--parted_path', default='/sbin/parted', help="Path to parted. (default: '%(default)s')")
    flag_parser.add_argument('--grub_install_path', default='/usr/sbin/grub-install', help="Path to grub. (default: '%(default)s')")
    flag_parser.add_argument('--ifup_path', default='/sbin/ifup', help="Path to ifup. (default: '%(default)s')")
    flag_parser.add_argument('--ifdown_path', default='/sbin/ifdown', help="Path to ifdown. (default: '%(default)s')")
    flag_parser.add_argument('--arping_path', default='/usr/bin/arping', help="Path to arping. (default: '%(default)s')")
    flag_parser.add_argument('--udevadm_path', default='/sbin/udevadm', help="Path to udevadm. (default: '%(default)s')")
    flag_parser.add_argument('--prospective_root_disk', default='/dev/sda', help="Boot disk as detected during a boot with the final configuration. (default: '%(default)s')")
    flag_parser.add_argument('--prospective_root_partition', default='/dev/sda1', help="Partition to mount while booting the Install Image. (default: '%(default)s')")
    flag_parser.add_argument('--install_fs', default='ext2', help="File system for the Install Image. (default: '%(default)s')")
    flag_parser.add_argument('--install_mountpoint', default='/mnt', help="Mountpoint for the Install Image. (default: '%(default)s')")
    flag_parser.add_argument('--install_srcpath', default='/install', help="Path to the Install Image source. (default: '%(default)s')")
    flag_parser.add_argument('--megacli_path', help="Path to MegaCli tool. (default: '%s')" % platform_dell.PlatformDell.DEFAULT_MEGACLI_PATH)
    flag_parser.add_argument('--syscfg_path', help="Path to syscfg tool. (default: '%s')" % platform_dell.PlatformDell.DEFAULT_SYSCFG_PATH)
    flag_parser.add_argument('--idracadm_path', help="Path to iDRAC administration tool. (default: '%s')" % platform_dell.PlatformDell.DEFAULT_IDRACADM_PATH)
    flag_parser.add_argument('--hpssacli_path', help="Path to hpssacli tool. (default: '%s')" % platform_hp.PlatformHP.DEFAULT_HPSSACLI_PATH)
    flag_parser.add_argument('--conrep_path', help="Path to conrep tool. (default: '%s')" % platform_hp.PlatformHP.DEFAULT_CONREP_PATH)
    flag_parser.add_argument('--setbootorder_path', help="Path to setbootorder tool. (default: '%s')" % platform_hp.PlatformHP.DEFAULT_SETBOOTORDER_PATH)
    flag_parser.add_argument('--mstconfig_path', help="Path to mstconfig tool. (default: '%s')" % platform_hp.PlatformHP.DEFAULT_MSTCONFIG_PATH)
    flag_parser.add_argument('--steps', default=installer.Installer.DEFAULT_STEPS, type=list_string, help="Specify steps to execute. (default: '%s')" % ','.join(installer.Installer.DEFAULT_STEPS))
    flag_parser.add_argument('--force_platform', default=platformutils.AUTODETECT, choices=[
     platformutils.AUTODETECT] + platformutils.GetHardwarePlatformNames(), help="Force a particular platform. (default: '%(default)s')")
    return flag_parser.parse_args(args)


def RunInstaller(args, logger):
    """Run the installation process and catch any errors.
    
    Args:
      args: Command line arguments namespace.
      logger: Instance of utils.Logger class.
    
    Returns:
      True on successful installation, False on errors.
    """
    try:
        detected_machine = machine.Machine.Detect(args.force_platform)
        detected_machine.PassEnv(args)
        install_config = configuration.Configuration(proc_cmdline=args.proc_cmdline, config_file=args.installer_config, network_config_file=args.network_config, rack_config_file=args.rack_config, live_mountpoint=args.live_mountpoint)
        install_platform = install_config.installer
        install_state = install_platform(detected_machine, install_config, logger, quiet=args.quiet, dry_run=args.dry_run, debug_mode=args.debug_mode, allow_any_ipv6=args.allow_any_ipv6, allow_special_ip=args.allow_special_ip, install_fs=args.install_fs, install_mountpoint=args.install_mountpoint, ping_options=args.ping_options, ping_retries=args.ping_retries, prospective_root_partition=args.prospective_root_partition, remote_logging_url=args.remote_logging_url, install_srcpath=args.install_srcpath, persistent_log_path=args.persistent_log_path, grub_install_path=args.grub_install_path, arping_path=args.arping_path, ifdown_path=args.ifdown_path, ifup_path=args.ifup_path, parted_path=args.parted_path, udevadm_path=args.udevadm_path, proc_cmdline=args.proc_cmdline, timeout=args.timeout)
        install_state.SetSteps(args.steps)
        if not install_state.Run():
            return False
    except Exception as e:
        logging.exception('Unexpected error, installation failed')
        if args.debug_mode:
            print 'Unexpected error: %s: %s' % (e.__class__.__name__, e)
        return False

    return True


def main(args):
    log_level = logging.DEBUG
    if not args.debug_mode:
        log_level = logging.INFO
        for s in [signal.SIGINT, signal.SIGQUIT, signal.SIGTSTP]:
            signal.signal(s, signal.SIG_IGN)

    logger = utils.Logger(log_dir=args.instlog_dir, log_name=args.instlog_name, log_level=log_level)
    if not RunInstaller(args, logger):
        sys.exit(2)


if __name__ == '__main__':
    main(ParseCommandlineArguments(sys.argv[1:]))
# okay decompiling ./google3/net/bandaid/xt_installer/setup/setup.pyc
