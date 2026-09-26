"""Listen for a Windows global hotkey. Never synthesize keyboard/game input."""
import ctypes as C
from ctypes import wintypes as W
import threading

HOTKEYS={'Off':None, **{f'F{n}':(0,0x70+n-1) for n in range(6,12)}, 'Ctrl+Shift+R':(6,ord('R'))}


class GlobalHotkey:
    def __init__(self, name, publish):
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.listen,args=(name,publish),daemon=True)
        self.thread.start()

    def listen(self, name, publish):
        key=HOTKEYS[name]
        if key is None: return
        api=C.WinDLL('user32',use_last_error=True)
        api.RegisterHotKey.argtypes=[W.HWND,C.c_int,W.UINT,W.UINT]
        api.RegisterHotKey.restype=W.BOOL
        api.UnregisterHotKey.argtypes=[W.HWND,C.c_int]
        api.UnregisterHotKey.restype=W.BOOL
        api.PeekMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
        api.PeekMessageW.restype=W.BOOL
        # A dedicated thread owns registration and its message queue; Tk owns widgets.
        if not api.RegisterHotKey(None,1,key[0]|0x4000,key[1]):
            publish('hotkey_error',f'{name} unavailable (Windows {C.get_last_error()}). Choose another key or use Start / Stop.')
            return
        try:
            publish('hotkey_ready',f'{name} starts / stops recording, including while Nioh is focused.')
            message=W.MSG()
            while not self.stop.wait(.025):
                while api.PeekMessageW(C.byref(message),None,0x0312,0x0312,1):
                    if message.wParam==1: publish('toggle',None)
        finally:
            api.UnregisterHotKey(None,1)

    def close(self):
        self.stop.set()
        self.thread.join()
