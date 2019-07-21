# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/tools/autopar/zipimport_tinypar.py
# Compiled at: 2019-06-18 16:41:38
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
AUTOPAR_VERSION = 4
RUNFILES_SUFFIX = '.runfiles'
SHLIB_EXT = '.so'
STANDARD_TIMEZONE = 'UTC'
TEMP_DIRS = [
 '/export/hda3/tmp', '/tmp']
if sys.platform == 'win32':
    TEMP_DIRS = [
     os.environ.get('TEMP')]
_knee_import_module = None
_verbosity = os.environ.get('PYTHONVERBOSE', 0)
_python_archives = {}
_zip_importers = []

def _Log(msg):
    global _verbosity
    if _verbosity:
        sys.stderr.write(msg)
        sys.stderr.write('\n')


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

    return result


def _ZipDateTimeToUnixTime(date_time):
    """Convert from a ZipInfo.date_time member to an integer timestamp.
    
    Timestamps in zip files are timezone-less, but timestamps in par files are
    in UTC timezone.
    """
    time_tuple = (
     date_time[0],
     date_time[1],
     date_time[2],
     date_time[3],
     date_time[4],
     date_time[5],
     0,
     0,
     -1)
    timestamp = _RunInTimeZone(STANDARD_TIMEZONE, time.mktime, time_tuple)
    return int(timestamp)


def _UnixTimeToZipDateTime(timestamp):
    """Convert from an integer timestamp to a ZipInfo.date_time member."""
    time_tuple = _RunInTimeZone(STANDARD_TIMEZONE, time.localtime, timestamp)
    return time_tuple[0:6]


def _mktemp(suffix, dir):
    """Generate a temporary filename in a specified directory.
    
    TODO(dgreiman): Backport 2.3's NamedTemporaryFile to 2.2,
    use that instead.
    """
    oldtempdir = tempfile.tempdir
    try:
        tempfile.tempdir = dir
        filename = tempfile.mktemp(suffix + str(os.getpid()))
    finally:
        tempfile.tempdir = oldtempdir

    return filename


_HOME_BUILD_DIRS = [
 '/home/build/', '/auto/build', '/google/']

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


class ZipModule():
    """One or more files stored in a zipfile that are an importable module."""
    _typemap = {'.py': 'py_filename',
       '.pyc': 'pyc_filename',
       '.pyo': 'pyo_filename',
       SHLIB_EXT: 'shlib_filename'
       }

    def __init__(self, canonical_name, rootname, is_package):
        self.rootname = rootname
        self.canonical_name = canonical_name
        self.is_package = is_package
        self.py_filename = None
        self.pyc_filename = None
        self.pyo_filename = None
        self.shlib_filename = None
        self.module = None
        return


def _FindLoadedArchive(pseudo_filename):
    """Given a pseudo-filename, determine if it matches an already loaded archive.
    
    pseudo_filename: A zip filename or pseudo-filename.
                     E.g. '/spam/eggs.par' or '/spam/eggs.par/bacon/grease'
    
    Returns (PythonArchive object, canonical name prefix as string)
    """
    global _python_archives
    assert os.path.isabs(pseudo_filename)
    for archive_filename, python_archive in _python_archives.items():
        archive_plus_sep = archive_filename + os.sep
        if pseudo_filename == archive_filename or pseudo_filename.startswith(archive_plus_sep):
            prefix = pseudo_filename[len(archive_plus_sep):]
            if prefix:
                prefix = prefix.replace(os.sep, '.') + '.'
            _Log('# using already loaded zip file %s [%s]' % (archive_filename, prefix))
            return (
             python_archive, prefix)

    return (None, None)


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
            st = os.stat(cur_filename)
            if stat.S_ISREG(st[stat.ST_MODE]):
                found = 1
                break
            else:
                break
        except EnvironmentError:
            pass

        old_filename = cur_filename
        prefix = os.path.basename(cur_filename) + '.' + prefix
        cur_filename = os.path.dirname(cur_filename)

    if found:
        return (found, cur_filename, prefix)
    else:
        return (
         found, '', '')
        return


def GetPythonArchive(pseudo_filename):
    """Factory for PythonArchive objects.
    
    pseudo_filename: A zip filename or pseudo-filename.
                     E.g. 'spam/eggs.par' or 'spam/eggs.par/bacon/grease'
    
    Returns (PythonArchive object, canonical name prefix as string)
    
    May return an existing object.
    """
    abs_pseudo_filename = os.path.abspath(pseudo_filename)
    python_archive, prefix = _FindLoadedArchive(abs_pseudo_filename)
    if python_archive:
        return (python_archive, prefix)
    found, archive_filename, prefix = _SplitPseudoFilename(abs_pseudo_filename)
    if not found:
        raise ImportError('not a Zip file: %s' % pseudo_filename)
    assert archive_filename not in _python_archives, (
     archive_filename, pseudo_filename, _python_archives)
    python_archive = PythonArchive(archive_filename)
    _python_archives[archive_filename] = python_archive
    return (
     python_archive, prefix)


class PythonArchive():
    """A class that exclusively manages metadata for a single zip file."""

    def __init__(self, filename):
        """Create object for named zipfile."""
        self._zip_filename = filename
        self._zip_file = None
        self._zip_owner_pid = 0
        self._zip_thread_lock = threading.RLock()
        self._filename_list = []
        self._runfiles_root = None
        self._zmodules = {}
        self._ReadZipFile()
        self._canonical_main_module_name = None
        return

    def __del__(self):
        if self._zip_file:
            try:
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
        with self._zip_thread_lock:
            if self._zip_file and os.getpid() != self._zip_owner_pid:
                self._OpenZipFile()
            yield

    def _CompileSourceCodeString(self, codestring, filename):
        """Compile the contents of a source file.
        
        codestring: A string containing an entire file of source code.
        filename:   The purported origin of the source code.
        
        Returns a code object.
        
        """
        codestring = codestring.replace('\r\n', '\n')
        codestring = codestring.replace('\r', '\n')
        if codestring and codestring[-1] != '\n':
            codestring = codestring + '\n'
        code = compile(codestring, filename, 'exec')
        return code

    def _MaybeAddModuleFile(self, filename):
        """Determine if a filename corresponds to a module."""
        rootname, ext = os.path.splitext(filename)
        filetype = ZipModule._typemap.get(ext, None)
        if not filetype:
            return
        else:
            module_name, is_package = self._GetModuleNameForFilename(rootname)
            if not module_name:
                return
            zmodule = self._zmodules.get(module_name)
            if zmodule:
                if zmodule.rootname != rootname:
                    raise ImportError('Ambiguity between files %s.* and %s.* in zipfile %s' % (
                     rootname, zmodule.rootname, self._zip_filename))
            else:
                zmodule = ZipModule(module_name, rootname, is_package)
                self._zmodules[module_name] = zmodule
                _Log('# mapping %s -> (%s, %s)' % (filename, module_name, rootname))
            existing_filename = getattr(zmodule, filetype, None)
            if existing_filename:
                raise ImportError('Internal zipimport error, duplicate filenames %s vs %s', existing_filename, filename)
            setattr(zmodule, filetype, filename)
            return

    def _GetModuleNameForFilename(self, rootname):
        """Compute the module name corresponding to a particular filename.
        
        rootname: Relative filename without file extension
        
        Returns (module_name, is_package), or (None, None) if the file is
        not a module.
        
        """
        assert not os.path.isabs(rootname)
        if rootname.find('.') != -1:
            return (None, None)
        else:
            module_name = rootname.replace(os.sep, '.')
            if os.altsep:
                module_name = module_name.replace(os.altsep, '.')
            is_package = 0
            if module_name.endswith('.__init__'):
                module_name = module_name[:-len('.__init__')]
                is_package = 1
            return (
             module_name, is_package)

    def _GetZModule(self, canonical_name):
        """Return the ZipModule object for a given canonical name."""
        if canonical_name == '__main__':
            canonical_name = self._canonical_main_module_name
        zmodule = self._zmodules.get(canonical_name, None)
        return zmodule

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
        if module_name == '__main__':
            self._canonical_main_module_name = canonical_name

    def _ReadCodeObject(self, fullname, data):
        """Create a code object from the contents of a .pyc or .pyo file.
        
        You'd think there would already be a library function to do this,
        but I didn't find one.
        
        If bytecode is wrong Python version, pretend it doesn't exist,
        like Python does.  Otherwise, raise ImportError.
        
        """
        magic = data[0:4]
        if magic != imp.get_magic():
            return None
        else:
            mtime = data[4:8]
            if len(mtime) != 4:
                return None
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
            raise ImportError('Not a zipfile: %s' % self._zip_filename)
        with self._zip_thread_lock:
            self._OpenZipFile()
        for filename in self._filename_list:
            self._MaybeAddModuleFile(filename)

    def _GetRunfilesName(self):
        """Return the path-less filename of the runfiles directory.
        
        E.g. for /spam/eggs/foo.par return foo.runfiles
        """
        dir_name = os.path.basename(self._GetDefaultRunfilesRoot())
        return dir_name

    def _GetDefaultRunfilesRoot(self):
        """Return the full path to the standard runfiles directory.
        
        E.g. for /spam/eggs/foo.par return /spam/eggs/foo.runfiles
        """
        canonical_filename = os.path.realpath(self._zip_filename)
        dir_path = os.path.splitext(canonical_filename)[0] + RUNFILES_SUFFIX
        return dir_path

    def _SetAndGetRunfilesRoot(self):
        """Return the runfiles directory.  If no runfiles directory has
        been chosen, choose one now."""
        if self._runfiles_root is None:
            self._runfiles_root = self._GetDefaultRunfilesRoot()
            _Log('# Setting runfiles root to %s' % self._runfiles_root)
        return self._runfiles_root

    def _GetExtractedFilename(self, rel_filename, dir_path=None):
        """Return the full path where a file should be extracted to
        
        rel_filename: A file stored in the zipfile.
        dir_path: If given, use this as the directory root.
                  Otherwise, use self._runfiles_root
        """
        if dir_path is None:
            dir_path = self._SetAndGetRunfilesRoot()
        return os.path.join(dir_path, rel_filename)

    def _ExtractFiles(self, predicate, description, dir_path):
        """Conditionally extract some files from this archive.
        
        If the directory doesn't exist, create it.
        
        predicate: A function called on each filename.  If true, extract the file.
        description: A text description of the predicate for logging
        dir_path: Directory to extract into
        """
        matching_files = [ f for f in self._filename_list if predicate(f) ]
        if not matching_files:
            return
        if _IsInHomeBuild(dir_path):
            allow_write = 0
            reason = 'Cannot extract to /home/build/*, /auto/build* or /google/*'
        else:
            manifest_fn = os.path.join(dir_path, 'MANIFEST')
            allow_write = not os.path.exists(manifest_fn)
            reason = 'Cannot clobber directory because it contains %s' % manifest_fn
        try:
            try:
                old_umask = os.umask(0)
                os.umask(old_umask & 63)
                if not os.path.isdir(dir_path):
                    if allow_write:
                        os.makedirs(dir_path, 493)
                    else:
                        raise IOError(errno.EPERM, reason)
                for filename in matching_files:
                    abs_filename = self._GetExtractedFilename(filename, dir_path)
                    if not self._IsFileExtracted(filename, abs_filename):
                        if allow_write:
                            self._ExtractFile(filename, abs_filename)
                        else:
                            raise IOError(errno.EPERM, reason)
                    else:
                        _Log("# don't need to extract %s %s to %s\n" % (
                         description, filename, abs_filename))

            finally:
                os.umask(old_umask)

        except EnvironmentError as e:
            _Log("# can't extract to %s: %s" % (dir_path, str(e)))
            raise

    def _SetRunfilesDirAndExtractFiles(self, predicate, description, extract_dirs=None):
        """Find a writable directory to extract files to, and extract files.
        
        predicate: A function called on each filename.  If true, extract the file.
        description: A text description of the predicate for logging
        
        Our approach is pretty brute force: We pick a directory and start
        extracting files into it.  If we encounter any errors, we pick a
        different directory and start over.  If we successfully extract
        all files, we return, otherwise if we run out of directories we
        raise an exception.
        """
        if self._runfiles_root is not None:
            self._ExtractFiles(predicate, description, self._runfiles_root)
            return
        else:
            dir_name = '%s-%s' % (self._GetRunfilesName(), getpass.getuser())
            if 'AUTOPAR_EXTRACT_DIRS' in os.environ:
                extract_dirs = os.environ.get('AUTOPAR_EXTRACT_DIRS').split(os.pathsep)
            if extract_dirs is None:
                extract_dirs = [
                 self._GetDefaultRunfilesRoot()]
            else:
                extract_dirs = [ os.path.join(d, dir_name) for d in extract_dirs if d ]
            extract_dirs.extend([ os.path.join(d, dir_name) for d in TEMP_DIRS ])
            for dir_path in extract_dirs:
                _Log('# Trying tentative runfiles root %s' % dir_path)
                try:
                    self._ExtractFiles(predicate, description, dir_path)
                    self._runfiles_root = dir_path
                    _Log('# Setting runfiles root to %s' % self._runfiles_root)
                    return
                except EnvironmentError as e:
                    pass

            raise e
            return

    def _ExtractAllFiles(self, extract_dirs=None):
        """Unconditionally extract all files from this archive."""
        self._SetRunfilesDirAndExtractFiles(lambda x: 1, 'file', extract_dirs=extract_dirs)

    def _ExtractSharedLibraries(self, extract_dirs=None):
        """Conditionally extract all shared libraries from this archive."""
        self._SetRunfilesDirAndExtractFiles(self._IsSharedLibrary, 'shared library', extract_dirs=extract_dirs)

    def _IsSharedLibrary(self, filename):
        """Determine if the file is a shared library."""
        return filename.endswith(SHLIB_EXT) or SHLIB_EXT + '.' in filename

    def _IsFileExtracted(self, filename, abs_filename):
        """Determine whether a file has already been extracted from the archive.
        
        filename: Relative path to file, as stored in archive.
        abs_filename: Absolute path to where file will be extracted
        
        """
        assert not os.path.isabs(filename)
        assert os.path.isabs(abs_filename)
        assert abs_filename.endswith(filename)
        try:
            stats = os.stat(abs_filename)
        except EnvironmentError:
            _Log("# file not stat'd %s" % abs_filename)
            return 0

        with self._ZipLock:
            info = self._zip_file.getinfo(filename)
        if info.file_size != stats.st_size:
            _Log('# file length mismatch: %d vs %d' % (
             info.file_size, stats.st_size))
            return 0
        if not os.access(abs_filename, os.R_OK):
            _Log('# file not readable %s' % abs_filename)
            return 0
        rounded_mtime = stats.st_mtime - stats.st_mtime % 2
        if _ZipDateTimeToUnixTime(info.date_time) != rounded_mtime:
            _Log('# timestamp mismatch: %d %s vs %d' % (
             _ZipDateTimeToUnixTime(info.date_time), info.date_time,
             stats.st_mtime))
            return 0
        return 1

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
        _Log('# extracting %s to %s\n' % (
         filename, abs_filename))
        dirname = os.path.dirname(abs_filename)
        if not os.path.isdir(dirname):
            if os.path.islink(dirname) or os.path.exists(dirname):
                os.remove(dirname)
            os.makedirs(dirname, 493)
        temp_filename = _mktemp('autopar', dirname)
        out_file = open(temp_filename, 'wb')
        with self._ZipLock:
            zip_member = self._zip_file.open(filename)
            while True:
                data = zip_member.read(1048576)
                if not data:
                    break
                out_file.write(data)

            zip_member.close()
        out_file.close()
        with self._ZipLock:
            info = self._zip_file.getinfo(filename)
        timestamp = _ZipDateTimeToUnixTime(info.date_time)
        os.utime(temp_filename, (timestamp, timestamp))
        mode = info.external_attr >> 16
        if mode:
            os.chmod(temp_filename, mode)
        os.rename(temp_filename, abs_filename)

    def NameList(self):
        with self._ZipLock:
            return self._zip_file.namelist()


class ZipImporter():
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
        if filename.startswith(sys.prefix):
            raise ImportError('zipimport_tinypar cannot load the stdlib zipfile')
        self._par, self._prefix = GetPythonArchive(filename)
        self._force_fail = {}

    def find_module(self, fullname, unused=None):
        """Determine whether this object can import the requested module.
        
        Note that foo.find_module('a.b.c') ignores everything before the
        last dot in 'fullname'.
        
        Respects _prefix if set.
        """
        _Log("# looking up %s in %s (prefix '%s')" % (
         fullname, self._par._zip_filename, self._prefix))
        canonical_name = self._GetCanonicalNameFromFullname(fullname)
        zmodule = self._par._GetZModule(canonical_name)
        if not zmodule:
            _Log('# not found')
            return None
        else:
            shlib_filename = zmodule.shlib_filename
            if zmodule.shlib_filename:
                extracted_filename = self._par._GetExtractedFilename(shlib_filename)
                if not self._par._IsFileExtracted(shlib_filename, extracted_filename):
                    _Log("# ignoring %s: present in zipfile, but hasn't been extracted to %s" % (
                     shlib_filename, extracted_filename))
                    return None
            return self

    def get_code(self, fullname):
        """Return compiled byte-code for module.
        
        Ignores _prefix.
        """
        zmodule = self._par._GetZModule(fullname)
        if not zmodule:
            raise ImportError('No module named %s' % fullname)
        if zmodule.shlib_filename:
            return
        else:
            bytecode_filenames = [
             zmodule.pyc_filename, zmodule.pyo_filename]
            for bytecode_filename in bytecode_filenames:
                if bytecode_filename:
                    with self._par._ZipLock:
                        data = self._par._zip_file.read(bytecode_filename)
                    code = self._par._ReadCodeObject(fullname, data)
                    if code:
                        return code

            py_filename = zmodule.py_filename
            if py_filename:
                with self._par._ZipLock:
                    source = self._par._zip_file.read(py_filename)
                code = self._par._CompileSourceCodeString(source, py_filename)
                assert code
                return code
            raise ImportError('Internal Error in zipimport: No module named %s' % fullname)
            return

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
        raise IOError(errno.ENOENT, 'File not found', filename)

    def _NormalizeFilename(self, filename):
        """Fix seperators if needed and strip absolute prefix if needed.
        
        filename: raw filename to normalize.
        """
        if os.altsep:
            filename = filename.replace(os.altsep, os.sep)
        if filename.startswith(self._par._zip_filename + os.sep) and len(filename) > len(self._par._zip_filename) + 1:
            filename = filename[len(self._par._zip_filename) + 1:]
        if os.altsep == '/':
            filename = filename.replace(os.sep, os.altsep)
        return filename

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
        canonical_name = fullname
        if fullname != '__main__':
            canonical_name = self._GetCanonicalNameFromFullname(fullname)
        zmodule = self._par._GetZModule(canonical_name)
        if not zmodule:
            raise ImportError('No module named %s' % fullname)
        py_filename = zmodule.py_filename
        if py_filename:
            with self._par._ZipLock:
                data = self._par._zip_file.read(py_filename)
                if sys.version_info.major == 3:
                    data_io = io.BytesIO(data)
                    encoding, _ = tokenize.detect_encoding(data_io.readline)
                    data_io.seek(0)
                    source = io.TextIOWrapper(data_io, encoding, newline=None)
                    return ''.join(source)
                return data
        return

    def is_package(self, fullname):
        """Does this name refer to a package directory?
        
        Ignores _prefix.
        """
        zmodule = self._par._GetZModule(fullname)
        if not zmodule:
            raise ImportError('No module named %s' % fullname)
        return zmodule.is_package

    def load_module(self, fullname):
        """Load the requested module.
        
        Respects _prefix if set.
        """
        assert fullname != '__main__'
        if self._force_fail.get(fullname, 0):
            _Log('# load_module returning None for %s' % fullname)
            sys.modules[fullname] = None
            return
        else:
            canonical_name = self._GetCanonicalNameFromFullname(fullname)
            zmodule = self._par._GetZModule(canonical_name)
            if not zmodule:
                raise ImportError('No module named %s' % fullname)
            if zmodule.module:
                sys.modules[fullname] = zmodule.module
                return zmodule.module
            shlib_filename = zmodule.shlib_filename
            if shlib_filename:
                return self._LoadExtensionModule(fullname, zmodule)
            try:
                return self._LoadNormalModule(fullname, zmodule)
            except ImportError:
                zmodule.module = None
                del sys.modules[fullname]
                raise

            return

    def _GetCanonicalNameFromFullname(self, fullname):
        return self._prefix + fullname.split('.')[-1]

    def _LoadExtensionModule(self, fullname, zmodule):
        """load_module for shared libraries.
        
        Ignores _prefix (caller should already have mangled fullname).
        
        fullname: Fully-package-qualified module name.
        zmodule: ZModule object to load.
        """
        shlib_filename = zmodule.shlib_filename
        ext = os.path.splitext(shlib_filename)[1]
        extracted_filename = self._par._GetExtractedFilename(shlib_filename)
        extracted_file = open(extracted_filename)
        module = imp.load_module(fullname, extracted_file, extracted_filename, (
         ext, 'rb', imp.C_EXTENSION))
        zmodule.module = module
        return module

    def _LoadNormalModule(self, fullname, zmodule):
        """load_module for normal Python modules.
        
        Ignores _prefix (caller should already have mangled fullname).
        
        fullname: Fully-package-qualified module name.
        zmodule: ZModule object to load.
        """
        code = self.get_code(zmodule.canonical_name)
        assert code
        module = imp.new_module(fullname)
        sys.modules[fullname] = module
        rootname = zmodule.rootname
        module.__file__ = '%s%s%s.py' % (
         self._par._zip_filename, os.sep, rootname)
        module.__loader__ = self
        if zmodule.is_package:
            dirname = os.path.dirname(rootname)
            par_path = '%s%s%s' % (self._par._zip_filename, os.sep, dirname)
            module.__path__ = [par_path]
            _Log('# Setting %s.__path__ to %s' % (module.__name__, module.__path__))
        zmodule.module = module
        exec code in module.__dict__
        newmodule = sys.modules[fullname]
        zmodule.module = newmodule
        return newmodule


def _InitializeZipImporters(path_list):
    """Examine path_list for python archives and initialize them."""
    importers = []
    for path in path_list:
        try:
            importer = ZipImporter(path)
            _Log('# loaded par file: %s' % path)
            importers.append(importer)
        except ImportError as e:
            if not path.startswith(sys.prefix) and zipfile.is_zipfile(path):
                sys.stderr.write('ZipImport Error: %s\n' % e)

    return importers


def _InstantiateZipImporters():
    """Create ZipImport objects for each zipfile in the path"""
    global _zip_importers
    _Log('# sys.path is: %s' % sys.path)
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
    zipimport = sys.modules['zipimport']
    path_hooks = getattr(sys, 'path_hooks')
    for idx in range(len(path_hooks)):
        if path_hooks[idx] == zipimport.zipimporter:
            path_hooks.insert(idx, ZipImporter)
            break
    else:
        path_hooks.append(ZipImporter)

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
    extract = os.environ.get('AUTOPAR_EXTRACT', autopar_extract_default)
    if extract != 'NONE':
        for z in _zip_importers:
            if extract != 'ALL':
                z._par._ExtractSharedLibraries(extract_dirs=extract_dirs)
            else:
                z._par._ExtractAllFiles(extract_dirs=extract_dirs)

        if extract == 'ALL':
            print 'Successfully extracted all files'
            sys.exit(0)
        elif extract == 'LIBS':
            print 'Successfully extracted shared libraries'
            sys.exit(0)
        elif extract == 'SWIGDEPS':
            print z._par._runfiles_root
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
    return


def Init(main_par_filename, autopar_extract_default, extract_dirs=None):
    """Initialize the import system.
    
    main_par_filename: File containing __main__ module
    autopar_extract_default: one of "ALL", "LIBS", "NONE", "DEFAULT",
      indicating exactly what to extract from the par file.
    extract_dirs: list of strings, each string indicating a path
      to try to decompress needed data.
    
    Returns ZipImporter for main_par_filename
    """
    _InstantiateZipImporters()
    assert len(_zip_importers) > 0, 'Error unzipping par file: %r' % (
     _zip_importers,)
    main_importer = None
    for importer in _zip_importers:
        if importer._par._zip_filename == main_par_filename:
            main_importer = importer
            break

    assert main_importer, 'Error 2 unzipping par file: %r' % _zip_importers
    _InstallImportHook_23()
    _ExtractFiles(autopar_extract_default, extract_dirs=extract_dirs)
    _SetupGooglebase(main_importer)
    return main_importer
# okay decompiling ./google3/tools/autopar/zipimport_tinypar.pyc
