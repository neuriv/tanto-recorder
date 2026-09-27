"""Listen for a Windows global hotkey. Never synthesize keyboard/game input."""
import ctypes as C
from ctypes import wintypes as W
import threading

HOTKEYS={'Off':None, **{f'F{n}':(0,0x70+n-1) for n in range(6,12)}, 'Ctrl+Shift+R':(6,ord('R'))}


def parse_hotkey(name):
    # Turn a readable keyboard shortcut into Windows modifier and virtual-key numbers.
    # Allow supported function keys or Ctrl/Alt plus a letter/number, reserving guide/save/close shortcuts.
    # Off returns no registration; unsupported combinations fail before a listener thread starts.
    if name=='Off':return None
    parts=name.split('+');modifiers=parts[:-1];key=parts[-1]
    if len(set(modifiers))!=len(modifiers) or any(part not in ('Ctrl','Alt','Shift') for part in modifiers):
        raise ValueError('Use Ctrl, Alt or Shift with one key.')
    mask=sum({'Alt':1,'Ctrl':2,'Shift':4}[part] for part in modifiers)
    if key.startswith('F') and key[1:].isdigit() and 2<=int(key[1:])<=24 and key!='F12':
        vk=0x70+int(key[1:])-1
    elif len(key)==1 and key in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' and mask&3:
        vk=ord(key)
    else:raise ValueError('Use F2–F11 / F13–F24, or Ctrl / Alt plus a letter or number.')
    if (mask,vk) in ((2,ord('S')),(1,0x73)):
        raise ValueError('Ctrl+S saves descriptions; Alt+F4 closes the window. Choose another binding.')
    return mask,vk


def key_event_name(event):
    # Translate the key pressed during Bind a key into the saved shortcut spelling.
    # Tk state bits describe Ctrl, Alt and Shift; they differ from RegisterHotKey's modifier numbers.
    # Ignore modifier-only presses and run the same validation used for saved bindings.
    key=event.keysym.upper()
    if key in ('SHIFT_L','SHIFT_R','CONTROL_L','CONTROL_R','ALT_L','ALT_R'):return None
    parts=[name for name,mask in (('Ctrl',4),('Alt',0x20000|8),('Shift',1)) if event.state&mask]
    name='+'.join([*parts,key]);parse_hotkey(name)
    return name


class GlobalHotkey:
    def __init__(self, name, publish):
        # Start a dedicated Windows listener for the chosen recording shortcut.
        # Give it a stop event and a queue-publishing callback instead of access to Tk widgets.
        # The listener is a daemon, while explicit close still releases its Windows registration promptly.
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.listen,args=(name,publish),daemon=True)
        self.thread.start()

    def listen(self, name, publish):
        # Receive the registered shortcut even when Recorder is not the focused application.
        # Register on the owning thread with MOD_NOREPEAT and poll only WM_HOTKEY messages.
        # Publish a toggle or registration error; always unregister on exit and never synthesize keyboard input.
        key=parse_hotkey(name)
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
        # Stop listening and release the shortcut for other applications.
        # Signal the listener's cooperative loop and wait for its unregister cleanup to finish.
        # Joining before a replacement registration prevents a false conflict with our own old listener.
        self.stop.set()
        self.thread.join()
