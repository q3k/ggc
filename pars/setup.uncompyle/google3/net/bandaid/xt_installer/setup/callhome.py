# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/callhome.py
# Compiled at: 2019-06-18 16:41:38
"""Callhome binary that calls home to the Google ISP Portal.

The binary checks for the existance of /export/hda3/bandaid/CHECKED_IN
and will do a callhome request to the ISP Portal if the timestamp of the file
is older than the uptime.

Design: http://go/bandaid-carcap
"""
import argparse
import logging
import os
import sys
import time
import urllib
from google3.net.bandaid.xt_installer.setup import capclassgen
from google3.net.bandaid.xt_installer.setup import utils
try:
    import readline
except ImportError:
    pass

_CALL_HOME_URL = 'https://cache-management-prod.google.com/mgmt/machine/checkin/'
_CHECKED_IN_FILE = '/export/hda3/bandaid/CHECKED_IN'
_DONT_INSTALL_FILE = '/export/hda3/bandaid/DO_NOT_INSTALL'
_SVCTAG_FILE = '/sys/class/dmi/id/product_serial'
_SYSID_FILE = '/sys/class/dmi/id/product_name'
_ETH0_ADDRESS = '/sys/class/net/eth0/address'
_SUPPORTED_OPERATIONS = [
 'REGISTER',
 'INSTALL_FAILED',
 'INSTALL_SUCCEEDED',
 'CHECK_INFO',
 'REBOOT_COMPLETE']

def _ReadLineFromFile(filename):
    try:
        with open(filename, 'r') as fd:
            return fd.readline().strip()
    except IOError:
        return ''


def _GetRegistrationsPostData(operation_type):
    """Gets the registration POST data.
    
    Args:
      operation_type: the operation type that should be used, should be one of
        _SUPPORTED_OPERATIONS (str).
    
    Returns:
      The URL encoded POST data for the callhome.
    """
    postdata = {'operation_type': operation_type}
    generated_cap_class = capclassgen.GenerateCapabilityClass()
    if generated_cap_class:
        postdata['capclass'] = generated_cap_class
    svc_tag = _ReadLineFromFile(_SVCTAG_FILE)
    if svc_tag:
        postdata['svctag'] = svc_tag
    sys_id = _ReadLineFromFile(_SYSID_FILE)
    if sys_id:
        postdata['sysid'] = sys_id
    mac_addr = _ReadLineFromFile(_ETH0_ADDRESS)
    if mac_addr:
        postdata['mac_addr'] = mac_addr
    sorted_postdata = sorted(postdata.items())
    return urllib.urlencode(sorted_postdata)


def RunCheckin(callhome_url, postdata, registration_timeout, ip_version=4):
    """Runs the given callhome.
    
    Args:
      callhome_url: callhome url that should be used (str).
      postdata: POST data payload that should be sent (str).
      registration_timeout: Timeout for wget before it gives up (int).
      ip_version: IP Version that should be used (4 or 6, int).
    """
    wget_command = 'wget -{ip_version} -O /dev/null -S --no-check-certificate --post-data="{post_data}" --timeout={registration_timeout} --tries=1 -- {callhome_url}'.format(ip_version=ip_version, post_data=postdata, registration_timeout=registration_timeout, callhome_url=callhome_url)
    _, _, return_code = utils.RunCommand(wget_command)
    if return_code:
        logging.error('IPv%d callhome failed with command: %s', ip_version, wget_command)
    else:
        logging.info('IPv%d callhome successful!', ip_version)
        logging.debug('used wget command: %s', wget_command)
        _TouchOrCreateCheckedInFile()


def CheckIn(callhome_url, operation_type, registration_timeout):
    """Runs both checkins over IPv4 and IPv6.
    
    Args:
      callhome_url: callhome url that should be used (str).
      operation_type: the operation type that should be used, should be one of
        _SUPPORTED_OPERATIONS (str).
      registration_timeout: Timeout for wget before it gives up (int).
    
    Returns:
      True if _CHECKED_IN_FILE exists after callhome, False otherwise.
    """
    encoded_postdata = _GetRegistrationsPostData(operation_type)
    RunCheckin(callhome_url, encoded_postdata, registration_timeout)
    RunCheckin(callhome_url, encoded_postdata, registration_timeout, ip_version=6)
    if os.path.isfile(_CHECKED_IN_FILE):
        return True
    else:
        return False


def _TouchOrCreateCheckedInFile():
    """Touches or creates the _CHECKED_IN_FILE."""
    try:
        if os.path.exists(_CHECKED_IN_FILE):
            os.utime(_CHECKED_IN_FILE, None)
        else:
            open(_CHECKED_IN_FILE, 'a').close()
    except IOError:
        logging.error('Could not open/touch checkin file: %s', _CHECKED_IN_FILE)

    return


def ParseCommandlineArguments(args):
    """Wrapper for argparse command line arguments handling.
    
    Args:
      args: List of command line arguments.
    
    Returns:
      Command line arguments namespace built by argparse.ArgumentParser().
    """
    flag_parser = argparse.ArgumentParser(prog='callhome', formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    flag_parser.add_argument('--callhome_url', '-u', default=_CALL_HOME_URL, help="URL for machine registration. (default: '%(default)s')")
    flag_parser.add_argument('--callhomelog_dir', default='/tmp', help="Path where log files reside. (default: '%(default)s')")
    flag_parser.add_argument('--callhomelog_name', default='callhome', help="Base name of the log file. (default: '%(default)s')")
    flag_parser.add_argument('--operation_type', '-o', default='REBOOT_COMPLETE', help="Operation type. (default: '%(default)s')")
    flag_parser.add_argument('--registration_timeout', '-t', default=60, help='Registration (wget) timeout in second. (default: %(default)s secs)')
    flag_parser.add_argument('--force', '-f', action='store_true', help='Force call home disregarding the CHECKED_IN file.')
    flag_parser.add_argument('--capclassgen_only', '-c', action='store_true', help='Only generate and output the capability_class.')
    return flag_parser.parse_args(args)


def _GetBootTimestamp():
    """Returns the time of the last boot, as seconds since epoch."""
    with open('/proc/uptime', 'r') as f:
        uptime_seconds = float(f.readline().split()[0])
    now = time.time()
    return now - uptime_seconds


def main(args):
    log_level = logging.DEBUG
    unused_logger = utils.Logger(log_dir=args.callhomelog_dir, log_name=args.callhomelog_name, log_level=log_level)
    if args.capclassgen_only:
        print capclassgen.GenerateCapabilityClass()
        return
    if args.operation_type not in _SUPPORTED_OPERATIONS:
        print '%s is not a supported operation type. Use one of: %s' % (
         args.operation_type, ' '.join(_SUPPORTED_OPERATIONS))
        sys.exit(1)
    if not args.force and os.path.isfile(_DONT_INSTALL_FILE):
        logging.info('%s found. Not supposed to callhome.', _DONT_INSTALL_FILE)
        sys.exit(1)
    if os.path.isfile(_CHECKED_IN_FILE):
        if not args.force and _GetBootTimestamp() < os.path.getctime(_CHECKED_IN_FILE):
            logging.info('Callhome already done since last reboot. Exiting...')
            return
        logging.info('Callhome not done since reboot. Removing checkin file.')
        os.remove(_CHECKED_IN_FILE)
    if not CheckIn(args.callhome_url, args.operation_type, args.registration_timeout):
        sys.exit(2)


if __name__ == '__main__':
    main(ParseCommandlineArguments(sys.argv[1:]))
# okay decompiling ./google3/net/bandaid/xt_installer/setup/callhome.pyc
