"""
voice_mouse_hands.py - the small part of Voice Mouse that can run as administrator.

It does one thing: it performs mouse and keyboard actions that the main program asks for. It does
no speech recognition, loads no models and imports nothing but the Python standard library, so
running it elevated means running about 500 lines you can read, not Vosk / sherpa-onnx / numpy and
the models downloaded from the internet. The main program stays a normal user program.

How they talk: this file listens on 127.0.0.1 (this computer only) on a random port. It writes the
port and a random token to a small file in your profile (see --token-file). The main program reads
that file, connects, and sends one JSON object per line, for example
    {"op": "click", "button": "left", "double": false}
Only plain data comes across (never pickle or code). Every message is checked against fixed lists
(keys, modifiers, actions) and size limits before anything is done.

Run it:      py voice_mouse_hands.py --admin          (asks for administrator rights, then serves)
Then start:  py voice_mouse.py --use-hands            (or let voice_mouse.py start it: --admin-hands)

It also draws the mouse grid and the status box (voice_mouse_ui.py, Tk, standard library). A window
is only as "on top" as the program that owns it: normal always-on-top windows can be covered by each
other, and Windows keeps a higher layer, the UI-access band (Magnifier, the on-screen keyboard, a
pinned Task Manager), that no ordinary program can cover. A program joins that band if its manifest
asks for uiAccess, it is signed with a certificate the PC trusts, and it is installed under Program
Files. Because this file is small and has no model code, it is the one to give that privilege: build
it with build.bat, then run install_hands_signed.bat (makes and trusts a test certificate, signs and
installs it, and starts it at logon). Use --no-ui to leave the drawing to the main program instead.

What this does NOT protect against: anything running as you can read the token file, so it can ask
the hands to press keys as administrator. The split keeps big, downloaded model code out of the
elevated process; it does not make an untrusted program on your account safe.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import queue
import secrets
import socket
import socketserver
import sys
import threading
import time

# --------------------------------------------------------------------------
# Keys (shared with the main program, which imports these)
# --------------------------------------------------------------------------
MEDIA_VK = {"play_pause": 0xB3, "stop": 0xB2, "next": 0xB0, "previous": 0xB1}   # VK_MEDIA_*
MEDIA_APPCOMMAND = {"fast_forward": 49, "rewind": 50}                            # APPCOMMAND_MEDIA_*

# canonical key name -> Windows virtual-key code
VK: dict[str, int] = {c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})
VK.update({
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "period": 0xBE, "comma": 0xBC, "slash": 0xBF, "backslash": 0xDC, "dash": 0xBD,
    "equals": 0xBB, "semicolon": 0xBA,
    "lbracket": 0xDB, "rbracket": 0xDD, "quote": 0xDE, "backtick": 0xC0,
    "capslock": 0x14, "printscreen": 0x2C,
    "volumeup": 0xAF, "volumedown": 0xAE, "mute": 0xAD, "contextmenu": 0x5D,   # 0x5D = VK_APPS
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
})
EXTENDED_KEYS = {"delete", "insert", "home", "end", "pageup", "pagedown",
                 "left", "up", "right", "down", "win", "printscreen",
                 "volumeup", "volumedown", "mute", "contextmenu"}
MODIFIER_KEYS = ("ctrl", "alt", "shift", "win")

KEYUP, UNICODE = 0x0002, 0x0004
VK_BACK, VK_RETURN = 0x08, 0x0D


def key_events(backspaces: int, text: str) -> list[tuple[int, int, int]]:
    """(virtual key, scan code, flags) triples: that many Backspaces, then the text. Newline is the
    Enter key; everything else is sent as UTF-16 code units with KEYEVENTF_UNICODE."""
    ev: list[tuple[int, int, int]] = []
    for _ in range(backspaces):
        ev += [(VK_BACK, 0, 0), (VK_BACK, 0, KEYUP)]
    for ch in text.replace("\r", ""):
        if ch == "\n":
            ev += [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYUP)]
            continue
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            ev += [(0, unit, UNICODE), (0, unit, UNICODE | KEYUP)]
    return ev


# --------------------------------------------------------------------------
# Windows input (ctypes). Everything that touches Windows lives in these classes.
# --------------------------------------------------------------------------
def make_dpi_aware() -> None:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor v1
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def is_admin() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def has_ui_access() -> bool:
    """Does this process's token have UI access (the privilege that puts its windows in Windows' top
    layer and lets it drive elevated windows)? False off Windows or if it cannot be read."""
    try:
        import ctypes
        from ctypes import wintypes
        k, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)]
        token = wintypes.HANDLE()
        if not adv.OpenProcessToken(k.GetCurrentProcess(), 0x0008, ctypes.byref(token)):      # TOKEN_QUERY
            return False
        value, size = wintypes.DWORD(0), wintypes.DWORD(0)
        ok = adv.GetTokenInformation(token, 26, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(size))  # TokenUIAccess
        k.CloseHandle(token)
        return bool(ok and value.value)
    except Exception:
        return False


class WinMouse:
    LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP = 0x0002, 0x0004, 0x0008, 0x0010

    def __init__(self):
        import ctypes
        self.u = ctypes.windll.user32

    def move(self, x: int, y: int) -> None:
        self.u.SetCursorPos(int(x), int(y))

    def _flags(self, button: str) -> tuple[int, int]:
        return (self.LEFTDOWN, self.LEFTUP) if button == "left" else (self.RIGHTDOWN, self.RIGHTUP)

    def click(self, button: str, double: bool = False) -> None:
        down, up = self._flags(button)
        for _ in range(2 if double else 1):
            self.u.mouse_event(down, 0, 0, 0, 0)
            self.u.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.05)

    def scroll(self, direction: str, amount: int) -> None:
        """One wheel notch (120 units) per step, at the current cursor position."""
        flag = 0x0800 if direction in ("up", "down") else 0x1000        # WHEEL / HWHEEL
        delta = 120 if direction in ("up", "right") else -120
        for _ in range(amount):
            self.u.mouse_event(flag, 0, 0, delta, 0)
            time.sleep(0.01)
        print(f"scroll {direction} x{amount}")

    def drag(self, button: str, start: tuple[int, int], end: tuple[int, int]) -> None:
        down, up = self._flags(button)
        self.move(*start)
        time.sleep(0.08)
        self.u.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.08)
        steps = 20
        for i in range(1, steps + 1):          # intermediate moves: many apps need them
            self.move(start[0] + (end[0] - start[0]) * i / steps,
                      start[1] + (end[1] - start[1]) * i / steps)
            time.sleep(0.01)
        time.sleep(0.08)
        self.u.mouse_event(up, 0, 0, 0, 0)


class WinKeyboard:
    def __init__(self):
        import ctypes
        self.u = ctypes.windll.user32

    def _event(self, key: str, up: bool) -> None:
        vk = VK[key]
        flags = (0x0001 if key in EXTENDED_KEYS else 0) | (0x0002 if up else 0)
        self.u.keybd_event(vk, self.u.MapVirtualKeyW(vk, 0), flags, 0)

    def press(self, mods, key: str, count: int = 1) -> None:
        """Hold the modifiers, tap the key, release in reverse. Small gaps let the shell and
        apps register the modifier first (Windows-key shortcuts need this)."""
        for _ in range(count):
            for m in mods:
                self._event(m, False)
            if mods:
                time.sleep(0.04)
            self._event(key, False)
            time.sleep(0.02 if mods else 0.005)
            self._event(key, True)
            if mods:
                time.sleep(0.03)
            for m in reversed(mods):
                self._event(m, True)
            time.sleep(0.02 if count > 1 else 0.01)   # let the target app keep up on repeats
        if mods:
            print(f"pressed {'+'.join(mods)}+{key}" + (f" x{count}" if count > 1 else ""))

    def hold(self, mods) -> None:
        """Press and keep down the modifier keys (used around a mouse click)."""
        for m in mods:
            self._event(m, False)
        if mods:
            time.sleep(0.04)

    def release(self, mods) -> None:
        for m in reversed(mods):
            self._event(m, True)
        if mods:
            time.sleep(0.02)


class WinWindow:
    """Minimise / maximise / restore the window you are working in (the foreground window)."""
    SW = {"minimize": 6, "maximize": 3, "restore": 9}          # SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE
    SHELL = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}   # desktop + taskbar

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.u = ctypes.windll.user32
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def act(self, action: str) -> None:
        hwnd = self.u.GetForegroundWindow()
        if not hwnd:
            return
        buf = self.ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(hwnd, buf, 256)
        if buf.value in self.SHELL:                  # never minimise the desktop or the taskbar
            print(f"{action} window: nothing to do (desktop or taskbar is focused)")
            return
        self.u.ShowWindow(hwnd, self.SW[action])
        print(f"{action} window")


class WinMedia:
    """Media buttons. Play/pause, stop, next and previous are the real Windows media keys (they
    reach whatever player owns media control). Fast forward and rewind have no key, so they are
    posted to the focused window as WM_APPCOMMAND, which only some players handle."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.u = ctypes.windll.user32
        self.u.GetForegroundWindow.restype = wintypes.HWND
        self.u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    def send(self, action: str) -> None:
        if action in MEDIA_VK:
            vk = MEDIA_VK[action]
            scan = self.u.MapVirtualKeyW(vk, 0)
            self.u.keybd_event(vk, scan, 0x0001, 0)                 # extended key down
            self.u.keybd_event(vk, scan, 0x0001 | 0x0002, 0)        # ... and up
        else:
            hwnd = self.u.GetForegroundWindow()
            self.u.PostMessageW(hwnd, 0x0319, hwnd or 0, MEDIA_APPCOMMAND[action] << 16)   # WM_APPCOMMAND
        print(f"media {action}")


_INPUT_TYPES = None


def _input_types():
    global _INPUT_TYPES
    if _INPUT_TYPES is None:
        import ctypes
        from ctypes import wintypes

        class MOUSEINPUT(ctypes.Structure):          # not used, but it sizes the INPUT union correctly
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        _INPUT_TYPES = (INPUT, KEYBDINPUT)
    return _INPUT_TYPES


class WinTyper:
    """Backspaces and text into the focused window, in as few SendInput calls as possible."""
    CHUNK = 400                                       # events per call (even, so down/up stay together)

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.INPUT, _ = _input_types()
        self.u = ctypes.windll.user32
        self.u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(self.INPUT), ctypes.c_int]
        self.u.SendInput.restype = wintypes.UINT
        self._warned = False

    def edit(self, backspaces: int, text: str) -> None:
        import ctypes
        events = key_events(backspaces, text)
        for i in range(0, len(events), self.CHUNK):
            chunk = events[i:i + self.CHUNK]
            arr = (self.INPUT * len(chunk))()
            for slot, (vk, scan, flags) in zip(arr, chunk):
                slot.type = 1                         # INPUT_KEYBOARD
                slot.u.ki.wVk, slot.u.ki.wScan, slot.u.ki.dwFlags = vk, scan, flags
            sent = self.u.SendInput(len(chunk), arr, ctypes.sizeof(self.INPUT))
            if sent < len(chunk) and not self._warned:
                self._warned = True
                print("warning: Windows refused some typed input (the window is probably running as "
                      "administrator; run the hands elevated: voice_mouse_hands.py --admin)")


# --------------------------------------------------------------------------
# The protocol: validate one JSON message, then do it
# --------------------------------------------------------------------------
MAX_COUNT = 500             # repeats of a key / notches of a scroll
MAX_TEXT = 5000             # characters in one typing request
MAX_BACKSPACES = 5000
MAX_LINE = 64 * 1024        # bytes in one message
COORD_LIMIT = 100_000       # |x|, |y| (multi-monitor layouts can be negative)
try:                                                        # the drawing half is optional for tests / --no-ui
    from voice_mouse_ui import CORNERS, STATES, Region
except ImportError:                                         # pragma: no cover
    CORNERS = STATES = ()
    Region = None
BUTTONS = ("left", "right")
DIRECTIONS = ("up", "down", "left", "right")
WINDOW_ACTIONS = tuple(WinWindow.SW)
MEDIA_ACTIONS = tuple(MEDIA_VK) + tuple(MEDIA_APPCOMMAND)


class BadRequest(ValueError):
    """The message is not one the hands are willing to carry out."""


def _int(msg: dict, name: str, lo: int, hi: int) -> int:
    v = msg.get(name)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadRequest(f"{name} must be an integer from {lo} to {hi}")
    return v


def _bool(msg: dict, name: str) -> bool:
    v = msg.get(name)
    if not isinstance(v, bool):
        raise BadRequest(f"{name} must be true or false")
    return v


def _choice(msg: dict, name: str, options) -> str:
    v = msg.get(name)
    if not isinstance(v, str) or v not in options:
        raise BadRequest(f"{name} must be one of {', '.join(options)}" if len(options) <= 12
                         else f"{name} is not a supported one")
    return v


def _point(msg: dict, name: str) -> tuple[int, int]:
    v = msg.get(name)
    if (not isinstance(v, list) or len(v) != 2
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or abs(n) > COORD_LIMIT for n in v)):
        raise BadRequest(f"{name} must be [x, y]")
    return int(v[0]), int(v[1])


def _mods(msg: dict) -> list[str]:
    v = msg.get("mods", [])
    if not isinstance(v, list) or len(v) > len(MODIFIER_KEYS) or any(m not in MODIFIER_KEYS for m in v):
        raise BadRequest(f"mods must be a list of {', '.join(MODIFIER_KEYS)}")
    return list(v)


UI_OPS = ("ui_init", "overlay_show", "overlay_hide", "pill")      # handled on the Tk thread, not under the input lock
MAX_HEARD = 300


class UiHost:
    """Owns the grid overlay and status box. Tk may only be used from the thread that created it, so
    requests from the socket threads are queued and run by pump(), which that thread calls often.
    Overlay show / hide wait until done (the caller relies on the order); status box updates are
    merged, so a busy UI thread only ever has the latest one to apply."""

    def __init__(self, root=None, screen=None, make_overlay=None, make_pill=None):
        self.root, self.screen = root, screen
        self.make_overlay = make_overlay or self._real_overlay
        self.make_pill = make_pill or self._real_pill
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.pending: dict = {}
        self.events: list[str] = []
        self.overlay = self.pill = None
        self.keep_on_top = True

    # -- real factories (need Tk; tests pass fakes instead)
    def _real_overlay(self, o):
        from voice_mouse_ui import Overlay
        return Overlay(self.root, self.screen, minor_grid=o["minor_grid"], inset=o["inset"], adapt=o["adapt"])

    def _real_pill(self, o):
        from voice_mouse_ui import StatusPill
        return StatusPill(self.root, self.screen, corner=o["corner"])

    # -- called from any thread
    def submit(self, fn, timeout: float = 5.0):
        done, box = threading.Event(), []
        self.q.put((fn, done, box))
        if not done.wait(timeout):
            raise TimeoutError("the UI thread is not responding")
        if isinstance(box[0], Exception):
            raise box[0]
        return box[0]

    def update_pill(self, fields: dict) -> list[str]:
        with self.lock:
            self.pending.update(fields)
            events, self.events = self.events, []
        return events

    # -- run on the Tk thread
    def pump(self) -> None:
        while True:
            try:
                fn, done, box = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                box.append(fn())
            except Exception as e:                       # reported to the caller, never kills the pump
                box.append(e)
                print(f"ui error: {type(e).__name__}: {e}")
            finally:
                done.set()
        with self.lock:
            fields, self.pending = self.pending, {}
        if fields and self.pill is not None:
            try:
                self._apply_pill(fields)
            except Exception as e:
                print(f"ui error: {type(e).__name__}: {e}")

    def _apply_pill(self, f: dict) -> None:
        if "state" in f and f["state"] != getattr(self.pill, "state", None):
            self.pill.set(f["state"])
        if "level" in f:
            self.pill.set_level(f["level"])
        if "heard" in f:
            self.pill.set_heard(f["heard"], f.get("seq", 0))

    def init(self, o: dict) -> None:
        for w in (self.overlay, self.pill):
            if w is not None and hasattr(w, "win"):
                w.win.destroy()
        self.keep_on_top = o["keep_on_top"]
        self.overlay, self.pill = self.make_overlay(o), self.make_pill(o)
        self.pill.on_click = lambda: self._event("click")
        self.options = o

    def _event(self, name: str) -> None:
        with self.lock:
            self.events.append(name)

    DEFAULTS = {"corner": "bottom-right", "minor_grid": True, "inset": 1, "adapt": True, "keep_on_top": True}

    def ensure(self) -> None:
        if self.overlay is None:
            self.init(dict(self.DEFAULTS))

    def raise_all(self) -> None:
        """Called a few times a second: back above anything that was raised since (overlay first,
        status box above it)."""
        if self.keep_on_top and self.overlay is not None:
            self.overlay.raise_()
            self.pill.raise_()


class Hands:
    """Carries out validated requests on the injected backends (Win* classes, or fakes in tests).
    One input request at a time: the lock keeps typing, key presses and mouse moves from interleaving."""

    def __init__(self, mouse, keyboard, window, media, typer, ui: UiHost | None = None):
        self.mouse, self.keyboard, self.window, self.media, self.typer = mouse, keyboard, window, media, typer
        self.ui = ui
        self.lock = threading.Lock()

    def handle(self, msg) -> dict:
        try:
            if not isinstance(msg, dict) or not isinstance(msg.get("op"), str):
                raise BadRequest("a request is an object with an 'op'")
            op = msg["op"]
            run = getattr(self, "op_" + op, None) if op.isidentifier() else None
            if run is None:
                raise BadRequest(f"unknown op {op!r}")
            if op in UI_OPS:
                if self.ui is None:
                    raise BadRequest("this helper has no screen drawing (started with --no-ui or no Tk)")
                extra = run(msg)
            else:
                with self.lock:
                    extra = run(msg)
            return {"ok": True, **(extra or {})}
        except BadRequest as e:
            print(f"refused: {e}")
            return {"ok": False, "error": str(e)}
        except Exception as e:                       # a failed Windows call must not stop the server
            print(f"error: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # one method per operation; each validates its own arguments first
    def op_ping(self, msg):
        pass

    def op_move(self, msg):
        x, y = _point({"p": [msg.get("x"), msg.get("y")]}, "p")
        self.mouse.move(x, y)

    def op_click(self, msg):
        button = _choice(msg, "button", BUTTONS)
        double = msg.get("double", False)
        if not isinstance(double, bool):
            raise BadRequest("double must be true or false")
        self.mouse.click(button, double)

    def op_drag(self, msg):
        button = _choice(msg, "button", BUTTONS)
        self.mouse.drag(button, _point(msg, "start"), _point(msg, "end"))

    def op_scroll(self, msg):
        direction = _choice(msg, "direction", DIRECTIONS)
        self.mouse.scroll(direction, _int(msg, "amount", 1, MAX_COUNT))

    def op_press(self, msg):
        mods, key = _mods(msg), _choice(msg, "key", VK)
        self.keyboard.press(mods, key, _int(msg, "count", 1, MAX_COUNT) if "count" in msg else 1)

    def op_hold(self, msg):
        self.keyboard.hold(_mods(msg))

    def op_release(self, msg):
        self.keyboard.release(_mods(msg))

    def op_edit(self, msg):
        text = msg.get("text", "")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise BadRequest(f"text must be a string of at most {MAX_TEXT} characters")
        back = _int(msg, "backspaces", 0, MAX_BACKSPACES) if "backspaces" in msg else 0
        self.typer.edit(back, text)

    def op_window(self, msg):
        self.window.act(_choice(msg, "action", WINDOW_ACTIONS))

    def op_media(self, msg):
        self.media.send(_choice(msg, "action", MEDIA_ACTIONS))

    # ---- screen drawing (needs a UiHost)
    def op_ui_init(self, msg):
        corner = _choice(msg, "corner", CORNERS)
        opts = {"corner": corner, "minor_grid": _bool(msg, "minor_grid"), "adapt": _bool(msg, "adapt"),
                "keep_on_top": _bool(msg, "keep_on_top"), "inset": _int(msg, "inset", 0, 50)}
        self.ui.submit(lambda: self.ui.init(opts))

    def op_overlay_show(self, msg):
        region = msg.get("region")
        if (not isinstance(region, list) or len(region) != 4 or any(
                isinstance(n, bool) or not isinstance(n, (int, float)) or abs(n) > COORD_LIMIT for n in region)):
            raise BadRequest("region must be [x, y, width, height]")
        mark = _point(msg, "mark") if msg.get("mark") is not None else None
        self.ui.submit(lambda: (self.ui.ensure(), self.ui.overlay.show(Region(*region), mark))[-1])

    def op_overlay_hide(self, msg):
        self.ui.submit(lambda: self.ui.overlay is not None and self.ui.overlay.hide())

    def op_pill(self, msg):
        fields = {}
        if "state" in msg:
            fields["state"] = _choice(msg, "state", STATES)
        if "level" in msg:
            v = msg["level"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise BadRequest("level must be a number from 0 to 1")
            fields["level"] = float(v)
        if "heard" in msg:
            if not isinstance(msg["heard"], str) or len(msg["heard"]) > MAX_HEARD:
                raise BadRequest(f"heard must be a string of at most {MAX_HEARD} characters")
            fields["heard"], fields["seq"] = msg["heard"], _int(msg, "seq", 0, 2 ** 31) if "seq" in msg else 0
        self.ui.submit(self.ui.ensure)            # first use before ui_init: defaults (also waits for it)
        return {"events": self.ui.update_pill(fields)}


# --------------------------------------------------------------------------
# The server: loopback socket, token, one JSON object per line
# --------------------------------------------------------------------------
def default_token_file() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "voice_mouse", "hands.json")


def write_token_file(path: str, port: int, token: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"port": port, "token": token, "pid": os.getpid()}, f)
    os.replace(tmp, path)


def read_token_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        info = json.load(f)
    if not (isinstance(info.get("port"), int) and isinstance(info.get("token"), str)):
        raise ValueError("not a hands file")
    return info


def serve_connection(rfile, wfile, hands: Hands, token: str, log=print) -> None:
    """Read requests from one connected client until it goes away. The first must be the hello
    with the right token; anything else ends the connection."""
    def reply(obj: dict) -> None:
        wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
        wfile.flush()

    authed = False
    while True:
        line = rfile.readline(MAX_LINE + 1)
        if not line:
            return
        if len(line) > MAX_LINE:
            reply({"ok": False, "error": "message too long"})
            return
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            reply({"ok": False, "error": "not JSON"})
            return
        if not authed:
            given = msg.get("token") if isinstance(msg, dict) else None
            if (isinstance(msg, dict) and msg.get("op") == "hello" and isinstance(given, str)
                    and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))):
                authed = True
                reply({"ok": True, "admin": is_admin(), "ui": getattr(hands, "ui", None) is not None,
                       "uiaccess": has_ui_access()})
                log("hands: client connected")
                continue
            log("hands: refused a connection (bad or missing token)")
            reply({"ok": False, "error": "bad token"})
            return
        reply(hands.handle(msg))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


def make_server(hands: Hands, token: str, port: int = 0, log=print) -> _Server:
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.server.clients += 1
            try:
                serve_connection(self.rfile, self.wfile, hands, token, log)
            except OSError:
                pass
            finally:
                self.server.clients -= 1
                self.server.last_client = time.monotonic()
    srv = _Server(("127.0.0.1", port), Handler)         # loopback only: not reachable from the network
    srv.clients, srv.last_client = 0, time.monotonic()
    return srv


def watch_idle(srv: _Server, idle_s: float, interval: float = 1.0, clock=time.monotonic,
               sleep=time.sleep, stop=lambda: srv.shutdown()) -> threading.Thread:
    """Stop the server once no client has been connected for `idle_s` seconds (0 = never)."""
    def run() -> None:
        while idle_s > 0:
            sleep(interval)
            if srv.clients == 0 and clock() - srv.last_client > idle_s:
                print(f"hands: no client for {idle_s:g}s; exiting")
                stop()
                return
    t = threading.Thread(target=run, daemon=True, name="hands-idle")
    t.start()
    return t


def relaunch_elevated() -> bool:
    """Start this file again with the UAC prompt. True if Windows started it."""
    import ctypes
    import subprocess
    exe, *args = hands_self_command()
    args = [a for a in args if a != "--admin"]
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), None, 1) > 32


def hands_self_command() -> list[str]:
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    if frozen:
        return [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
    return [sys.executable, os.path.abspath(__file__), *sys.argv[1:]]


def open_log(path: str, max_bytes: int = 2_000_000) -> None:
    """Send print() output (and tracebacks) to a time-stamped log file as well as the console, if any.
    A log over `max_bytes` is moved aside to <path>.old first, so it cannot grow without limit."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".old")
    except OSError:
        pass
    fh = open(path, "a", encoding="utf-8", buffering=1)

    class Tee:
        def __init__(self, stream):
            self.stream, self.at_line_start = stream, True

        def write(self, text):
            text = str(text)
            for part in text.splitlines(True):
                fh.write((time.strftime("%Y-%m-%d %H:%M:%S ") if self.at_line_start else "") + part)
                self.at_line_start = part.endswith("\n")
            if self.stream:
                self.stream.write(text)
            return len(text)

        def flush(self):
            fh.flush()
            if self.stream:
                self.stream.flush()

        def isatty(self):
            return False
    sys.stdout, sys.stderr = Tee(sys.__stdout__), Tee(sys.__stderr__)
    print(f"hands: log {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Voice Mouse hands: the small, elevated-capable input helper")
    ap.add_argument("--token-file", default=default_token_file(),
                    help="where to write the port and token the main program reads (default: %(default)s)")
    ap.add_argument("--port", type=int, default=0, help="loopback port (default 0 = pick a free one)")
    ap.add_argument("--admin", action="store_true", help="restart elevated (shows the UAC prompt)")
    ap.add_argument("--idle-exit", type=float, default=0, metavar="SECONDS",
                    help="exit when no main program has been connected for this long (default 0 = never: "
                         "it runs like a server until closed)")
    ap.add_argument("--log", metavar="FILE", help="write everything printed here to FILE (default: hands.log "
                    "next to the token file), so a hidden or scheduled run can still be diagnosed")
    ap.add_argument("--no-log", action="store_true", help="do not write a log file")
    ap.add_argument("--no-ui", action="store_true",
                    help="do not draw the grid and status box here (the main program then draws them itself)")
    args = ap.parse_args(argv)

    if args.admin and not is_admin():
        print("Restarting as administrator (accept the Windows prompt) ...")
        if relaunch_elevated():
            return 0
        print("Could not get administrator rights (prompt declined?); carrying on without them.")
    if not args.no_log:
        open_log(args.log or os.path.join(os.path.dirname(os.path.abspath(args.token_file)), "hands.log"))
    make_dpi_aware()
    root = ui = None
    if not args.no_ui:
        try:
            import tkinter
            from voice_mouse_ui import primary_screen
            root = tkinter.Tk()
            root.withdraw()
            ui = UiHost(root, primary_screen())
        except Exception as e:
            print(f"hands: no screen drawing ({type(e).__name__}: {e}); the main program will draw instead")
            root = ui = None
    hands = Hands(WinMouse(), WinKeyboard(), WinWindow(), WinMedia(), WinTyper(), ui=ui)
    token = secrets.token_hex(32)
    srv = make_server(hands, token, args.port)
    port = srv.server_address[1]
    write_token_file(args.token_file, port, token)
    print(f"hands ready on 127.0.0.1:{port} ({'administrator' if is_admin() else 'NOT administrator'}; "
          f"UI access: {'yes' if has_ui_access() else 'no'}; "
          f"{'drawing the grid and status box' if ui else 'input only'}); token file: {args.token_file}")
    watch_idle(srv, args.idle_exit)
    server = threading.Thread(target=srv.serve_forever, daemon=True, name="hands-server")
    server.start()
    try:
        if root is not None:                         # Tk lives on this thread: serve the UI queue and keep on top
            def pump() -> None:
                ui.pump()
                if server.is_alive():
                    root.after(8, pump)
                else:
                    root.quit()

            def keep() -> None:
                try:
                    ui.raise_all()
                except Exception as e:
                    print(f"ui error: {type(e).__name__}: {e}")
                root.after(250, keep)
            root.after(8, pump)
            root.after(250, keep)
            root.mainloop()
        else:
            server.join()
    except KeyboardInterrupt:
        pass
    finally:
        if server.is_alive():
            srv.shutdown()
        try:
            os.remove(args.token_file)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
