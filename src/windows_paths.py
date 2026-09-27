"""Resolve the user's Downloads location, including Windows folder redirection."""
import ctypes as C
from pathlib import Path
from uuid import UUID


def downloads_dir():
    shell=C.WinDLL('shell32');ole=C.WinDLL('ole32')
    shell.SHGetKnownFolderPath.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.POINTER(C.c_void_p)]
    shell.SHGetKnownFolderPath.restype=C.c_long
    ole.CoTaskMemFree.argtypes=[C.c_void_p];ole.CoTaskMemFree.restype=None
    folder=C.create_string_buffer(UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le)
    result=C.c_void_p()
    status=shell.SHGetKnownFolderPath(folder,0,None,C.byref(result))
    try:
        if status<0: raise OSError(f'Windows could not locate Downloads (HRESULT {status & 0xffffffff:08X})')
        return Path(C.wstring_at(result))
    finally:
        if result.value: ole.CoTaskMemFree(result)
