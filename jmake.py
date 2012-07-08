"""
jmake.py
Python-powered build utility for C and C++
Uses advanced techniques to reduce build time to a minimum, while attempting to always ensure that  the correct build
operations are performed every time without need of a clean operation. Eliminates redundant and unnecessary build
operations, and incorporates the Unity Build concept for larger builds to speed up project compilation, while avoiding
it for smaller build operations to speed up iteration.

See www.github.net/ShadauxCat/JMake for more information and documentation.
"""

import argparse
import subprocess
import os
import fnmatch
import sys
import re
import threading
import multiprocessing
import shutil
import itertools
import hashlib

#NOTE: All this <editor-fold desc="Whatever"> stuff is specific to the PyCharm editor, which allows custom folding blocks.

#<editor-fold desc="Logging">

#Initialize logging...

try:
   subprocess.check_output(["tput", "colors"], stderr=subprocess.STDOUT)
except subprocess.CalledProcessError as e:
   _color_supported = False
else:
   _color_supported = True

def LOG_MSG(color, level, msg):
   """Print a message to stdout"""
   if _color_supported:
      print " ", "\033[{0};1m{1}:\033[0m".format(color, level), msg
   else:
      print " ", level+":", msg

def LOG_ERROR(msg):
   """Log an error message"""
   if _quiet >= 3:
      return
   global _errors
   LOG_MSG(31, "ERROR", msg)
   _errors.append(msg)

def LOG_WARN(msg):
   """Log a warning"""
   if _quiet >= 3:
      return
   global _warnings
   LOG_MSG(33, "WARN", msg)
   _warnings.append(msg)

def LOG_INFO(msg):
   """Log general info"""
   if _quiet >= 1:
      return
   LOG_MSG(36, "INFO", msg)

def LOG_BUILD(msg):
   """Log info related to building"""
   if _quiet >= 2:
      return
   LOG_MSG(35, "BUILD", msg)

def LOG_LINKER(msg):
   """Log info related to linking"""
   if _quiet >= 2:
      return
   LOG_MSG(32, "LINKER", msg)

def LOG_THREAD(msg):
   """Log info related to threads, particularly stalls caused by waiting on another thread to finish"""
   if _quiet >= 2:
      return
   LOG_MSG(34, "THREAD", msg)

def LOG_INSTALL(msg):
   """Log info related to the installer"""
   if _quiet >= 2:
      return
   LOG_MSG(37, "INSTALL", msg)

#</editor-fold>

#<editor-fold desc="Private">
#<editor-fold desc="Private Variables">
#Private Variables
_libraries = []

_include_dirs = [
   "/usr/include",
   "/usr/local/include"
]

_library_dirs = [
   "/usr/lib",
   "/usr/local/lib"
]

_opt_level = 0
_debug_level = 0
_warn_flags = []
_flags = []
_defines = []
_undefines = []
_compiler = "g++"
_obj_dir = "."
_output_dir = "."
_jmake_dir = "./.jmake"
_output_name = "JMade"
_output_install_dir = ""
_header_install_dir = ""
_automake = True
_standard = ""

_c_files = []
_headers = []

_shared = False
_profile = False

_max_threads = multiprocessing.cpu_count()

_semaphore = threading.BoundedSemaphore(value=_max_threads)
_lock = threading.Lock()

_extra_flags = ""
_linker_flags = ""

_exclude_dirs = []
_exclude_files = []

_built_something = False
_build_success = True
_called_something = False
_overrides = ""

_library_mtimes = []

_output_dir_set = False
_obj_dir_set = False
_debug_set = False
_opt_set = False

_errors = []
_warnings = []

_allheaders = {}
_chunks = []

_quiet = 1

_use_chunks = True
_chunk_tolerance = 3
_chunk_size = 10
_interrupted = False

_header_recursion = 0
_ignore_external_headers = False

_no_warnings = False

_default_target = "debug"
#</editor-fold>

#<editor-fold desc="Private Functions">
#Private Functions
def _get_warnings():
   """Returns a string containing all of the passed warning flags, formatted to be passed to gcc/g++."""
   if _no_warnings:
      return "-w "
   ret = ""
   for flag in _warn_flags:
      ret += "-W{0} ".format(flag)
   return ret

def _get_defines():
   """Returns a string containing all of the passed defines and undefines, formatted to be passed to gcc/g++."""
   ret = ""
   for define in _defines:
      ret += "-D{0} ".format(define)
   for undefine in _undefines:
      ret += "-U{0} ".format(undefine)
   return ret

def _get_include_dirs():
   """Returns a string containing all of the passed include directories, formatted to be passed to gcc/g++."""
   ret = ""
   for inc in _include_dirs:
      ret += "-I{0} ".format(inc)
   return ret
   
def _get_libraries():
   """Returns a string containing all of the passed libraries, formatted to be passed to gcc/g++."""
   ret = ""
   for lib in _libraries:
      ret += "-l{0} ".format(lib)
   return ret

def _get_library_dirs():
   """Returns a string containing all of the passed library dirs, formatted to be passed to gcc/g++."""
   ret = ""
   for lib in _library_dirs:
      ret += "-L{0} ".format(lib)
   return ret

def _get_flags():
   """Returns a string containing all of the passed flags, formatted to be passed to gcc/g++."""
   ret = ""
   for flag in _flags:
      ret += "-f{0} ".format(flag)
   return ret

def _get_files(sources=None, headers=None):
   """Steps through the current directory tree and finds all of the source and header files, and returns them as a list.
   Accepts two lists as arguments, which it populates. If sources or headers are excluded from the parameters, it will
   ignore files of the relevant types.
   """
   for root, dirnames, filenames in os.walk('.'):
      if root in _exclude_dirs:
         continue
      if sources is not None:
         for filename in fnmatch.filter(filenames, '*.cpp'):
            path = os.path.join(root, filename)
            if path not in _exclude_files:
               sources.append(path)
         for filename in fnmatch.filter(filenames, '*.c'):
            path = os.path.join(root, filename)
            if path not in _exclude_files:
               sources.append(path)

         sources.sort(key=str.lower)

      if headers is not None:
         for filename in fnmatch.filter(filenames, '*.hpp'):
            path = os.path.join(root, filename)
            if path not in _exclude_files:
               headers.append(path)
         for filename in fnmatch.filter(filenames, '*.h'):
            path = os.path.join(root, filename)
            if path not in _exclude_files:
               headers.append(path)

         headers.sort(key=str.lower)

def _follow_headers(file, allheaders):
   """Follow the headers in a file.
   First, this will check to see if the given header has been followed already.
   If it has, it pulls the list from the _allheaders global dictionary and returns it.
   If not, it populates a new allheaders list with _follow_headers2, and then adds
   that to the _allheaders dictionary
   """
   headers = []
   global _allheaders
   if not file:
      return
   with open(file) as f:
      for line in f:
         if line[0] != '#':
            continue

         RMatch = re.search("#include [<\"](.*?)[\">]", line)
         if RMatch is None:
            continue

         if "." not in RMatch.group(1):
            continue

         headers.append(RMatch.group(1))

   for header in headers:
      #If we've already looked at this header (i.e., it was included twice) just ignore it
      if header in allheaders:
         continue

      #Find the header in the listed includes.
      path = "{0}/{1}".format(os.path.dirname(file), header)
      if not os.path.exists(path):
         for dir in _include_dirs:
            path = "{0}/{1}".format(dir, header)
            if os.path.exists(path):
               break
      #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
      #Just ignore them to speed things up.
      if not os.path.exists(path):
         continue

      if _ignore_external_headers and not path.startswith("./"):
         continue

      allheaders.append(header)

      if _header_recursion != 1:
         #Check to see if we've already followed this header.
         #If we have, the list we created from it is already stored in _allheaders under this header's key.
         try:
            allheaders += _allheaders[header]
         except KeyError:
            pass
         else:
            continue

         _follow_headers2(path, allheaders, 1)

      _allheaders.update({header : allheaders})

def _follow_headers2(file, allheaders, n):
   """More intensive, recursive, and cpu-hogging function to follow a header.
   Only executed the first time we see a given header; after that the information is cached."""
   headers = []
   if not file:
      return
   with open(file) as f:
      for line in f:
         if line[0] != '#':
            continue

         RMatch = re.search("#include [<\"](.*?)[\">]", line)
         if RMatch is None:
            continue

         if "." not in RMatch.group(1):
            continue

         headers.append(RMatch.group(1))

   for header in headers:
      #Check to see if we've already followed this header.
      #If we have, the list we created from it is already stored in _allheaders under this header's key.
      if header in allheaders:
         continue

      if header in _allheaders:
         continue

      path = "{0}/{1}".format(os.path.dirname(file), header)
      if not os.path.exists(path):
         for dir in _include_dirs:
            path = "{0}/{1}".format(dir, header)
            if os.path.exists(path):
               break
      #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
      #Just ignore them to speed things up.
      if not os.path.exists(path):
         continue

      if _ignore_external_headers and not path.startswith("./"):
         continue

      allheaders.append(header)
      if _header_recursion == 0 or n < _header_recursion:
         _follow_headers2(path, allheaders, n+1)

def _should_recompile(file):
   """Checks various properties of a file to determine whether or not it needs to be recompiled."""

   basename = os.path.basename(file).split('.')[0]
   ofile = "{0}/{1}_{2}.o".format(_obj_dir, basename, target)

   if _use_chunks:
      chunk = _get_chunk(file)
      chunkfile = "{0}/{1}_{2}.o".format(_obj_dir, chunk, target)

      #First check: If the object file doesn't exist, we obviously have to create it.
      if not os.path.exists(ofile):
         ofile = chunkfile

   if not os.path.exists(ofile):
      LOG_INFO("Going to recompile {0} because the associated object file does not exist.".format(file))
      return True

   #Third check: modified time.
   #If the source file is newer than the object file, we assume it's been changed and needs to recompile.
   mtime = os.path.getmtime(file)
   omtime = os.path.getmtime(ofile)


   with open(file, "r") as f:
      newmd5 = hashlib.md5(f.read()).digest()
   md5file = "{0}/{1}.md5".format(_jmake_dir, file)
   md5dir = os.path.dirname(md5file)
   if not os.path.exists(md5dir):
      os.makedirs(md5dir)

   if mtime > omtime:
      oldmd5 = None
      if os.path.exists(md5file):
         with open(md5file, "r") as f:
            oldmd5 = f.read()

      if oldmd5 != newmd5:
         LOG_INFO("Going to recompile {0} because it has been modified since the last successful build.".format(file))

         with open(md5file, "w") as f:
            f.write(newmd5)
         return True

   with open(md5file, "w") as f:
      f.write(newmd5)

   #Fourth check: Header files
   #If any included header file (recursive, to include headers included by headers) has been changed,
   #then we need to recompile every source that includes that header.
   #Follow the headers for this source file and find out if any have been changed o necessitate a recompile.
   headers = []
   _follow_headers(file, headers)

   for header in headers:
      path = "{0}/{1}".format(os.path.dirname(file), header)
      if not os.path.exists(path):
         for dir in _include_dirs:
            path = "{0}/{1}".format(dir, header)
            if os.path.exists(path):
               break
      #A lot of standard C and C++ headers will be in a compiler-specific directory that we won't check.
      #Just ignore them to speed things up.
      if not os.path.exists(path):
         continue

      header_mtime = os.path.getmtime(path)
      if header_mtime > omtime:
         LOG_INFO("Going to recompile {0} because included header {1} has been modified since the last successful build.".format(file, header))
         return True

   #If we got here, we assume the object file's already up to date.
   LOG_INFO("Skipping {0}: Already up to date".format(file))
   return False

def _check_libraries():
   """Checks the libraries designated by the make script.
   Invokes ld to determine whether or not the library exists.
   Uses the -t flag to get its location.
   And then stores the library's last modified time to a global list to be used by the linker later, to determine
   whether or not a project with up-to-date objects still needs to link against new libraries.
   """
   libraries_ok = True
   LOG_INFO("Checking required libraries...")
   for library in _libraries:
      LOG_INFO("Looking for lib{0}...".format(library))
      success = True
      out = ""
      try:
         out = subprocess.check_output(["ld", "-t", "-l{0}".format(library)], stderr=subprocess.STDOUT)
      except subprocess.CalledProcessError as e:
         out = e.output
         success = False
      finally:
         mtime = 0
         RMatch = re.search("-l{0} \\((.*)\\)".format(library), out)
         #Some libraries (such as -liberty) will return successful but don't have a file (internal to ld maybe?)
         #In those cases we can probably assume they haven't been modified.
         #Set the mtime to 0 and return success as long as ld didn't return an error code.
         if RMatch is not None:
               lib = RMatch.group(1)
               mtime = os.path.getmtime(lib)
         elif not success:
            LOG_ERROR("Could not locate library: {0}".format(library))
            libraries_ok = False
         _library_mtimes.append(mtime)
   if not libraries_ok:
      LOG_ERROR("Some dependencies are not met on your system.")
      LOG_ERROR("Check that all required libraries are installed.")
      LOG_ERROR("If they are installed, ensure that the path is included in the makefile (use jmake.LibDirs() to set them)")
      return False
   LOG_INFO("Libraries OK!")
   return True

class _dummy_block(object):
   """Some versions of python have a bug in threading where a dummy thread will try and use a value that it deleted.
   To keep that from erroring on systems with those versions of python, this is a dummy object with the required
   methods in it, which can be recreated in __init__ for the thread object to prevent this bug from happening.
   """
   def __init__(self):
      """Dummy __init__ method"""
      return

   def acquire(self):
      """Dummy acquire method"""
      return

   def release(self):
      """Dummy release method"""
      return

   def notify_all(self):
      """Dummy notify_all method"""
      return

class _threaded_build(threading.Thread):
   """Multithreaded build system, launches a new thread to run the compiler in.
   Uses a threading.BoundedSemaphore object to keep the number of threads equal to the number of processors on the machine.
   """
   def __init__(self, infile, inobj):
      """Initialize the object. Also handles above-mentioned bug with dummy threads."""
      threading.Thread.__init__(self)
      self.file = infile
      self.obj = inobj
      #Prevent certain versions of python from choking on dummy threads.
      if not hasattr(threading.Thread, "_Thread__block"):
         threading.Thread._Thread__block = _dummy_block()

   def run(self):
      """Actually run the build process."""
      try:
         global _build_success
         cmd = "{0} -pass-exit-codes -c {1}{2}{3}-g{4} -O{5} {6}{7}{8}{11}{12} -o\"{9}\" \"{10}\"".format(_compiler, _get_warnings(), _get_defines(), _get_include_dirs(), _debug_level, _opt_level, "-fPIC " if _shared else "", "-pg " if _profile else "", "--std={0}".format(_standard) if _standard != "" else "", self.obj, self.file, _get_flags(), _extra_flags)
         #We have to use os.system here, not subprocess.call. For some reason, subprocess.call likes to freeze here, but os.system works fine.
         ret = os.system(cmd)
         if ret:
            if str(ret) == "2":
               _lock.acquire()
               global _interrupted
               if not _interrupted:
                  LOG_ERROR("Keyboard interrupt received. Aborting build.")
               _interrupted = True
               _lock.release()
            if not _interrupted:
               LOG_ERROR("Compile of {0} failed!".format(self.file, ret))
            _build_success = False
      except Exception as e:
         #If we don't do this with ALL exceptions, any unhandled exception here will cause the semaphore to never release...
         #Meaning the build will hang. And for whatever reason ctrl+c won't fix it.
         #ABSOLUTELY HAVE TO release the semaphore on ANY exception.
         if os.path.dirname(self.file) == _jmake_dir:
            os.remove(self.file)
         _semaphore.release()
         raise e
      else:
         if os.path.dirname(self.file) == _jmake_dir:
            os.remove(self.file)
         _semaphore.release()

def _make_chunks(l):
   """ Converts the list into a list of lists - i.e., "chunks"
   Each chunk represents one compilation unit in the chunked build system.
   """
   if not _use_chunks:
      return [l]
   chunks = []
   for i in xrange(0, len(l), _chunk_size):
      chunks.append(l[i:i+_chunk_size])
   return chunks

def _get_chunk(file):
   """Retrieves the chunk that a given file belongs to."""
   for chunk in _chunks:
      if file in chunk:
         return "{0}_chunk_{1}_to_{2}".format(_output_name, os.path.basename(chunk[0]).split(".")[0], os.path.basename(chunk[-1]).split(".")[0])

def _chunked_build(sources):
   """Prepares the files for a chunked build.
   This function steps through all of the sources that are on the slate for compilation and determines whether each
   needs to be compiled individually or as a chunk. If it is to be compiled as a chunk, this function also creates
   the chunk file to be compiled. It then returns an updated list of files - individual files, chunk files, or both -
   that are to be compiled.
   """
   chunks = []

   chunks_to_build = []
   for source in sources:
      chunk = _get_chunk(source)
      file = "{0}/{1}_chunk_{2}_to_{3}.cpp".format(_jmake_dir, _output_name, os.path.basename(chunk[0]).split(".")[0], os.path.basename(chunk[-1]).split(".")[0])
      if chunk not in chunks_to_build and os.path.exists(file):
         chunks_to_build.append(chunk)

   dont_split = False
   if len(chunks_to_build) > max(len(chunks)/4, 2):
      LOG_INFO("Not splitting any existing chunks because we would have to build too many.")
      dont_split = True

   for chunk in _chunks:
      sources_in_this_chunk = []
      for source in sources:
         if source in chunk:
            sources_in_this_chunk.append(source)

      file = "{0}/{1}_chunk_{2}_to_{3}.cpp".format(_jmake_dir, _output_name, os.path.basename(chunk[0]).split(".")[0], os.path.basename(chunk[-1]).split(".")[0])

      #If only one or two sources in this chunk need to be built, we get no benefit from building it as a unit. Split unless we're told not to.
      if len(sources_in_this_chunk) > _chunk_tolerance or (dont_split and os.path.exists(file) and len(sources_in_this_chunk) > 0):
         LOG_INFO("Going to build chunk {0} as {1}".format(chunk, file))
         if not os.path.exists(_jmake_dir):
            os.makedirs(_jmake_dir)
         with open(file, "w") as f:
            f.write("//Automatically generated file, do not edit.\n")
            for source in chunk:
               f.write('#include "{0}"\n'.format(os.path.abspath(source)))
               obj = "{0}/{1}_{2}.o".format(_obj_dir, os.path.basename(source).split('.')[0], target)
               if os.path.exists(obj):
                  os.remove(obj)

         chunks.append(file)
      elif len(sources_in_this_chunk) > 0:
         chunkname = "{0}_chunk_{1}_to_{2}".format(_output_name, os.path.basename(chunk[0]).split(".")[0], os.path.basename(chunk[-1]).split(".")[0])
         obj = "{0}/{1}_{2}.o".format(_obj_dir, chunkname, target)
         if os.path.exists(obj):
            #If the chunk object exists, the last build of these files was the full chunk.
            #We're now splitting the chunk to speed things up for future incremental builds, which means the chunk
            #is getting deleted and *every* file in it needs to be recompiled this time only.
            #The next time any of these files changes, only that section of the chunk will get built.
            #This keeps large builds fast through the chunked build, without sacrificing the speed of smaller
            #incremental builds (except on the first build after the chunk)
            os.remove(obj)
            add_chunk = chunk
            LOG_WARN("Breaking chunk ({0}) into individual files to improve future iteration turnaround.".format(chunk))
         else:
            add_chunk = sources_in_this_chunk
         if len(add_chunk) == 1:
            LOG_INFO("Going to build {0} as an individual file.".format(add_chunk))
         else:
            LOG_INFO("Going to build chunk {0} as individual files.".format(add_chunk))
         chunks += add_chunk

   return chunks

#</editor-fold>
#</editor-fold>

#<editor-fold desc="Public">
#<editor-fold desc="Public Variables">
#Public Variables
target = "release"
CleanBuild = False
do_install = False
#</editor-fold>

#<editor-fold desc="Setters">
#Setters
def InstallOutput( s = "/usr/local/lib" ):
   """Enables installation of the compiled output file. Default target is /usr/local/lib."""
   global _output_install_dir
   _output_install_dir = s

def InstallHeaders( s = "/usr/local/include" ):
   """Enables installation of the project's headers. Default target is /usr/local/include."""
   global _header_install_dir
   _header_install_dir = s

def ExcludeDirs( *args ):
   """Excludes the given subdirectories from the build. Accepts multiple string arguments."""
   args = list(args)
   newargs = []
   for arg in args:
      if arg[0] != '/' and not arg.startswith("./"):
         arg = "./" + arg
      newargs.append(arg)
   global _exclude_dirs
   _exclude_dirs += newargs

def ExcludeFiles( *args ):
   """Excludes the given files from the build. Accepts multiple string arguments."""
   args = list(args)
   newargs = []
   for arg in args:
      if arg[0] != '/' and not arg.startswith("./"):
         arg = "./" + arg
      newargs.append(arg)
   global _exclude_files
   _exclude_files += newargs


def Libraries( *args ):
   """List of libraries to link against. Multiple string arguments. gcc/g++ -l."""
   global _libraries
   _libraries += list(args)

def IncludeDirs( *args ):
   """List of directories to search for included headers. Multiple string arguments. gcc/g++ -I
   By default, this list contains /usr/include and /usr/local/include.
   Using this function will add to the existing list, not replace it.
   """
   global _include_dirs
   _include_dirs += list(args)

def LibDirs( *args ):
   """List of directories to search for libraries. Multiple string arguments. gcc/g++ -L
   By default, this list contains /usr/lib and /usr/local/lib
   Using this function will add to the existing list, not replace it"""
   global _library_dirs
   _library_dirs += list(args)
   
def ClearLibraries( ):
   """Clears the list of libraries"""
   global _libraries
   _libraries = []

def ClearIncludeDirs( ):
   """Clears the include directories, including the defaults."""
   global _include_dirs
   _include_dirs = []

def ClearLibDirs( ):
   """Clears the library directories, including the defaults"""
   global _library_dirs
   _library_dirs = []

def Opt(i):
   """Sets the optimization level. gcc/g++ -O"""
   global _opt_level
   global _opt_set
   _opt_level = i
   _opt_set = True

def Debug(i):
   """Sets the debug level. gcc/g++ -g"""
   global _debug_level
   global _debug_set
   _debug_level = i
   _debug_set = True
   
def Define( *args ):
   """Sets defines for the project. Accepts multiple arguments. gcc/g++ -D"""
   global _defines
   _defines += list(args)
   
def ClearDefines( ):
   """clears the list of defines"""
   global _defines
   _defines = []
   
def Undefine( *args ):
   """Sets undefines for the project. Multiple arguments. gcc/g++ -U"""
   global _undefines
   _undefines += list(args)
   
def ClearUndefines( ):
   """clears the list of undefines"""
   global _undefines
   _undefines = []
   
def Compiler(s):
   """Sets the compiler to use for the project. Default is g++"""
   global _compiler
   _compiler = s
   
def Output(s):
   """Sets the output file for the project. If unset, the project will be compiled as "JMade"""""
   global _output_name
   _output_name = s
   
def OutDir(s):
   """Sets the directory to place the compiled result"""
   global _output_dir
   global _output_dir_set
   _output_dir = s
   _output_dir_set = True
   
def ObjDir(s):
   """Sets the directory to place pre-link objects"""
   global _obj_dir
   global _obj_dir_set
   _obj_dir = s
   _obj_dir_set = True
   
def WarnFlags( *args ):
   """Sets warn flags for the project. Multiple arguments. gcc/g++ -W"""
   global _warn_flags
   _warn_flags += list(args)
   
def ClearWarnFlags( ):
   """Clears the list of warning flags"""
   global _warn_flags
   _warn_flags = []
   
def Flags( *args ):
   """Sets miscellaneous flags for the project. Multiple arguments. gcc/g++ -f"""
   global _flags
   _flags += list(args)
   
def ClearFlags( ):
   """Clears the list of misc flags"""
   global _flags
   _flags = []
   
def DisableAutoMake():
   """Disables the automatic build of the project at conclusion of the script
   If you turn this off, you will need to explicitly call either make() to build and link,
   or build() and link() to take each step individually
   """
   global _automake
   _automake = False
   
def EnableAutoMake():
   """Turns the automatic build back on after disabling it"""
   global _automake
   _automake = True
   
def Shared():
   """Builds the project as a shared library. Enables -shared in the linker and -fPIC in the compiler."""
   global _shared
   _shared = True

def NotShared():
   """Turns shared object mode back off after it was enabled."""
   global _shared
   _shared = False
   
def Profile():
   """Enables profiling optimizations. gcc/g++ -pg"""
   global _profile
   _profile = True
   
def Unprofile():
   """Turns profiling back off."""
   global _profile
   _profile = False
   
def ExtraFlags(s):
   """Literal string of extra flags to be passed directly to the compiler"""
   global _extra_flags
   _extra_flags = s
   
def ClearExtraFlags():
   """Clears the extra flags string"""
   global _extra_flags
   _extra_flags = ""

def LinkerFlags(s):
   """Literal string of extra flags to be passed directly to the linker"""
   global _linker_flags
   _linker_flags = s

def ClearLinkerFlags():
   """Clears the linker flags string"""
   global _linker_flags
   _linker_flags = ""
   
def Standard(s):
   """The C/C++ standard to be used when compiling. gcc/g++ --std"""
   global _standard
   _standard = s

def DisableChunkedBuild():
   """Turn off the chunked/unity build system and build using individual files."""
   global _use_chunks
   _use_chunks = False

def EnableChunkedBuild():
   """Turn chunked/unity build on and build using larger compilation units. This is the default."""
   global _use_chunks
   _use_chunks = True

def ChunkSize(i):
   """Set the size of the chunks used in the chunked build. This indicates the number of files per compilation unit.
   The default is 10.
   This value is ignored if SetChunks is called.
   """
   global _chunk_size
   _chunk_size = i

def ChunkTolerance(i):
   """Set the number of files above which the files will be built as a chunk.
   For example, if you set this to 3 (the default), then a chunk will be built as a chunk
   if more than three of its files need to be built; if three or less need to be built, they will
   be built individually to save build time.
   """
   global _chunk_tolerance
   _chunk_tolerance = i

def SetChunks(*chunks):
   """Explicitly set the chunks used as compilation units.
   This accepts multiple arguments, each of which should be a list of files.
   Each list is one chunk.
   NOTE that setting this will disable the automatic file gathering, so any files you have
   """
   global _chunks
   chunks = list(chunks)
   _chunks = chunks

def ClearChunks():
   """Clears the explicitly set list of chunks and returns the behavior to the default."""
   global _chunks
   _chunks = []

def HeaderRecursionLevel(i):
   """Sets the depth to search for header files. If set to 0, it will search with unlimited recursion to find included
   headers. Otherwise, it will travel to a depth of i to check headers. If set to 1, this will only check first-level
   headers and not check headers included in other headers; if set to 2, this will check headers included in headers,
   but not headers included by *those* headers; etc.

   This is very useful if you're using a large library (such as boost) or a very large project and are experiencing
   long waits prior to compilation.
   """
   global _header_recursion
   _header_recursion = i

def IgnoreExternalHeaders():
   """If this option is set, external headers will not be checked or followed when building. Only headers within the
   base project's directory and its subdirectories will be checked. This will speed up header checking, but if you
   modify any external headers, you will need to manually --clean the project.
   """
   global _ignore_external_headers
   _ignore_external_headers = True

def DisableWarnings():
   """Disables ALL warnings, including gcc/g++'s built-in warnings."""
   global _no_warnings
   _no_warnings = True

def DefaultTarget(s):
   """Sets the default target if none is specified. The default value for this is release."""
   global _default_target
   _default_target = s.lower()

#</editor-fold>

#<editor-fold desc="Workers">
def build():
   """Build the project.
   This step handles:
   Checking library dependencies.
   Checking which files need to be built.
   And spawning a build thread for each one that does.
   """
   if not _check_libraries():
      return False

   sources = []

   global _chunks
   if not _chunks:
      allsources = []

      _get_files(allsources)

      if not allsources:
         return True

      #We'll do this even if _use_chunks is false, because it simplifies the linker logic.
      _chunks = _make_chunks(allsources)
   else:
      allsources = list(itertools.chain(*_chunks))

   for source in allsources:
      if _should_recompile(source):
         sources.append(source)

   if _use_chunks:
      sources = _chunked_build(sources)

   if sources:
      global _built_something
      _built_something = True
      global _build_success
      LOG_BUILD("Building {0} ({1})".format(_output_name, target))

      if not os.path.exists(_obj_dir):
         os.makedirs(_obj_dir)

      global _jmake_dir
      _jmake_dir = "{0}/.jmake".format(_obj_dir)
      if not os.path.exists(_jmake_dir):
         os.makedirs(_jmake_dir)

      global _max_threads

      for source in sources:
         obj = "{0}/{1}_{2}.o".format(_obj_dir, os.path.basename(source).split('.')[0], target)
         if not _semaphore.acquire(False):
            if _max_threads != 1:
               LOG_THREAD("Waiting for a build thread to become available...")
            _semaphore.acquire(True)
         if _interrupted:
            sys.exit(2)
         LOG_BUILD("Building {0}...".format(obj))
         _threaded_build(source, obj).start()

      #Wait until all threads are finished. Simple way to do this is acquire the semaphore until it's out of resources.
      for i in range(_max_threads):
         if _max_threads != 1 and not _semaphore.acquire(False):
            LOG_THREAD("Waiting on {0} more build thread{1} to finish...".format(_max_threads - i, "s" if _max_threads - i != 1 else ""))
            _semaphore.acquire(True)
            if _interrupted:
               sys.exit(2)

      #Then immediately release all the semaphores once we've reclaimed them.
      #We're not using any more threads so we don't need them now.
      for i in range(_max_threads):
         _semaphore.release()

      return _build_success

   else:
      LOG_BUILD("Nothing to build.")
      return True
   
def link(*objs):
   """Linker:
   Links all the built files.
   Accepts an optional list of object files to link; if this list is not provided it will use the auto-generated list created by build()
   This function also checks (if nothing was built) the modified times of all the required libraries, to see if we need
   to relink anyway, even though nothing was compiled.
   """
   output = "{0}/{1}".format(_output_dir, _output_name)

   objs = list(objs)
   if not objs:
      for chunk in _chunks:
         obj = "{0}/{1}_chunk_{2}_to_{3}_{4}.o".format(_obj_dir, _output_name, os.path.basename(chunk[0]).split(".")[0], os.path.basename(chunk[-1]).split(".")[0], target)
         if _use_chunks and os.path.exists(obj):
            objs.append(obj)
         else:
            for source in chunk:
               obj = "{0}/{1}_{2}.o".format(_obj_dir, os.path.basename(source).split('.')[0], target)
               if os.path.exists(obj):
                  objs.append(obj)
               else:
                  LOG_ERROR("Some object files are missing. Either the build failed, or you haven't built yet.")
                  return

   if not objs:
      return

   global _built_something
   if not _built_something:
      if os.path.exists(output):
         mtime = os.path.getmtime(output)
         for obj in objs:
            if os.path.getmtime(obj) != mtime:
               #If the obj time is later, something got built in another run but never got linked...
               #Maybe the linker failed last time.
               #We should count that as having built something, because we do need to link.
               #Otherwise, if the object time is earlier, there's a good chance that the existing
               #output file was linked using a different target, so let's link it again to be safe.
               _built_something = True
               break

         #Even though we didn't build anything, we should verify all our libraries are up to date too.
         #If they're not, we need to relink.
         for i in range(len(_library_mtimes)):
            if _library_mtimes[i] > mtime:
               LOG_LINKER("Library {0} has been modified since the last successful build. Relinking to new library.".format(_libraries[i]))
               _built_something = True

         #Barring the two above cases, there's no point linking if the compiler did nothing.
         if not _built_something:
            if not _called_something:
               LOG_LINKER("Nothing to link.")
            return

   LOG_LINKER("Linking {0}...".format(output))

   objstr = ""

   #Generate the list of objects to link
   for obj in objs:
      objstr += obj + " "

   if not os.path.exists(_output_dir):
      os.makedirs(_output_dir)

   #Remove the output file so we're not just clobbering it
   #If it gets clobbered while running it could cause BAD THINGS (tm)
   if os.path.exists(output):
      os.remove(output)

   subprocess.call("{0} -o{1} {7} {2}{3}-g{4} -O{5} {6} {8}".format(_compiler, output, _get_libraries(), _get_library_dirs(), _debug_level, _opt_level, "-shared " if _shared else "", objstr, _linker_flags), shell=True)


def make():
   """Performs both the build and link steps of the process.
   Aborts if the build fails.
   """
   if not build():
      LOG_ERROR("Build failed. Aborting.")
   else:
      link()
      LOG_BUILD("Build complete.")

def clean():
   """Cleans the project.
   Invoked with --clean.
   Deletes all of the object files to make sure they're rebuilt cleanly next run.
   Does NOT delete the actual compiled file.
   """
   sources = []
   _get_files(sources)
   if not sources:
      return

   if _use_chunks:
      global _chunks
      _chunks = _make_chunks(sources)

   LOG_INFO("Cleaning {0} ({1})...".format(_output_name, target))
   for source in sources:
      obj = "{0}/{1}_{2}.o".format(_obj_dir, os.path.basename(source).split('.')[0], target)
      if os.path.exists(obj):
         LOG_INFO("Deleting {0}".format(obj))
         os.remove(obj)
      if _use_chunks:
         obj = "{0}/{1}_{2}.o".format(_obj_dir, _get_chunk(source), target)
         if os.path.exists(obj):
            LOG_INFO("Deleting {0}".format(obj))
            os.remove(obj)
   LOG_INFO("Done.")

def install():
   """Installer.
   Invoked with --install.
   Installs the generated output file and/or header files to the specified directory.
   Does nothing if neither InstallHeaders() nor InstallOutput() has been called in the make script.
   """
   output = "{0}/{1}".format(_output_dir, _output_name)
   install_something = False

   if os.path.exists(output):
      #install output file
      if _output_install_dir:
         if not os.path.exists(_output_install_dir):
            LOG_ERROR("Install directory {0} does not exist!".format(_output_install_dir))
         else:
            LOG_INSTALL("Installing {0} to {1}...".format(output, _output_install_dir))
            shutil.copy(output, _output_install_dir)
            install_something = True

      #install headers
      if _header_install_dir:
         if not os.path.exists(_header_install_dir):
            LOG_ERROR("Install directory {0} does not exist!".format(_header_install_dir))
         else:
            headers = []
            _get_files(headers=headers)
            for header in headers:
               LOG_INSTALL("Installing {0} to {1}...".format(header, _header_install_dir))
               shutil.copy(header, _header_install_dir)
            install_something = True

      if not install_something:
         LOG_INSTALL("Nothing to install.")
      else:
         LOG_INSTALL("Done.")
   else:
      LOG_ERROR("Output file {0} does not exist! You must build without --install first.".format(output))

#</editor-fold>

#<editor-fold desc="Misc. Public Functions">
def call(s):
   """Calls another makefile script.
   This can be used for multi-tiered projects where each subproject needs its own build script.
   The top-level script will then jmake.call() the other scripts.
   """
   path = os.path.dirname(s)
   file = os.path.basename(s)
   ExcludeDirs(path)
   isMakefile = False
   with open(file) as f:
      for line in f:
         if "import jbuild" in line or "from jbuild import" in line:
            isMakefile = True
   if not isMakefile:
      LOG_ERROR("Called script is not a makefile script!")
   cwd = os.getcwd()
   os.chdir(path)
   LOG_INFO("Entered directory: {0}".format(path))
   args = ["python", file]
   if CleanBuild:
      args.append("--clean")
   if do_install:
      args.append("--install")
   if _quiet:
      qarg = "-"
      for i in range(_quiet):
         qarg += "q"
      args.append(qarg)
   args.append(target)
   subprocess.call(args)
   os.chdir(cwd)
   LOG_INFO("Left directory: {0}".format(path))
   global _called_something
   _called_something = True

#</editor-fold>
#</editor-fold>

#<editor-fold desc="startup">
#<editor-fold desc="Preprocessing">

#This stuff DOES need to run when the module is imported by another file.
#Lack of an if __name__ == __main__ is intentional.
mainfile = sys.modules['__main__'].__file__
if mainfile is not None:
   mainfile = os.path.basename(os.path.abspath(mainfile))
else:
   mainfile = "<makefile>"

parser = argparse.ArgumentParser(description='JMake: Build files in local directories and subdirectories.')
parser.add_argument('target', nargs="?", help='Target for build', default=_default_target)
group = parser.add_mutually_exclusive_group()
group.add_argument('--clean', action="store_true", help='Clean the target build')
group.add_argument('--install', action="store_true", help='Install the target build')
group2 = parser.add_mutually_exclusive_group()
group2.add_argument('-v', action="store_const", const=0, dest="quiet", help="Verbose. Enables additional INFO-level logging.", default=1)
group2.add_argument('-q', action="store_const", const=2, dest="quiet", help="Quiet. Disables all logging except for WARN and ERROR.", default=1)
group2.add_argument('-qq', action="store_const", const=3, dest="quiet", help="Very quiet. Disables all jmake-specific logging.", default=1)
parser.add_argument('--overrides', help="Makefile overrides, semicolon-separated. The contents of the string passed to this will be executed as additional script after the makefile is processed.")
parser.add_argument("-H", "--makefile_help", action="store_true", help="Displays specific help for your makefile (if any)")
args, remainder = parser.parse_known_args()

target = args.target.lower()
CleanBuild = args.clean
do_install = args.install
_overrides = args.overrides
_quiet = args.quiet

makefile_help = args.makefile_help

if makefile_help:
   remainder.append("-h")

args = remainder

if target[0] == "_":
   LOG_ERROR("Invalid target: {0}.".format(target))
   sys.exit(1)

def debug():
   """Default debug target."""
   if not _opt_set:
      Opt(0)
   if not _debug_set:
      Debug(3)
   if not _output_dir_set:
      OutDir("Debug")
   if not _obj_dir_set:
      ObjDir("Debug/obj")
def release():
   """Default release target."""
   if not _opt_set:
      Opt(3)
   if not _debug_set:
      Debug(0)
   if not _output_dir_set:
      OutDir("Release")
   if not _obj_dir_set:
      ObjDir("Release/obj")

ExcludeDirs(_jmake_dir)

#Import the file that imported this file.
#This ensures any options set in that file are executed before we continue.
#It also pulls in its target definitions.
if mainfile != "<makefile>":
   exec("import {0} as __mainfile__".format(mainfile.split(".")[0]))
else:
   LOG_ERROR("JMake cannot be run from the interactive console.")
   sys.exit(1)

#Check if the default debug, release, and none targets have been defined in the makefile script
#If not, set them to the defaults defined above.
try:
   exec "__mainfile__.{0}".format(target)
except AttributeError:
   if target == "debug":
      #__mainfile__ is defined in the above exec statement, but can show as unresolved to some code inspectors.
      #noinspection PyUnresolvedReferences
      __mainfile__.debug = debug
   elif target == "release":
      #noinspection PyUnresolvedReferences
      __mainfile__.release = release

if makefile_help:
   sys.exit(0)

#Try to execute the requested target function
#If it doesn't exist, throw an error
try:
   exec "__mainfile__.{0}()".format(target)
except AttributeError:
   LOG_ERROR("Invalid target: {0}".format(target))
else:
   #Execute any overrides that have been passed
   #These will supercede anything set in the makefile script.
   if _overrides:
      exec _overrides
   #If automake hasn't been disabled by the makefile script, call the proper function
   #clean() on --clean
   #install() on --install
   #and make() in any other case
   if _automake:
      if CleanBuild:
         clean()
      elif do_install:
         install()
      else:
         make()
   #Print out any errors or warnings incurred so the user doesn't have to scroll to see what went wrong
   if _warnings:
      LOG_WARN("Warnings encountered during build:")
      for warn in _warnings[0:-1]:
         LOG_WARN(warn)
   if _errors:
      LOG_ERROR("Errors encountered during build:")
      for error in _errors[0:-1]:
         LOG_ERROR(error)

#And finally, explicitly exit! If we don't do this, the makefile script runs again after this.
#That looks sloppy if it does anything visible, and besides that, it takes up needless cycles
sys.exit(0)
#</editor-fold>
#</editor-fold>
