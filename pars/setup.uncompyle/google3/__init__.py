# uncompyle6 version 2.10.1
# Python bytecode 2.7 (62211)
# Decompiled from: Python 3.6.8 (default, Apr 20 2019, 23:18:21) 
# [GCC 8.2.0]
# Embedded file name: google3/__init__.py
# Compiled at: 2019-06-18 16:41:38
"""This is the root of the google3 tree.

Code in here is built by the Google3 build system.
"""
import os
import sys
import warnings

def _SetupPath(old_path, this_dir):
    """Setup package import path for Google3.
    
    old_path: List of directories.
    this_dir: Directory that this package is loaded from.
    
    Allow the google3 package to import subpackages and modules from two
    different directory trees: the VCS client (Piper, CitC, git5 or something
    else) and the READONLY directory (or symlink to srcfs).
    
    This code sets the top-level path, and relies on
    Google3MetaImportHook to propagate the path to subpackages.
    
    Returns a list of three things:
    
    The first is the new package path, consisting of the old package
    path reordered and with extra directories inserted.
    
    The second is a subset of the first, consisting of all the google3
    directories that we might want to take third-party modules from.
    
    The third is a boolean saying whether a READONLY directory was
    found.  If true, the 'directory merging' functionality will be
    activated.  Note that this will never be true if running from a .par
    file, since 'client_root' will be '/somedir/somefile.par' and thus
    '/somedir/somefile.par/READONLY' will not be a directory.
    
    """
    this_dir = os.path.abspath(this_dir)
    parent_dir = os.path.dirname(this_dir)
    if os.path.basename(parent_dir) == 'READONLY':
        client_root = os.path.dirname(parent_dir)
        readwrite_dir = os.path.join(client_root, 'google3')
        readonly_dir = os.path.join(client_root, 'READONLY', 'google3')
        have_readonly_dir = 1
    elif parent_dir.endswith('/READONLY/stateless-client') and parent_dir.startswith('/usr/local/google/'):
        client_root = parent_dir[len('/usr/local/google'):-len('/READONLY/stateless-client')]
        readwrite_dir = os.path.join(client_root, 'google3')
        readonly_dir = os.path.join(parent_dir, 'google3')
        have_readonly_dir = 1
    else:
        client_root = parent_dir
        readwrite_dir = os.path.join(client_root, 'google3')
        readonly_dir = os.path.join(client_root, 'READONLY', 'google3')
        have_readonly_dir = os.path.isdir(readonly_dir)
    google3_path = [
     readwrite_dir]
    if have_readonly_dir:
        google3_path.append(readonly_dir)
    package_path = google3_path[:]
    for pathdir in old_path:
        if pathdir not in package_path:
            package_path.append(pathdir)

    return (package_path, google3_path, have_readonly_dir)


def _FixupParentPathByName(module_name):
    """Given a module name, find its parent package, and fix that package's path.
    
    module_name: Fully-qualified module name
    
    """
    lastdot = module_name.rfind('.')
    if lastdot == -1:
        return
    second_lastdot = module_name.rfind('.', 0, lastdot)
    if second_lastdot == -1:
        return
    parent_name = module_name[:lastdot]
    parent = sys.modules.get(parent_name)
    grandparent_name = module_name[:second_lastdot]
    grandparent = sys.modules.get(grandparent_name)
    if parent and grandparent:
        _MaybeInheritPath(parent_name, parent, grandparent)


def _MaybeInheritPath(package_name, package, package_parent):
    """Given a package, fixup its path if necessary.
    
    package_name: Fully-qualified module name
    package, package_parent_name: Module objects
    """
    if getattr(package, '_g_inherit_processed__', 0):
        return
    if not getattr(package, '_g_inherit_path__', 1):
        return
    if not getattr(package_parent, '_g_inherit_path__', 0):
        return
    _InheritPath(package_name, package, package_parent)


def _InheritPath(package_name, package, package_parent):
    """Compute a path for a package, based on the path of its parent.
    
    If package is named spam.eggs, then for each entry D in
    package_parent's path, add D/eggs to package's path.
    
    package_name: Fully qualified package name
    package, package_parent: Module objects
    
    """
    basename = package_name.split('.')[-1]
    assert basename, 'Contact build-help@google.com'
    orig_package_path = getattr(package, '__path__', [])
    new_path = []
    for pathdir in getattr(package_parent, '__path__', []):
        newdir = os.path.join(pathdir, basename)
        if newdir in orig_package_path or os.path.isdir(newdir):
            new_path.append(newdir)

    for pathdir in orig_package_path:
        if pathdir not in new_path:
            new_path.append(pathdir)

    package.__path__[:] = new_path
    package._g_inherit_path__ = 1
    package._g_inherit_processed__ = 1


class _Python23MergeImportsHook:
    """Propagate package search path to all subpackages of Google3.
    
    This class is a meta-import hook, as defined by Python 2.3 and
    above.  Instead of actually importing anything, it works like a
    pre-import hook to fix up the __path__ in a package object that has
    already been imported.
    
    Consider packages A, A.B, and A.B.C.  A's __path__ contains a list
    of directories.  We want A.B's __path__ to be set to the same list
    of directories, except with '/B' appended to each one.  We could
    update A.B's __path__ when A.B is first imported, but that is
    difficult to implement.  Instead, we allow A.B's path to be
    incorrect until A.B.C is imported.  When A.B.C is imported, this
    hook runs, looks at A's __path__, and copies it with modifications
    to A.B's __path__.  The updated __path__ is then used by the normal
    import mechanism to find A.B.C.
    
    """

    def find_module(self, module_name, unused_path=None):
        """Called by standard Python import mechanism.
        
        module_name: Fully-qualified module name
        unused: List of directories to search, from parent package.
        
        We use this as a signal that a module is about to be imported, and
        fixup its parent's path if necessary.
        
        We then return a failure notification (via 'return None'), so that
        the normal import process continues.
        
        """
        _FixupParentPathByName(module_name)
        return None


_merge_imports_hook_installed = 0

def _SetupMergeImportsHook(have_readonly_dir):
    """Enable hook to merge directory trees for imports.
    
    have_readonly_dir: 1 if [p4 client]/READONLY exists
    """
    global _merge_imports_hook_installed
    if _merge_imports_hook_installed:
        return
    if not have_readonly_dir or os.environ.get('GOOGLE3_DISABLE_MERGE_IMPORTS'):
        return
    _merge_imports_hook_installed = 1
    meta_path = getattr(sys, 'meta_path', [])
    meta_path.append(_Python23MergeImportsHook())


def _SetupThirdParty(sys_path, google3_path):
    """Setup import path to code in google3/third_party/py.
    
    sys_path: Original sys.path
    google3_path: Google3 dirs being added to sys.path
    
    Returns nothing, modifies sys_path in place.
    """
    third_party_path = [ os.path.join(d, 'third_party', 'py') for d in google3_path
                       ]
    found_site_packages = idx = 0
    for idx in range(len(sys_path)):
        dirname = sys_path[idx]
        if dirname.find('site-packages') != -1:
            found_site_packages = 1
            break

    if found_site_packages:
        sys_path[idx:idx] = third_party_path
    else:
        sys_path.extend(third_party_path)
    path_hooks = getattr(sys, 'path_hooks', [])
    _CheckThirdParty(third_party_path, path_hooks, sys.modules)
    return None


def _CheckThirdParty(third_party_path, path_hooks, sys_modules):
    """Check for erroneous imports from site-packages directory.
    
    third_party_path: List of path entries.  Each is an absolute
                      directory name, but may be a pseudo-path formed by
                      concatenating a .par filename with a subdir.
                      E.g. '/home/zog/src1/google3/third_party/py' or
                      '/root/myprog.par/google3/third_party/py'.
    
    For each top-level module or package that was imported from Python's
    site-package directory, but should have been imported from
    [client]/google3/third_party/py instead, issue a warning message.
    
    We try to determine this with a minimum of I/O, and without fully
    reimplementing import().  So we use heuristics: We only look at top
    level modules or packages (no dots), and we assume that every file
    or directory in google3/third_party/py is a module or package name.
    Since we control google3/third_party/py, this is generally safe.
    
    Returns a list of problematic modules
    """
    path_data = _ExaminePath(third_party_path, path_hooks)
    problems = []
    for module_name, module in sys_modules.items():
        if module_name.find('.') == -1:
            fn = getattr(module, '__file__', None)
            if fn and fn.find('site-packages') != -1:
                third_party_fn = _FindInPath(module_name, path_data)
                if third_party_fn:
                    msg = '%s is deprecated, use %s instead.  To fix this, move "import google3" or "from google3... import ..." before "import %s" in your main source file.' % (
                     fn, third_party_fn,
                     module_name)
                    warnings.warn(msg, DeprecationWarning, stacklevel=2)
                    problems.append((fn, third_party_fn, module_name))

    return problems


def _ExaminePath(dirs, path_hooks):
    """Determine the type and contents of a list of import path entries.
    
    dirs:  List of path entries as above.
    path_hooks: Contents of sys.path_hooks
    
    We categorize each directory as 1) real directory or 2) zipfile.
    There is no usable Python-level API to access the import internals,
    so we have to reimplement sys.path_hooks
    processing. [imp.find_module() doesn't work because it wasn't
    updated when new-style import hooks were added to Python 2.3]
    
    Returns a list of (path, [dir contents if real dir], loader if zipfile)
    """
    path_data = []
    for dirname in dirs:
        files = []
        try:
            files = []
            for f in os.listdir(dirname):
                base, ext = os.path.splitext(f)
                if not ext or ext.startswith('.py'):
                    files.append(base)

        except EnvironmentError:
            pass

        loader = None
        for path_hook in path_hooks:
            try:
                loader = path_hook(dirname)
                break
            except ImportError:
                pass

        path_data.append([dirname, files, loader])

    return path_data


def _FindInPath(module_name, path_data):
    """Heuristic search for a module in a set of directories.
    
    module_name: top-level module name.  E.g. 'MySQLdb'
    path_data: List of (path, [dir contents if real dir], loader if zipfile)
    
    Returns the filename to the module or package dir, or None if not found.
    """
    assert '.' not in module_name, 'Contact build-help@google.com'
    for path, files, loader in path_data:
        if module_name in files:
            package_fn = os.path.join(path, module_name)
            init_fn = os.path.join(package_fn, '__init__.py')
            if os.path.exists(init_fn):
                return package_fn
        if loader and loader.find_module(module_name):
            return os.path.join(path, module_name)

    return None


def _SetupSwig():
    """Setup environment for Blaze built extension modules."""
    if sys.platform in ('win32', 'darwin'):
        return
    else:
        launcher_info = sys.modules.get('_launcher_info')
        if launcher_info is not None and launcher_info.is_google3_python_launcher:
            return
        native_code_deps_dso = os.environ.get('GOOGLE3_NATIVE_CODE_DEPS_DSO')
        native_code_deps_needed = os.environ.get('GOOGLE3_NATIVE_CODE_DEPS_NEEDED')
        ld_preload = os.environ.get('LD_PRELOAD')
        if native_code_deps_dso and ld_preload:
            parts = ld_preload.split()
            other_parts = [ part for part in parts if part != native_code_deps_dso ]
            if parts and not other_parts:
                del os.environ['LD_PRELOAD']
                return
            if len(other_parts) != len(parts):
                os.environ['LD_PRELOAD'] = ' '.join(other_parts)
                return
        if native_code_deps_dso:
            try:
                import ctypes
            except ImportError:
                if native_code_deps_needed:
                    raise
                return

            try:
                ctypes.CDLL(native_code_deps_dso, ctypes.RTLD_GLOBAL)
            except OSError:
                if native_code_deps_needed:
                    raise

            if native_code_deps_needed:
                del os.environ['GOOGLE3_NATIVE_CODE_DEPS_NEEDED']
        return


def _SetupHookModule():
    """Import an early startup hook if one has been specified in the environment.
    
    The GOOGLE3_PY_HOOK_MODULE environment variable, if set and not empty, must
    be a string of the form "google3.path.to.my.module".  This module must be in
    the runtime dependencies of the py_binary or py_test or an ImportError will
    result.  It will be imported upon the first google3 import - normally before
    most code runs - well before main(), flag parsing, or InitGoogle.
    
    Users may use it to implement a non-standard debugger to make the py_binary
    or py_test load their debugger by setting GOOGLE3_PY_HOOK_MODULE in their
    environment.
    """
    hook_module = os.environ.get('GOOGLE3_PY_HOOK_MODULE', '')
    if hook_module:
        try:
            import importlib
            importlib.import_module(hook_module)
        except ImportError:
            pass


if sys.version_info[:2] not in ((2, 6), (2, 7)):
    _msg = 'Python %d.%d is unsupported; use 2.7' % sys.version_info[:2]
    warnings.warn(_msg, DeprecationWarning, stacklevel=1)
basedir = os.path.dirname(os.path.abspath(__file__))
TYPE_CHECKING = False
_g_inherit_path__ = 1
_g_inherit_processed__ = 1
__path__ = globals().get('__path__', [])
__path__, _google3_path, _have_readonly_dir = _SetupPath(__path__, basedir)
_SetupMergeImportsHook(_have_readonly_dir)
_SetupThirdParty(sys.path, _google3_path)
_SetupSwig()
_SetupHookModule()
# okay decompiling ./google3/__init__.pyc
