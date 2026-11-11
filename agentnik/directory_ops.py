"""Atomic, no-replace directory rename on supported local platforms."""
import ctypes
import os
import sys


def rename_directory_no_replace(source,destination):
    if os.name=='nt':
        # Windows os.rename fails rather than replacing an existing destination.
        os.rename(source,destination);return
    library=ctypes.CDLL(None,use_errno=True)
    if sys.platform.startswith('linux'):
        try:operation=library.renameat2
        except AttributeError:raise OSError('Atomic no-replace directory rename is unavailable') from None
        operation.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        operation.restype=ctypes.c_int
        result=operation(-100,os.fsencode(source),-100,os.fsencode(destination),1) # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform=='darwin':
        try:operation=library.renamex_np
        except AttributeError:raise OSError('Atomic no-replace directory rename is unavailable') from None
        operation.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];operation.restype=ctypes.c_int
        result=operation(os.fsencode(source),os.fsencode(destination),4) # RENAME_EXCL
    else:raise OSError('Atomic no-replace directory rename is unavailable on this platform')
    if result:
        number=ctypes.get_errno()
        raise OSError(number,os.strerror(number))
