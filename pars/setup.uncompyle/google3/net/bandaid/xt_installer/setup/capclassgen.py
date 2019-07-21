# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/net/bandaid/xt_installer/setup/capclassgen.py
# Compiled at: 2019-06-18 16:41:38
"""This is the implementation module of http://go/bandaid-cap.

This module collects different sysfs values to compute the capability class of a
machine.

We should end up getting something like this:
{
  DiskCount: 12
  RamKilobytes: 67108864
  IntendedLacpState: {
    lacp_enabled: true
    per_link_mbps: 1000
    total_links: 4
  }
  PerformanceClassTag: "num_cores_min=24"
  PerformanceClassTag: "cpu_uarch=sandybridge"
  PerformanceClassTag: "cpu_mhz=2000"
  PerformanceClassTag: "cpu_physical_cores_per_socket=6"
  PerformanceClassTag: "cpu_threads_per_core=2"
  PerformanceClassTag: "cpu_part=E5-2620-0"
  KernelClassTag: "nic=tg3"
  ChunkDiskKilobytesLong: 2929721344
}

Design: http://go/bandaid-cap (and http://go/bandaid-carcap)
"""
import json
import os
import re
from google3.net.bandaid.xt_installer.setup import utils
_MEGACLI_PATH = '/export/hda3/bandaid/tools/MegaCli64'
_HPSSACLI_PATH = '/export/hda3/bandaid/tools/hpssacli'
_SAS3CLI_PATH = '/export/hda3/bandaid/tools/sas3ircu'
_PERCCLI_PATH = '/export/hda3/bandaid/tools/PercCli64'
_POTENTIAL_BONDING_FILES = [
 'proc/net/bonding/bond0', 'proc/net/bonding/eth0']
_DISK_COUNT_MEGACLI_RE = re.compile('^.*Slot.*$')
_DISK_COUNT_HPSSACLI_RE = re.compile('^.*physicaldrive.*$')
_DISK_COUNT_SAS3CLI_RE = re.compile('^.*Slot #.*$')
_RAM_KILOBYTES_RE = re.compile('^MemTotal:\\s*([0-9]*) .*$')
_PER_LINK_MBPS_RE = re.compile('^Speed: \\s*([0-9]*) Mbps.*$')
_PER_LINK_MBPS_ETHTOOL_RE = re.compile('^.*Speed: \\s*([0-9]*)Mb/s.*$')
_NUM_CORES_RE = re.compile('^processor.*$')
_CPU_MODEL_NAME_RE = re.compile('^model name.*CPU\\s(.*)\\s@.*$')
_CPU_MODEL_NAME_SKYLAKE_RE = re.compile('^model name.*\\s((Silver|Gold).*)\\sCPU\\s@.*$')
_CPU_GHZ_RE = re.compile('^model name.*@\\s(.*)$')
_CPU_CORES_PER_SOCKET_RE = re.compile('^cpu cores.*: (.*)$')
_CPU_THREADS_PER_CORE = re.compile('^flags.*:.* (ht) .*$')
_CHUNK_DISK_KB_HP_RE = re.compile('^.*, ([0-9\\.]*) GB.*$')
_CHUNK_DISK_KB_DELL_RE = re.compile('^Raw Size: ([0-9\\.]*) TB.*$')

def _FindPatternInFile(file_path, regex_object, root='/'):
    """Returns the first match in a file for a given regex object."""
    try:
        with open(os.path.join(root, file_path), 'r') as fd:
            for line in fd:
                entry = regex_object.match(line)
                if entry:
                    return entry.group(1).strip()

    except IOError:
        pass

    return ''


def _FindNumberOfMatchesInFile(file_path, regex_object, root='/'):
    """Returns the number of matches in a file for a given regex object."""
    matches = 0
    try:
        with open(os.path.join(root, file_path), 'r') as fd:
            for line in fd:
                match = regex_object.match(line)
                if match:
                    matches += 1

    except IOError:
        pass

    return matches


def _FindPatternInCommandOutput(command, regex_object):
    """Returns the first match in stdout of a command for a given regex object."""
    output, _, _ = utils.RunCommand(command)
    for line in output.splitlines():
        entry = regex_object.match(line)
        if entry:
            return entry.group(1)

    return ''


def _FindNumberOfMatchesInCommandOutput(command, regex_object):
    """Returns the number of matches in command stdout for the regex object."""
    matches = 0
    output, _, _ = utils.RunCommand(command)
    for line in output.splitlines():
        match = regex_object.match(line)
        if match:
            matches += 1

    return matches


def _GetPercDiskCount():
    """Gets the number of physical disks using the PercCLI.
    
    This version of the PercCLI supports json, but requires linefeeds and carriage
    returns to be removed.
    
    Returns:
      Number of physical disks of all controllers as determined by PercCLI, or 0
      if none found.
    """
    total_disk_count = 0
    cmd_output, _, _ = utils.RunCommand('%s /call show j' % _PERCCLI_PATH)
    cmd_output = re.sub('(\\n|\\r)', '', cmd_output)
    try:
        perc_data = json.loads(cmd_output)
        for controller in perc_data['Controllers']:
            total_disk_count += controller['Response Data']['Physical Drives']

    except (ValueError, TypeError, KeyError):
        pass

    return total_disk_count


def _GetDiskCount():
    """Gets the number of physical disks in the machine.
    
    Tries Dell tools first and falls back to HP if 0 disks found.
    
    Returns:
      Number of physical disks or empty string if none found.
    """
    megacli_disk_count = _FindNumberOfMatchesInCommandOutput('%s PDList -aAll' % _MEGACLI_PATH, _DISK_COUNT_MEGACLI_RE)
    sas3_disk_count = _FindNumberOfMatchesInCommandOutput('%s 0 DISPLAY' % _SAS3CLI_PATH, _DISK_COUNT_SAS3CLI_RE)
    perc_disk_count = _GetPercDiskCount()
    if sas3_disk_count:
        return megacli_disk_count + sas3_disk_count
    if perc_disk_count:
        return perc_disk_count
    if megacli_disk_count:
        return megacli_disk_count
    hp_slot0_disk_count = _FindNumberOfMatchesInCommandOutput('%s controller slot=0 pd all show' % _HPSSACLI_PATH, _DISK_COUNT_HPSSACLI_RE)
    hp_slot1_disk_count = _FindNumberOfMatchesInCommandOutput('%s controller slot=1 pd all show' % _HPSSACLI_PATH, _DISK_COUNT_HPSSACLI_RE)
    hp_disk_count = hp_slot0_disk_count + hp_slot1_disk_count
    return hp_disk_count


def _GetRamKilobytes(root='/'):
    """Gets amount of RAM in kilobytes."""
    return _FindPatternInFile('proc/meminfo', _RAM_KILOBYTES_RE, root)


def _GetLacpEnabled():
    """Gets LACP status. Either true or false."""
    if os.path.isfile('/proc/net/bonding/bond0'):
        return 'true'
    if os.path.isfile('/proc/net/bonding/eth0'):
        return 'true'
    return 'false'


def _GetPerLinkMbps(root='/'):
    """Gets the link speed of each interface in the LACP bundle."""
    for bonding_file in _POTENTIAL_BONDING_FILES:
        bundle_link_speed = _FindPatternInFile(bonding_file, _PER_LINK_MBPS_RE, root)
        if bundle_link_speed:
            return bundle_link_speed

    return _FindPatternInCommandOutput('ethtool eth0', _PER_LINK_MBPS_ETHTOOL_RE)


def _GetTotalLinks(root='/'):
    """Gets the total amount of links in the LACP bundle."""
    for bonding_file in _POTENTIAL_BONDING_FILES:
        slave_links = _FindNumberOfMatchesInFile(bonding_file, _PER_LINK_MBPS_RE, root)
        if slave_links > 0:
            return slave_links

    return '1'


def _GetNumCoresMin(root='/'):
    """Gets the total number of CPU cores."""
    return _FindNumberOfMatchesInFile('proc/cpuinfo', _NUM_CORES_RE, root)


def _GetCpuUarch(root='/'):
    """Enumerates the CPU microarchitecture based on the model name."""
    cpu_model = _FindPatternInFile('proc/cpuinfo', _CPU_MODEL_NAME_RE, root)
    if not cpu_model:
        cpu_model = _FindPatternInFile('proc/cpuinfo', _CPU_MODEL_NAME_SKYLAKE_RE, root)
    if 'v2' in cpu_model:
        return 'ivybridge'
    if 'v3' in cpu_model:
        return 'haswell'
    if 'v4' in cpu_model:
        return 'broadwell'
    if 'v5' in cpu_model:
        return 'skylake'
    if 'E55' in cpu_model:
        return 'nehalem'
    if 'L55' in cpu_model:
        return 'nehalem'
    if 'Silver' in cpu_model:
        return 'skylake'
    if 'Gold' in cpu_model:
        return 'skylake'
    return 'sandybridge'


def _GetCpuMhz(root='/'):
    """Gets the CPU Clock Speed and converts to Mhz.
    
    CapabilityClassInfo message mandates Mhz unit, Intel CPUs only report correct
    speed in model name. Speed value in /proc/cpuinfo varies depending on load.
    
    Args:
      root: path to filesystem root (str).
    
    Returns:
      CPU clock speed in Mhz or empty string.
    """
    cpu_speed = _FindPatternInFile('proc/cpuinfo', _CPU_GHZ_RE, root)
    if 'GHz' in cpu_speed:
        try:
            return int(float(cpu_speed.rstrip('GHz')) * 1000)
        except ValueError:
            return ''

    return ''


def _GetCpuPhysicalCoresPerSocket(root='/'):
    """Gets the amount of CPU cores per socket."""
    return _FindPatternInFile('proc/cpuinfo', _CPU_CORES_PER_SOCKET_RE, root)


def _GetCpuThreadsPerCore(root='/'):
    """Gets the number of CPU threads per core."""
    ht_status = _FindPatternInFile('proc/cpuinfo', _CPU_THREADS_PER_CORE, root)
    if ht_status:
        return 2
    return ''


def _GetCpuPart(root='/'):
    """Gets the CPU model name."""
    cpu_model = _FindPatternInFile('proc/cpuinfo', _CPU_MODEL_NAME_RE, root)
    if not cpu_model:
        cpu_model = _FindPatternInFile('proc/cpuinfo', _CPU_MODEL_NAME_SKYLAKE_RE, root)
    return cpu_model.replace(' ', '-')


def _GetNicDriver():
    """Gets the loaded NIC driver kernel module."""
    kernel_modules, _, _ = utils.RunCommand('lsmod')
    kernel_modules = kernel_modules.strip()
    if 'mlx4_en' in kernel_modules:
        return 'mlx4_en'
    if 'mlx5_core' in kernel_modules:
        return 'mlx5_core'
    if 'bnx2x_dell' in kernel_modules:
        return 'bnx2x_dell'
    if 'bnx2x' in kernel_modules:
        return 'bnx2x'
    if 'bnx2' in kernel_modules:
        return 'bnx2'
    if 'tg3' in kernel_modules:
        return 'tg3'
    return ''


def _GetChunkDiskKilobytesLong():
    """Gets the size of the chunk disks in kilobytes."""
    hp_disk_size = _FindPatternInCommandOutput('%s controller slot=0 pd all show' % _HPSSACLI_PATH, _CHUNK_DISK_KB_HP_RE)
    if len(hp_disk_size) > 1:
        return long(float(hp_disk_size) * 1024 * 1024)
    dell_disk_size = _FindPatternInCommandOutput('%s -PdList -aAll' % _MEGACLI_PATH, _CHUNK_DISK_KB_DELL_RE)
    if len(dell_disk_size) > 1:
        return long(float(dell_disk_size) * 1024 * 1024 * 1024)
    return ''


def GenerateCapabilityClass(root='/'):
    """Generates the textproto representation of a CapabilityClassInfo message."""
    output = []
    disk_count = _GetDiskCount()
    if disk_count:
        output.append('  DiskCount: {}'.format(disk_count))
    ram_kilobytes = _GetRamKilobytes(root)
    if ram_kilobytes:
        output.append('  RamKilobytes: {}'.format(ram_kilobytes))
    output.append('  IntendedLacpState: {')
    lacp_enabled = _GetLacpEnabled()
    if lacp_enabled:
        output.append('    lacp_enabled: {}'.format(lacp_enabled))
    per_link_mbps = _GetPerLinkMbps(root)
    if per_link_mbps:
        output.append('    per_link_mbps: {}'.format(per_link_mbps))
    total_links = _GetTotalLinks(root)
    if total_links:
        output.append('    total_links: {}'.format(total_links))
    output.append('  }')
    num_cores_min = _GetNumCoresMin(root)
    if num_cores_min:
        output.append('  PerformanceClassTag: "num_cores_min={}"'.format(num_cores_min))
    cpu_uarch = _GetCpuUarch(root)
    if cpu_uarch:
        output.append('  PerformanceClassTag: "cpu_uarch={}"'.format(cpu_uarch))
    cpu_mhz = _GetCpuMhz(root)
    if cpu_mhz:
        output.append('  PerformanceClassTag: "cpu_mhz={}"'.format(cpu_mhz))
    cpu_phys_cores = _GetCpuPhysicalCoresPerSocket(root)
    if cpu_phys_cores:
        output.append('  PerformanceClassTag: "cpu_physical_cores_per_socket={}"'.format(cpu_phys_cores))
    cpu_threads_per_core = _GetCpuThreadsPerCore(root)
    if cpu_threads_per_core:
        output.append('  PerformanceClassTag: "cpu_threads_per_core={}"'.format(cpu_threads_per_core))
    cpu_part = _GetCpuPart(root)
    if cpu_part:
        output.append('  PerformanceClassTag: "cpu_part={}"'.format(cpu_part))
    chunk_disk_kb = _GetChunkDiskKilobytesLong()
    if chunk_disk_kb:
        output.append('  ChunkDiskKilobytesLong: {}'.format(chunk_disk_kb))
    nic_driver = _GetNicDriver()
    if nic_driver:
        output.append('  KernelClassTag: "nic={}"'.format(nic_driver))
    return '\n'.join(output)
# okay decompiling ./google3/net/bandaid/xt_installer/setup/capclassgen.pyc
