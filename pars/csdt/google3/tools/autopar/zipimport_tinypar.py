# Copyright 2010 Google Inc.
# All Rights Reserved.

"""
 A wrapper around zipimport to deal with google3 eccentricities.

 A pure-Python backport of Python 2.3's "zipimport" feature for
 Python 2.2, with a variety of extra features.

 We use the "knee" module to override the built-in import, but
 replace the crucial "import_module" with our own implementation.

 About 50% of this module is basic functionality, and 50% is dealing
 with our sitecustomize peculiarities.

 NOTE: reload(module_name) is a no-op

 Runfiles: When a ZipImporter starts up, it picks a directory to
 extract shared libraries and other needful files into.  Normally,
 for a file /spam/eggs/bacon.par, it picks the directory
 /spam/eggs/bacon.runfiles.  If that directory can't be created or
 written into, the ZipImporter falls back to a temporary directory.

 Original Code by Doug Greiman (dgreiman@google.com)

"""

__author__ = 'springer@google.com (Matthew Springer)'


import contextlib
import errno
import getpass
import io
import imp
import marshal
import os
import stat
import sys
import tempfile
import threading
import time
import tokenize
import types
import zipfile

##################
# Global variables
##################

# Update if any file in this directory is modified
AUTOPAR_VERSION = 4

# Subdirectory where we extract shared libraries to.
RUNFILES_SUFFIX = '.runfiles'

# We currently hardcode ".so" as the extension for shared libraries.
# TODO(dgreiman): Windows .dlls, etc.
SHLIB_EXT = '.so'

# Assume all zipfile timestamps use this timezone
STANDARD_TIMEZONE = "UTC"

# Places to try to create runfiles directories
TEMP_DIRS = ['/export/hda3/tmp', '/tmp']
if sys.platform == 'win32':
  TEMP_DIRS = [os.environ.get('TEMP')]

# Original value of knee.import_module for Python2.2
_knee_import_module = None

# Import verbosity. Ideally we'd use Python's Py_VerboseFlag but it's
# not accessible to Python code.
_verbosity = os.environ.get('PYTHONVERBOSE', 0)

# Map from filename to archive object
_python_archives = {}

# Zipimporters, at least one per zipfile
_zip_importers = []

####################
# Utility functions
####################

def _Log(msg):
  global _verbosity
  if _verbosity:
    sys.stderr.write(msg)
    sys.stderr.write("\n")
  # endif
# enddef


def _RunInTimeZone(timezone, function, *args):
  """Run a function in a standard timezone

  timezone: A timezone abbreviation, as string
  function: A callable object
  args: A list of arguments to pass to the function

  Returns the result of the function

  TODO(dgreiman): Python2.3 provides more reliable ways to set timezone
  """

  old_tz = os.environ.get('TZ')
  try:
    os.environ['TZ'] = timezone
    result = function(*args)
  finally:
    if old_tz is None:
      del os.environ['TZ']
    else:
      os.environ['TZ'] = old_tz
    # endif
  # endtry

  return result
# enddef


def _ZipDateTimeToUnixTime(date_time):
  """Convert from a ZipInfo.date_time member to an integer timestamp.

  Timestamps in zip files are timezone-less, but timestamps in par files are
  in UTC timezone.
  """

  time_tuple = (date_time[0],
                date_time[1],
                date_time[2],
                date_time[3],
                date_time[4],
                date_time[5],
                0, # day of week
                0, # Julian day
                -1, # daylight savings
                )
  timestamp = _RunInTimeZone(STANDARD_TIMEZONE, time.mktime, time_tuple)
  return int(timestamp)
# enddef

def _UnixTimeToZipDateTime(timestamp):
  """Convert from an integer timestamp to a ZipInfo.date_time member."""

  time_tuple = _RunInTimeZone(STANDARD_TIMEZONE, time.localtime, timestamp)
  return time_tuple[0:6]
# enddef


def _mktemp(suffix, dir):
  """Generate a temporary filename in a specified directory.

  TODO(dgreiman): Backport 2.3's NamedTemporaryFile to 2.2,
  use that instead.
  """

  oldtempdir = tempfile.tempdir
  try:
    tempfile.tempdir = dir
    filename=tempfile.mktemp(suffix + str(os.getpid()))
  finally:
    tempfile.tempdir = oldtempdir
  # endtry

  return filename
# enddef


# prefix match also matches e.g. /auto/buildstaticrw
_HOME_BUILD_DIRS = ['/home/build/', '/auto/build', '/google/']

def _IsInHomeBuild(filename):
  """Guess whether a filename is on a public corp NFS mount.

  TODO(dgreiman): We don't guess true for /home/* in general, because
  I'm not sure that there isn't some production code that depends on
  the exact location of .runfiles, and we don't actually have a good
  corp/prod test.

  Returns true/false.
  """

  for d in _HOME_BUILD_DIRS:
    if filename.startswith(d):
      return 1
  return 0
# enddef

####################
# Zipfile-handling Classes
####################

class ZipModule:
  """One or more files stored in a zipfile that are an importable module."""

  _typemap = {
    ".py": "py_filename",
    ".pyc": "pyc_filename",
    ".pyo": "pyo_filename",
    SHLIB_EXT: "shlib_filename",
    }

  def __init__(self, canonical_name, rootname, is_package):
    self.rootname = rootname # Filename minus ext, e.g. google3/foo/bar

    # canonical_name is rootname with "/" replaced by ".", and
    # /__init__.py omitted, e.g. "google3.foo.bar".
    #
    # The actual __name__ of a module will either be canonical_name
    # or a substring of canonical_name, except for __main__.
    #
    # TODO(dgreiman): Make this less confusing.
    self.canonical_name = canonical_name

    self.is_package = is_package

    self.py_filename = None
    self.pyc_filename = None
    self.pyo_filename = None
    self.shlib_filename = None

    self.module = None # Python module object, once loaded
  # enddef
# endclass


def _FindLoadedArchive(pseudo_filename):
  """Given a pseudo-filename, determine if it matches an already loaded archive.

  pseudo_filename: A zip filename or pseudo-filename.
                   E.g. '/spam/eggs.par' or '/spam/eggs.par/bacon/grease'

  Returns (PythonArchive object, canonical name prefix as string)
  """

  assert os.path.isabs(pseudo_filename)
  global _python_archives

  for archive_filename, python_archive in _python_archives.items():
    # Search for 'spam/eggs.par' or 'spam/eggs.par/.*'
    archive_plus_sep = archive_filename + os.sep
    if ((pseudo_filename == archive_filename) or
        (pseudo_filename.startswith(archive_plus_sep))):
      prefix = pseudo_filename[len(archive_plus_sep):]
      if prefix:
        prefix = prefix.replace(os.sep, '.') + '.'
      # endif
      _Log("# using already loaded zip file %s [%s]" % (archive_filename, prefix))
      return python_archive, prefix
    # endif
  # endfor

  return (None, None)
# enddef


def _SplitPseudoFilename(pseudo_filename):
  """Split a pseudo-filename into actual filename part and 'prefix'.

  pseudo_filename: A zip filename or pseudo-filename.
                   E.g. '/spam/eggs.par' or '/spam/eggs.par/bacon/grease'

  The 'prefix', which is actually a suffix here, is used as a prefix
  to construct canonical_names.

  A pseudo_filename like '/spam/eggs.par' is broken into an
  archive filename '/spam/eggs.par' and a prefix ''

  A pseudo_filename like '/spam/eggs.par/bacon/grease' is broken into
  an archive filename '/spam/eggs.par' and a prefix 'bacon.grease.'
  (note trailing dot).

  Returns (1 if actual filename part was found,
           absolute path to .par file,
           canonical name prefix)
  """

  assert os.path.isabs(pseudo_filename), pseudo_filename

  found = 0
  old_filename = None
  cur_filename = pseudo_filename
  prefix = ''
  while cur_filename and cur_filename != old_filename:
    try:
      # Real file (or symlink to real file)?
      st = os.stat(cur_filename)
      if stat.S_ISREG(st[stat.ST_MODE]):
        found = 1
        break
      else:
        # Otherwise a directory, pipe, etc
        break
      # endif
    except EnvironmentError:
      pass  # File not found, keep slicing off subdirs
    # endtry

    old_filename = cur_filename
    prefix = os.path.basename(cur_filename) + '.' + prefix
    cur_filename = os.path.dirname(cur_filename)
  # endwhile

  if found:
    return found, cur_filename, prefix
  else:
    return found, '', ''
  # endif
# enddef


def GetPythonArchive(pseudo_filename):
  """Factory for PythonArchive objects.

  pseudo_filename: A zip filename or pseudo-filename.
                   E.g. 'spam/eggs.par' or 'spam/eggs.par/bacon/grease'

  Returns (PythonArchive object, canonical name prefix as string)

  May return an existing object.
  """

  abs_pseudo_filename = os.path.abspath(pseudo_filename)

  # Already loaded?
  python_archive, prefix = _FindLoadedArchive(abs_pseudo_filename)
  if python_archive:
    return python_archive, prefix
  # endif

  # Archive hasn't been loaded yet
  found, archive_filename, prefix = _SplitPseudoFilename(abs_pseudo_filename)
  if not found:
    raise ImportError("not a Zip file: %s" % pseudo_filename)
  # endif

  # Load archive
  assert archive_filename not in _python_archives, (
    archive_filename, pseudo_filename, _python_archives)
  python_archive = PythonArchive(archive_filename)
  _python_archives[archive_filename] = python_archive

  return python_archive, prefix
# enddef


class PythonArchive:
  """A class that exclusively manages metadata for a single zip file."""

  def __init__(self, filename):
    """Create object for named zipfile."""

    self._zip_filename = filename
    self._zip_file = None
    self._zip_owner_pid = 0
    self._zip_thread_lock = threading.RLock()
    self._filename_list = []

    self._runfiles_root = None

    # Map of fully qualified module name to ZipModule objects.
    self._zmodules = {}
    self._ReadZipFile()
    self._canonical_main_module_name = None

  def __del__(self):
    if self._zip_file:
      try:
        # Should grab the lock here, but grabbing locks in __del__ is tricky,
        # since it might happen during process destruction. Nobody should
        # be accessing the zipfile if not through us, and file.close() is
        # also protected by its own use-counter, so it should be good enough.
        self._zip_file.fp.close()
      except IOError:
        pass

  def _OpenZipFile(self):
    """Open or re-open the underlying zipfile object."""
    if not self._zip_file:
      self._zip_file = zipfile.ZipFile(open(self._zip_filename, 'rb'))
      self._filename_list = self._zip_file.namelist()
    else:
      self._zip_file.fp = open(self._zip_filename, 'rb')
    self._zip_owner_pid = os.getpid()


  @property
  @contextlib.contextmanager
  def _ZipLock(self):
    """Get a lock appropriate for providing exclusive access to the zipfile.

    Returns a context manager object.
    """

    # Thread lock is only good within a process, unique filehandles handle
    # concurrency between processes.
    with self._zip_thread_lock:
      if self._zip_file and os.getpid() != self._zip_owner_pid:
        # We forked after opening the zipfile. Re-open to avoid sharing file
        # table entries. We must avoid sharing offsets and locks.
        self._OpenZipFile()
      yield

  def _CompileSourceCodeString(self, codestring, filename):
    """Compile the contents of a source file.

    codestring: A string containing an entire file of source code.
    filename:   The purported origin of the source code.

    Returns a code object.

    """

    # As per py_compile.py, we must fixup the source as follows:
    codestring = codestring.replace(b"\r\n", b"\n")
    codestring = codestring.replace(b"\r", b"\n")
    if codestring and codestring[-1] != b'\n':
      codestring = codestring + b'\n'
    # endif
    code = compile(codestring, filename, 'exec')

    return code
  # enddef

  def _MaybeAddModuleFile(self, filename):
    """Determine if a filename corresponds to a module."""

    rootname, ext = os.path.splitext(filename)

    # Ignore non-python files
    filetype = ZipModule._typemap.get(ext, None)
    if not filetype:
      return
    # endif

    # Map filename to module name
    module_name, is_package = self._GetModuleNameForFilename(rootname)
    if not module_name:
      return
    # endif

    # Get existing module object, if any, or create new one
    zmodule = self._zmodules.get(module_name)
    if zmodule:
      if zmodule.rootname != rootname:
        raise ImportError("Ambiguity between files %s.* and %s.* in zipfile %s" % (
          rootname, zmodule.rootname, self._zip_filename))
        # endif
      # endif
    else:
      zmodule = ZipModule(module_name, rootname, is_package)
      self._zmodules[module_name] = zmodule
      _Log("# mapping %s -> (%s, %s)" % (filename, module_name, rootname))
    # endif

    # Record filename
    existing_filename = getattr(zmodule, filetype, None)
    if existing_filename:
      raise ImportError("Internal zipimport error, duplicate filenames %s vs %s",
                        existing_filename, filename)
    # endif
    setattr(zmodule, filetype, filename) # Tricky
  # enddef

  def _GetModuleNameForFilename(self, rootname):
    """Compute the module name corresponding to a particular filename.

    rootname: Relative filename without file extension

    Returns (module_name, is_package), or (None, None) if the file is
    not a module.

    """

    # Assume filenames are relative to GOOGLEBASE
    assert not os.path.isabs(rootname)

    # Filenames with dots aren't valid Python names
    if rootname.find(".") != -1:
      return (None, None)
    # endif

    # Convert filename to module name
    module_name = rootname.replace(os.sep, '.')
    if os.altsep:
      module_name = module_name.replace(os.altsep, '.')


    # Is this a package init file?
    is_package = 0
    if module_name.endswith('.__init__'):
      module_name = module_name[:-len('.__init__')]
      is_package = 1
    # endif

    return (module_name, is_package)
  # enddef

  def _GetZModule(self, canonical_name):
    """Return the ZipModule object for a given canonical name."""
    if canonical_name == '__main__':
      canonical_name = self._canonical_main_module_name
    zmodule = self._zmodules.get(canonical_name, None)
    return zmodule
  # enddef

  def _FixupModule(self, module_name, filename):
    """Record the fact that a certain module has already been loaded.

    module_name: __name__ of already-loaded module
    filename: Filename of module, relative to archive file root.

    Basically a hack to deal with __main__ and zipimport_compat modules.

    The first module loaded by Python is given the name __main__, even
    though it has a real name like google.setup.Lockfile. This function
    reconnects the two names as aliases for each other.

    Likewise, the zipimport_compat module is loaded before ZipImport
    objects are created.
    """
    rootname = os.path.splitext(filename)[0]
    canonical_name = self._GetModuleNameForFilename(rootname)[0]
    zmodule = self._GetZModule(canonical_name)
    if zmodule:
      module = sys.modules.get(module_name)
      zmodule.module = module
    # Fix for b/7901421
    if module_name == '__main__':
      self._canonical_main_module_name = canonical_name


  def _ReadCodeObject(self, fullname, data):
    """Create a code object from the contents of a .pyc or .pyo file.

    You'd think there would already be a library function to do this,
    but I didn't find one.

    If bytecode is wrong Python version, pretend it doesn't exist,
    like Python does.  Otherwise, raise ImportError.

    """

    # First 4 bytes is magic #
    magic = data[0:4]
    if magic != imp.get_magic():
      return None

    # Second 4 bytes is timestamp
    mtime = data[4:8]
    if len(mtime) != 4:
      return None

    # Rest of bytes are bytecode
    bytecode = data[self._GetPycHeaderSize():]
    code = marshal.loads(bytecode)
    if not isinstance(code, types.CodeType):
      raise ImportError('Non-code object in %s' % fullname)

    return code

  def _GetPycHeaderSize(self):
    if sys.version_info.major == 3:
      if sys.version_info.minor < 7:
        pyc_header_size = 12
      else:
        pyc_header_size = 16
    else:
      pyc_header_size = 8
    return pyc_header_size

  def _ReadZipFile(self):
    """Construct module table from zipfile table of contents."""

    if not zipfile.is_zipfile(self._zip_filename):
      raise ImportError("Not a zipfile: %s" % self._zip_filename)

    # Read contents of zipfile. Open the file ourselves, so zipfile
    # keeps it open instead of opening and closing it for each access.
    # It will be closed explicitly by our __del__.
    with self._zip_thread_lock:
      self._OpenZipFile()

    # Construct a map of modules contained in this zipfile
    for filename in self._filename_list:
      self._MaybeAddModuleFile(filename)
    # endfor
  # enddef

  def _GetRunfilesName(self):
    """Return the path-less filename of the runfiles directory.

    E.g. for /spam/eggs/foo.par return foo.runfiles
    """
    dir_name = os.path.basename(self._GetDefaultRunfilesRoot())
    return dir_name
  # enddef

  def _GetDefaultRunfilesRoot(self):
    """Return the full path to the standard runfiles directory.

    E.g. for /spam/eggs/foo.par return /spam/eggs/foo.runfiles
    """
    canonical_filename = os.path.realpath(self._zip_filename)
    dir_path = os.path.splitext(canonical_filename)[0] + RUNFILES_SUFFIX
    return dir_path
  # enddef

  def _SetAndGetRunfilesRoot(self):
    """Return the runfiles directory.  If no runfiles directory has
    been chosen, choose one now."""

    if self._runfiles_root is None:
      # Not set.  Set to default value
      self._runfiles_root = self._GetDefaultRunfilesRoot()
      _Log("# Setting runfiles root to %s" % self._runfiles_root)
    # endif
    return self._runfiles_root
  # enddef

  def _GetExtractedFilename(self, rel_filename, dir_path=None):
    """Return the full path where a file should be extracted to

    rel_filename: A file stored in the zipfile.
    dir_path: If given, use this as the directory root.
              Otherwise, use self._runfiles_root
    """

    if dir_path is None:
      dir_path = self._SetAndGetRunfilesRoot()
    # endif

    return os.path.join(dir_path, rel_filename)
  # enddef

  def _ExtractFiles(self, predicate, description, dir_path):
    """Conditionally extract some files from this archive.

    If the directory doesn't exist, create it.

    predicate: A function called on each filename.  If true, extract the file.
    description: A text description of the predicate for logging
    dir_path: Directory to extract into
    """

    matching_files = [f for f in self._filename_list if predicate(f)]
    if not matching_files:
      return
    # endif

    # As a performance optimization heuristic, we don't try to unpack
    # runfiles into /home/build/ or its aliases /auto/build*/
    if _IsInHomeBuild(dir_path):
      allow_write = 0
      reason = "Cannot extract to /home/build/*, /auto/build* or /google/*"
    else:
      # Presence of a MANIFEST file means that this directory was
      # created by the build system.  We can read from it, but cannot
      # overwrite it.
      manifest_fn = os.path.join(dir_path, "MANIFEST")
      allow_write = (not os.path.exists(manifest_fn))
      reason = "Cannot clobber directory because it contains %s" %  manifest_fn
    # endif

    try:
      try:
        # Modify umask so that all files are user-accessible.  Have to
        # call umask twice, since the only way to read the existing
        # umask is to set another umask(!).
        old_umask = os.umask(0)  # 0 == dummy value
        os.umask(old_umask & 0o077)  # Clear user's rwx bits in umask

        # If directory doesn't exist, create it
        if not os.path.isdir(dir_path):
          if allow_write:
            os.makedirs(dir_path, 0o755)  # -rwxr-xr-x
          else:
            raise IOError(errno.EPERM, reason)
          # endif
        # endif

        # Iterate over all shared libraries
        for filename in matching_files:
          # Where to extract?
          abs_filename = self._GetExtractedFilename(filename, dir_path)

          # Need to extract?
          if not self._IsFileExtracted(filename, abs_filename):
            if allow_write:
              self._ExtractFile(filename, abs_filename)
            else:
              raise IOError(errno.EPERM, reason)
            # endif
          else:
            _Log("# don't need to extract %s %s to %s\n" % (
              description, filename, abs_filename))
          # endif
        # endfor
      finally:
        os.umask(old_umask)
      # endtry
    except EnvironmentError as e:
      _Log("# can't extract to %s: %s" % (dir_path, str(e)))
      raise
    # endtry
  # enddef

  def _SetRunfilesDirAndExtractFiles(self, predicate, description,
                                     extract_dirs=None):
    """Find a writable directory to extract files to, and extract files.

    predicate: A function called on each filename.  If true, extract the file.
    description: A text description of the predicate for logging

    Our approach is pretty brute force: We pick a directory and start
    extracting files into it.  If we encounter any errors, we pick a
    different directory and start over.  If we successfully extract
    all files, we return, otherwise if we run out of directories we
    raise an exception.
    """

    # If a previous call to this function has already set
    # self._runfiles_root, then use that value.
    if self._runfiles_root is not None:
      self._ExtractFiles(predicate, description, self._runfiles_root)
      return
    else:
      # Mangle tempdirs with username, so that each user can get a
      # private writable directory.
      dir_name = "%s-%s" % (self._GetRunfilesName(), getpass.getuser())

      # Try several places to extract to.  First, check if we have
      # an environment variable, then, check if we were provided
      # some paths at compile time. In any other case, use the script
      # directory first.
      if 'AUTOPAR_EXTRACT_DIRS' in os.environ:
        extract_dirs = os.environ.get('AUTOPAR_EXTRACT_DIRS').split(os.pathsep)

      if extract_dirs is None:
        extract_dirs = [self._GetDefaultRunfilesRoot()]
      else:
        extract_dirs = [os.path.join(d, dir_name) for d in extract_dirs if d]

      extract_dirs.extend([os.path.join(d, dir_name) for d in TEMP_DIRS])
      for dir_path in extract_dirs:
        _Log("# Trying tentative runfiles root %s" % dir_path)
        try:
          self._ExtractFiles(predicate, description, dir_path)
          self._runfiles_root = dir_path
          _Log("# Setting runfiles root to %s" % self._runfiles_root)
          return
        except EnvironmentError as e:
          pass
        # endtry
      # endfor

      # Didn't find anything
      raise e
    # endif
  # enddef

  def _ExtractAllFiles(self, extract_dirs=None):
    """Unconditionally extract all files from this archive."""
    self._SetRunfilesDirAndExtractFiles(lambda x: 1, "file",
                                        extract_dirs=extract_dirs)
  # enddef

  def _ExtractSharedLibraries(self, extract_dirs=None):
    """Conditionally extract all shared libraries from this archive."""
    self._SetRunfilesDirAndExtractFiles(self._IsSharedLibrary, "shared library",
                                        extract_dirs=extract_dirs)
  # enddef

  def _IsSharedLibrary(self, filename):
    """Determine if the file is a shared library."""
    # Some libraries (esp third party) don't end with .so, but some
    # version-specific name, like .so.32, .so.5, .so.10.1, etc.
    # We check for ".so." because lots of non-shared libraries contain ".so",
    # e.g, .soy, .source, etc
    return filename.endswith(SHLIB_EXT) or (SHLIB_EXT + ".") in filename

  def _IsFileExtracted(self, filename, abs_filename):
    """Determine whether a file has already been extracted from the archive.

    filename: Relative path to file, as stored in archive.
    abs_filename: Absolute path to where file will be extracted

    """

    assert not os.path.isabs(filename)
    assert os.path.isabs(abs_filename)
    assert abs_filename.endswith(filename)

    # Does file exist in runfiles?
    try:
      stats = os.stat(abs_filename)
    except EnvironmentError:
      _Log("# file not stat'd %s" % abs_filename)
      return 0  # Doesn't exist
    # endtry

    # Get info for this archive member, including timestamp and length
    with self._ZipLock:
      info = self._zip_file.getinfo(filename)

    # Timestamp and length match?
    if info.file_size != stats.st_size:
      _Log("# file length mismatch: %d vs %d" % (
        info.file_size, stats.st_size))
      return 0
    # endif

    # File is readable?
    if not os.access(abs_filename, os.R_OK):
      _Log("# file not readable %s" % abs_filename)
      return 0
    # endif

    # NOTE: zipfiles only store times to the nearest 2 seconds as per
    # MSDOS.  Thus 12:00:01 is stored as 12:00:00.
    rounded_mtime = stats.st_mtime - (stats.st_mtime % 2)
    if _ZipDateTimeToUnixTime(info.date_time) != rounded_mtime:
      _Log("# timestamp mismatch: %d %s vs %d" % (
        _ZipDateTimeToUnixTime(info.date_time), info.date_time,
        stats.st_mtime))
      return 0
    # endif

    return 1
  # enddef

  def _ExtractFile(self, filename, abs_filename):
    """Unconditionally extract a file from this archive.

    Files are extracted to a directory tree rooted in the same
    directory as the archive file.

    filename: Relative path to file, as stored in archive.
    abs_filename: Absolute path to where file will be extracted

    """

    assert not os.path.isabs(filename)
    assert os.path.isabs(abs_filename)
    assert abs_filename.endswith(filename)

    _Log("# extracting %s to %s\n" % (
      filename, abs_filename))

    # What directory do we extract to?
    dirname = os.path.dirname(abs_filename)

    # Create if needed
    if not os.path.isdir(dirname):
      # Need to delete existing?
      if os.path.islink(dirname) or os.path.exists(dirname):
        os.remove(dirname)
      # endif

      os.makedirs(dirname, 0o755)  # -rwxr-xr-x
    # endif

    # Write file contents
    temp_filename = _mktemp('autopar', dirname)
    out_file = open(temp_filename, "wb")
    with self._ZipLock:
      zip_member = self._zip_file.open(filename)
      while True:
        data = zip_member.read(1024 * 1024)
        if not data:
          break
        out_file.write(data)
      zip_member.close()
    out_file.close()

    # Restore timestamp
    with self._ZipLock:
      info = self._zip_file.getinfo(filename)
    timestamp = _ZipDateTimeToUnixTime(info.date_time)
    os.utime(temp_filename, (timestamp, timestamp))

    # Restore UNIX specific permission bits
    mode = info.external_attr >> 16
    if mode:
      os.chmod(temp_filename, mode)
    # endif

    # Atomically update existing file if any
    os.rename(temp_filename, abs_filename)
  # enddef

  def NameList(self):
    with self._ZipLock:
      return self._zip_file.namelist()
# endclass

####################
# Importer class
####################

class ZipImporter:
  """A class that can import modules from a single zip file.

  It follows the Importer interface described in PEP 302:
    http://www.python.org/peps/pep-0302.html

  The following public methods are part of that interface:
    find_module
    load_module
    get_code
    get_data
    get_source
    is_package

  There may be multiple importers created for a single zip file under
  Python 2.3+.  The behavior here matches the builtin zipimport module.
  For example, if sys.path contains
    'someprogram.par', 'someprogram.par/dir1/dir2'
  then two ZipImporters are created.  Both objects share the same
  PythonArchive object, but have different import semantics.

  The second path entry in the example is called a pseudofile because
  it refers not a physical file in the file system, but a logical
  directory inside the zip file.  We call this directory the 'prefix'.
  The various public methods are somewhat inconsistent in their
  handling of prefixes.  I adhere to the empirically determined
  behavior of the zipimport module.

  """

  def __init__(self, filename):
    """Create importer for named zipfile."""

    # Cowardly refuse to handle any zipfiles in sys.prefix, since our
    # zipimport implementation isn't quite compatible with Python's own
    # and that breaks certain modules in a zipped up standard library.
    if filename.startswith(sys.prefix):
      raise ImportError('zipimport_tinypar cannot load the stdlib zipfile')

    self._par, self._prefix = GetPythonArchive(filename)

    # Mapping of fully-qualified module name to boolean
    # If _force_fail[name] is true, then load_module(name) returns None
    self._force_fail = {}

  # enddef

  def find_module(self, fullname, unused=None):
    """Determine whether this object can import the requested module.

    Note that foo.find_module('a.b.c') ignores everything before the
    last dot in 'fullname'.

    Respects _prefix if set.
    """

    # Remapped module?
    _Log("# looking up %s in %s (prefix '%s')" % (
      fullname, self._par._zip_filename, self._prefix))

    # Do we have this module?
    canonical_name = self._GetCanonicalNameFromFullname(fullname)
    zmodule = self._par._GetZModule(canonical_name)
    if not zmodule:
      _Log("# not found")
      return None
    # endif

    # Extension module?
    shlib_filename = zmodule.shlib_filename
    if zmodule.shlib_filename:
      extracted_filename = self._par._GetExtractedFilename(shlib_filename)
      if not self._par._IsFileExtracted(shlib_filename, extracted_filename):
        _Log("# ignoring %s: present in zipfile, but hasn't "
             "been extracted to %s" % (
          shlib_filename, extracted_filename))

        return None
      # endif
    # endif

    return self # As per Importer
  # enddef

  def get_code(self, fullname):
    """Return compiled byte-code for module.

    Ignores _prefix.
    """

    # Do we have this module?
    zmodule = self._par._GetZModule(fullname)
    if not zmodule:
      raise ImportError("No module named %s" % fullname)
    # endif

    # Extension module?
    if zmodule.shlib_filename:
      # Extension modules have no code object
      return None
    # endif

    # Try to find bytecode
    if __debug__:
      bytecode_filenames = [ zmodule.pyc_filename, zmodule.pyo_filename ]
    else:
      bytecode_filenames = [ zmodule.pyo_filename, zmodule.pyc_filename ]
    # endif
    for bytecode_filename in bytecode_filenames:
      if bytecode_filename:
        # Read bytecode
        # IOErrors propagate up
        with self._par._ZipLock:
          data = self._par._zip_file.read(bytecode_filename)

        # Construct code object from bytecode.
        # Possible Marshal exceptions or ImportError propagate up.
        code = self._par._ReadCodeObject(fullname, data)
        if code:
          return code
        # endif
      # endif
    # endfor

    # Try to find source code
    py_filename = zmodule.py_filename
    if py_filename:
      # Read source
      # IOErrors propagate up
      with self._par._ZipLock:
        source = self._par._zip_file.read(py_filename)

      # Compile source.
      # SyntaxErrors etc. propagate up.
      code = self._par._CompileSourceCodeString(source, py_filename)
      assert code
      return code
    # endif

    # We shouldn't get here
    raise ImportError("Internal Error in zipimport: No module named %s" % fullname)
  # enddef

  def get_data(self, filename):
    """Return the contents of a file stored within this archive.

    From PEP 302:
     ---
    To retrieve the data for arbitrary "files" from the underlying
    storage backend, loader objects may supply a method named get_data:

    loader.get_data(path)

    This method returns the data as a string, or raise IOError if the
    "file" wasn't found.  It is meant for importers that have some
    file-system-like properties.  The 'path' argument is a path that can
    be constructed by munging module.__file__ (or pkg.__path__ items)
    with the os.path.* functions, for example:

    d = os.path.dirname(__file__)
    data = __loader__.get_data(os.path.join(d, "mydata.txt"))
    ---

    As per Python2.3, and unlike the PEP, we handle both relative
    paths, and absolute paths starting with the filename of the
    parfile.

    Ignores _prefix.
    """

    filename = self._NormalizeFilename(filename)
    if filename in self._par._filename_list:
      with self._par._ZipLock:
        return self._par._zip_file.read(filename)
    # endif

    raise IOError(errno.ENOENT, "File not found", filename)
  # enddef

  def _NormalizeFilename(self, filename):
    """Fix seperators if needed and strip absolute prefix if needed.

    filename: raw filename to normalize.
    """

    if os.altsep:
      filename = filename.replace(os.altsep, os.sep)

    # Strip prefix if any
    if (filename.startswith(self._par._zip_filename + os.sep) and
        len(filename) > len(self._par._zip_filename) + 1):
      filename = filename[len(self._par._zip_filename) + 1:]
    # endif

    if os.altsep == "/":
      filename = filename.replace(os.sep, os.altsep)
    return filename
  # enddef

  def get_source(self, fullname):
    """Return source code for module.

    From PEP 302:
    ---
    The loader.get_source(fullname) method should return the source
    code for the module as a string (using newline characters for line
    endings) or None if the source is not available (yet it should
    still raise ImportError if the module can't be found by the
    importer at all).
    ---

    Ignores _prefix.
    """

    # Do we have this module?
    canonical_name = fullname
    if fullname != '__main__':
      canonical_name = self._GetCanonicalNameFromFullname(fullname)

    zmodule = self._par._GetZModule(canonical_name)
    if not zmodule:
      raise ImportError("No module named %s" % fullname)
    # endif

    # Try to find source code
    py_filename = zmodule.py_filename
    if py_filename:
      # Read source
      # IOErrors propagate up
      with self._par._ZipLock:
        data = self._par._zip_file.read(py_filename)
        if sys.version_info.major == 3:
          data_io = io.BytesIO(data)
          encoding, _ = tokenize.detect_encoding(data_io.readline)
          data_io.seek(0)
          # newline=None means universal newlines
          source = io.TextIOWrapper(data_io, encoding, newline=None)
          return ''.join(source)
        else:
          return data

    # Nope
    return None
  # enddef

  def is_package(self, fullname):
    """Does this name refer to a package directory?

    Ignores _prefix.
    """

    # Do we have this module?
    zmodule = self._par._GetZModule(fullname)
    if not zmodule:
      raise ImportError("No module named %s" % fullname)
    # endif

    return zmodule.is_package
  # enddef

  def load_module(self, fullname):
    """Load the requested module.

    Respects _prefix if set.
    """

    assert fullname != '__main__'

    # Short-circuit optimization?
    if self._force_fail.get(fullname, 0):
      _Log("# load_module returning None for %s" % fullname)
      sys.modules[fullname] = None
      return None
    # endif

    # Do we have this module?
    canonical_name = self._GetCanonicalNameFromFullname(fullname)
    zmodule = self._par._GetZModule(canonical_name)
    if not zmodule:
      raise ImportError("No module named %s" % fullname)
    # endif

    # Already loaded under a different name?
    if zmodule.module:
      sys.modules[fullname] = zmodule.module
      return zmodule.module
    # endif

    # Extension module?
    shlib_filename = zmodule.shlib_filename
    if shlib_filename:
      return self._LoadExtensionModule(fullname, zmodule)
    else:
      try:
        return self._LoadNormalModule(fullname, zmodule)
      except ImportError:
        zmodule.module = None
        del sys.modules[fullname]
        raise
    # endif
  # endef

  def _GetCanonicalNameFromFullname(self, fullname):
    return self._prefix + fullname.split('.')[-1]

  def _LoadExtensionModule(self, fullname, zmodule):
    """load_module for shared libraries.

    Ignores _prefix (caller should already have mangled fullname).

    fullname: Fully-package-qualified module name.
    zmodule: ZModule object to load.
    """

    shlib_filename = zmodule.shlib_filename

    # Use builtin Python code to create this module (via "imp" module)
    ext = os.path.splitext(shlib_filename)[1]
    extracted_filename = self._par._GetExtractedFilename(shlib_filename)
    extracted_file = open(extracted_filename)

    module = imp.load_module(fullname, extracted_file, extracted_filename,
                             (ext, "rb", imp.C_EXTENSION))
    zmodule.module = module
    return module
  # enddef

  def _LoadNormalModule(self, fullname, zmodule):
    """load_module for normal Python modules.

    Ignores _prefix (caller should already have mangled fullname).

    fullname: Fully-package-qualified module name.
    zmodule: ZModule object to load.
    """

    # Retrieve code object for module
    code = self.get_code(zmodule.canonical_name)
    assert code

    # Create and module object and stuff in sys.modules
    #
    # We set __name__ to fullname instead of canonical_name.  For
    # example, if we have
    #   fullname='MySQLdb'
    #   canonical_name='google3.third_party.py.MySQLdb'
    # then we set
    #   __name__ = "MySQLdb"
    #
    # This maintains the invariant
    #   sys.modules[foo].__name__ == foo
    # which Python requires.
    module = imp.new_module(fullname)
    sys.modules[fullname] = module

    # Initialize module object fields
    rootname = zmodule.rootname
    module.__file__ = "%s%s%s.py" % (
      self._par._zip_filename, os.sep, rootname)
    module.__loader__ = self
    if zmodule.is_package:
      # Set package path to have a phony dirname based on the .par
      # filename.  This is an essential marker for our import hooks,
      # and matches the behavior of Python2.3+ zipimport.
      dirname = os.path.dirname(rootname)
      par_path = "%s%s%s" % (self._par._zip_filename, os.sep, dirname)
      module.__path__ = [par_path]
      _Log("# Setting %s.__path__ to %s" % (module.__name__, module.__path__))
    # endif

    # Record that we've loaded this module. We'll do it again later (in
    # case sys.modules is modified), but this preserves the requirement
    # that modules are only imported once, even with circular imports.
    zmodule.module = module

    exec(code, module.__dict__)
    # This maintains compatability with built-in import which allows
    # modules to modify sys.modules on import, including their own entry.
    # Note that it's not circular-import-safe, but then neither is the
    # builtin version.  It also doesn't maintain __file__, __name__, etc.
    # But neither does the builtin version.
    newmodule = sys.modules[fullname]
    zmodule.module = newmodule
    return newmodule

####################
# Init functions
####################

def _InitializeZipImporters(path_list):
  """Examine path_list for python archives and initialize them."""

  importers = []
  for path in path_list:
    try:
      # Errors while reading file are reported
      importer = ZipImporter(path)
      _Log("# loaded par file: %s" % path)
      importers.append(importer)
    except ImportError as e:
      # Only print errors from actual zipfiles that are not in sys.prefix
      # (see the comment in ZipImporter.__init__ for why.)
      if not path.startswith(sys.prefix) and zipfile.is_zipfile(path):
        sys.stderr.write("ZipImport Error: %s\n" % e)

  return importers

def _InstantiateZipImporters():
  """Create ZipImport objects for each zipfile in the path"""

  # Examine entries on sys.path for zipfiles
  _Log("# sys.path is: %s" % sys.path)
  global _zip_importers
  _zip_importers = _InitializeZipImporters(sys.path)

def _InstallImportHook_23():
  """Start using our own import functionality.  Python2.3+ specific.

    From PEP 302:
    ---
    sys.path_hooks is a list of callables, which will be checked in
    sequence to determine if they can handle a given path item.  The
    callable is called with one argument, the path item.  The callable
    must raise ImportError if it is unable to handle the path item, and
    return an importer object if it can handle the path item.  The
    callable is typically the class of the import hook, and hence the
    class __init__ method is called.
    ---
  """


  # Python 2.2 doesn't have a "zipimport" module.  So we look directly
  # in sys.modules instead of using import, to hide it from autopar.
  zipimport = sys.modules['zipimport']

  # Make sure we insert our zipimport hook before the standard zipimport.
  # We don't want regular zipimport to see this zipfile, but replacing it
  # altogether would break imports from other zipfiles.  (gettattr used to
  # avoid pychecher complaints under Pyton 2.2)
  path_hooks = getattr(sys, 'path_hooks')
  for idx in range(len(path_hooks)):
    if path_hooks[idx] == zipimport.zipimporter:
      path_hooks.insert(idx, ZipImporter)
      break
  else:
    # Conceivably something else already removed the standard hook.
    path_hooks.append(ZipImporter)

  # Clear cache
  path_importer_cache = getattr(sys, 'path_importer_cache')
  path_importer_cache.clear()

def _ExtractFiles(autopar_extract_default, extract_dirs=None):
  """Extract files from zipfiles based on environment var $AUTOPAR_EXTRACT.

  Extraction is as follows:
    ALL: Extract all and quit
    LIBS: Extract libs and quit
    NONE: Extract none, run program
    DEFAULT: Extract libs, run program
  """

  # What to extract?
  global _zip_importers
  extract = os.environ.get("AUTOPAR_EXTRACT", autopar_extract_default)
  if extract != "NONE":
    for z in _zip_importers:
      if extract != "ALL": # LIBS, DEFAULT or SWIGDEPS
        z._par._ExtractSharedLibraries(extract_dirs=extract_dirs)
      else:
        z._par._ExtractAllFiles(extract_dirs=extract_dirs)

    if extract == "ALL":
      print("Successfully extracted all files")
      sys.exit(0)
    elif extract == "LIBS":
      print("Successfully extracted shared libraries")
      sys.exit(0)
    elif extract == "SWIGDEPS":
      print(z._par._runfiles_root)
      sys.exit(0)

def _SetupGooglebase(main_importer):
  """Setup sitecustomize.GOOGLEBASE for this program.

  main_importer: ZipImporter that __main__ was loaded from.

  It is set to the runfiles directory of the par file, i.e. the root
  of the tree where shared libraries are extracted to.

  TODO(dgreiman): The directory sitecustomize.GOOGLEBASE is
  ill-defined, especially in the .par file case, and should be
  globally removed at some point.

  """
  sitecustomize = sys.modules.get('sitecustomize', None)
  if sitecustomize:
    googlebase = main_importer._par._SetAndGetRunfilesRoot()
    assert googlebase
    sitecustomize.GOOGLEBASE = googlebase

def Init(main_par_filename, autopar_extract_default, extract_dirs=None):
  """Initialize the import system.

  main_par_filename: File containing __main__ module
  autopar_extract_default: one of "ALL", "LIBS", "NONE", "DEFAULT",
    indicating exactly what to extract from the par file.
  extract_dirs: list of strings, each string indicating a path
    to try to decompress needed data.

  Returns ZipImporter for main_par_filename
  """
  global _zip_importers

  _InstantiateZipImporters()
  assert len(_zip_importers) > 0, ("Error unzipping par file: %r"
                                   % (_zip_importers,))

  main_importer = None
  for importer in _zip_importers:
    if importer._par._zip_filename == main_par_filename:
      main_importer = importer
      break

  assert main_importer, "Error 2 unzipping par file: %r" % (_zip_importers)

  _InstallImportHook_23()

  _ExtractFiles(autopar_extract_default, extract_dirs=extract_dirs)
  _SetupGooglebase(main_importer)

  return main_importer
