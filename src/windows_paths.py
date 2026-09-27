"""Resolve the user's Downloads location, including Windows folder redirection."""
import ctypes as C
from pathlib import Path
from uuid import UUID


def choose_recording_folders(owner, initial):
    """Explorer's native multi-folder picker (IFileOpenDialog), without extra packages."""
    ole=C.WinDLL('ole32');shell=C.WinDLL('shell32')
    def guid(value):return C.create_string_buffer(UUID(value).bytes_le)
    def method(obj,index,*types):
        table=C.cast(obj,C.POINTER(C.POINTER(C.c_void_p))).contents
        return C.WINFUNCTYPE(C.c_long,C.c_void_p,*types)(table[index])
    def checked(result):
        if result<0:raise OSError(f'Folder picker failed (HRESULT {result & 0xffffffff:08X})')
    ole.CoInitializeEx.argtypes=[C.c_void_p,C.c_uint32];ole.CoInitializeEx.restype=C.c_long
    ole.CoCreateInstance.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32,C.c_void_p,C.POINTER(C.c_void_p)]
    ole.CoCreateInstance.restype=C.c_long
    ole.CoTaskMemFree.argtypes=[C.c_void_p];ole.CoTaskMemFree.restype=None
    shell.SHCreateItemFromParsingName.argtypes=[C.c_wchar_p,C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)]
    shell.SHCreateItemFromParsingName.restype=C.c_long
    checked(ole.CoInitializeEx(None,2))
    dialog=C.c_void_p();items=C.c_void_p();folder=C.c_void_p()
    try:
        checked(ole.CoCreateInstance(guid('dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7'),None,1,
            guid('d57c7288-d4ad-4768-be02-9d969532d960'),C.byref(dialog)))
        checked(method(dialog,9,C.c_uint32)(dialog,0x20|0x200|0x40|0x800|0x8))
        checked(method(dialog,17,C.c_wchar_p)(dialog,'Select saved session folders · Ctrl / Shift selects several'))
        checked(method(dialog,18,C.c_wchar_p)(dialog,'Export selected sessions'))
        if Path(initial).is_dir():
            checked(shell.SHCreateItemFromParsingName(str(initial),None,guid('43826d1e-e718-42ee-bc55-a1e261c37bfe'),C.byref(folder)))
            checked(method(dialog,12,C.c_void_p)(dialog,folder))
        result=method(dialog,3,C.c_void_p)(dialog,owner)
        if result & 0xffffffff==0x800704c7:return []
        checked(result)
        checked(method(dialog,27,C.POINTER(C.c_void_p))(dialog,C.byref(items)))
        count=C.c_uint32();checked(method(items,7,C.POINTER(C.c_uint32))(items,C.byref(count)))
        paths=[]
        for index in range(count.value):
            item=C.c_void_p();name=C.c_void_p()
            try:
                checked(method(items,8,C.c_uint32,C.POINTER(C.c_void_p))(items,index,C.byref(item)))
                checked(method(item,5,C.c_uint32,C.POINTER(C.c_void_p))(item,0x80058000,C.byref(name)))
                paths.append(Path(C.wstring_at(name)))
            finally:
                if name:ole.CoTaskMemFree(name)
                if item:method(item,2)(item)
        return paths
    finally:
        for obj in (folder,items,dialog):
            if obj:method(obj,2)(obj)
        ole.CoUninitialize()


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
