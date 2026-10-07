"""
voice_mouse.py - hands-free mouse control for Windows using a tiny offline
speech model (Vosk) restricted to a handful of command words.

Voice commands
--------------
Asleep   : "start listening"             -> wake up (only phrase heard while asleep)
Awake    : "stop listening"              -> go back to sleep
           "mouse grid"                  -> open the 3x3 grid over the whole screen
In grid  : "one" ... "nine"              -> zoom into that cell (cursor moves to its centre)
           "back"                        -> undo the last zoom
           "mark"                        -> remember this spot as a drag start, restart grid
           "left click" / "right click"  -> click at the aimed spot (or drag from the mark)
           "double click"                -> double-click at the aimed spot
           "move mouse"                  -> put the cursor at the aimed spot and leave the grid,
                                            without clicking
           "cancel"                      -> leave the grid (and forget any mark)

Keyboard (awake, or inside the grid)
------------------------------------
  "press tab"                        one key
  "press down down enter"            keys one after another
  "press down twenty"                a key followed by a number repeats it ("twenty times" also ok)
  "press control c"                  modifiers (control, alt, shift, windows) apply to the next key
  "press control shift escape"       ... several modifiers
  "press control c control v"        chords one after another
  "press function five"              F5          "press page down fifty"   Page Down x50
  "press one two three"              digit keys  (numbers straight after "press" are digits)
  letters: say the letter ("a", "bee", "see"...) or NATO words ("alpha", "bravo", ...)
  other keys: enter return tab escape space backspace delete insert home end up down left
              right period comma slash backslash dash equals semicolon
Page keys (no "press" needed; go to the window with keyboard focus)
  "page down" / "page up"              one page
  "page down five [times]"             N pages, e.g. "page up twenty"
Scrolling (awake, or inside the grid; scrolls whatever window is under the cursor)
  "scroll down" / "scroll up"          default 5 notches
  "scroll down twenty [times]"         N notches (also "scroll left" / "scroll right")
  "scroll down ten scroll up two"      chainable
Everything can be chained in one breath: "mouse grid five one left click press hello" style.

Hotkey (no voice needed): tap Ctrl + Left-Windows together, then let go. It toggles between
sleeping and listening (and leaves the grid). A high beep = now listening, low beep = sleeping.
Ctrl+Win combined with any other key (e.g. virtual-desktop switching) is left alone.
Disable with --no-hotkey.
You can also click the status box in the bottom-right corner to toggle listening; its \u21c4
button moves the box round the four screen corners (start somewhere else with --corner top-left).

Run:  python voice_mouse.py            (downloads the ~40 MB model on first run)
      python voice_mouse.py --list-devices
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
SAMPLE_RATE = 16000
MIN_CELL_PX = 4          # stop zooming when a cell would be smaller than this

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}

# Two-word phrases first, then single words.
PHRASES = {
    ("start", "listening"): "start",
    ("stop", "listening"): "stop",
    ("mouse", "grid"): "grid",
    ("move", "mouse"): "move",
    ("move",): "move",          # bare word: Vosk sometimes drops "mouse"
    ("left", "click"): "left",
    ("right", "click"): "right",
    ("double", "click"): "double",
    ("click",): "left",         # plain "click" = left click
    ("left",): "left",          # bare words: Vosk sometimes drops "click"
    ("right",): "right",        # (arrow keys always need "press" first)
    ("double",): "double",
    ("mark",): "mark",
    ("back",): "back",
    ("cancel",): "cancel",
}

MAX_REPEAT = 500          # safety cap for "press down <N>" / "scroll down <N>"
SCROLL_DEFAULT = 5        # notches for a bare "scroll down"

# ---- keyboard vocabulary ---------------------------------------------------
UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

MODIFIERS = {"control": "ctrl", "alt": "alt", "shift": "shift", "windows": "win"}

SPOKEN_KEYS = {
    "enter": "enter", "return": "enter", "tab": "tab", "escape": "escape", "space": "space",
    "backspace": "backspace", "delete": "delete", "insert": "insert", "home": "home",
    "end": "end", "up": "up", "down": "down", "left": "left", "right": "right",
    "period": "period", "comma": "comma", "slash": "slash", "backslash": "backslash",
    "dash": "dash", "minus": "dash", "equals": "equals", "semicolon": "semicolon",
}

LETTER_WORDS = {c: c for c in "abcdefghijklmnopqrstuvwxyz"}
LETTER_WORDS.update({   # spoken-letter homophones the recogniser may prefer
    "bee": "b", "be": "b", "see": "c", "sea": "c", "dee": "d", "gee": "g", "jay": "j",
    "kay": "k", "oh": "o", "pee": "p", "queue": "q", "are": "r", "tea": "t", "you": "u",
    "why": "y", "zee": "z", "zed": "z", "ex": "x", "eye": "i", "el": "l", "em": "m", "en": "n",
})
LETTER_WORDS.update({   # NATO alphabet: longer words, usually more reliable than bare letters
    w: w[0] for w in (
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
        "november oscar papa quebec romeo sierra tango uniform victor whiskey yankee zulu"
    ).split()
})

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
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
})
EXTENDED_KEYS = {"delete", "insert", "home", "end", "pageup", "pagedown",
                 "left", "up", "right", "down", "win"}

_KEY_WORDS = (set(SPOKEN_KEYS) | set(LETTER_WORDS) | set(MODIFIERS) | set(UNITS) | set(TENS)
              | {"press", "times", "function", "page", "hundred", "click", "scroll"})

WAKE_GRAMMAR = ["start listening", "[unk]"]
COMMAND_GRAMMAR = list(dict.fromkeys(
    ["stop listening", "mouse grid", "move mouse", "click", "left click", "right click", "double click",
     "mark", "back", "cancel", "start listening"]
    + list(NUMBER_WORDS) + sorted(_KEY_WORDS) + ["[unk]"]
))


# --------------------------------------------------------------------------
# Pure logic (no Windows / audio dependencies, so it can be unit tested)
# --------------------------------------------------------------------------
def level_from_pcm(data: bytes) -> float:
    """Loudness of a 16-bit mono PCM chunk on a 0..1 scale (-60 dBFS -> 0, -10 dBFS -> 1)."""
    from array import array
    a = array("h")
    a.frombytes(data[: len(data) // 2 * 2])
    if not a:
        return 0.0
    rms = math.sqrt(sum(x * x for x in a) / len(a))
    if rms < 1:
        return 0.0
    db = 20 * math.log10(rms / 32768)
    return max(0.0, min(1.0, (db + 60) / 50))


@dataclass(frozen=True)
class Chord:
    mods: tuple[str, ...]
    key: str
    count: int = 1


@dataclass(frozen=True)
class KeyPress:
    chords: tuple[Chord, ...]


@dataclass(frozen=True)
class Scroll:
    direction: str      # up / down / left / right
    amount: int


def parse_number(words: list[str], i: int):
    """Parse 0-999 spoken ('twenty five', 'one hundred ten'). Returns (value, next_i) or None."""
    n, j, total, got = len(words), i, 0, False
    if j + 1 < n and words[j] in UNITS and UNITS[words[j]] < 10 and words[j + 1] == "hundred":
        total, j, got = UNITS[words[j]] * 100, j + 2, True
    if j < n and words[j] in TENS:
        total += TENS[words[j]]
        j, got = j + 1, True
        if j < n and words[j] in UNITS and 1 <= UNITS[words[j]] <= 9:
            total += UNITS[words[j]]
            j += 1
    elif j < n and words[j] in UNITS:
        total += UNITS[words[j]]
        j, got = j + 1, True
    return (total, j) if got else None


def _parse_key(words: list[str], i: int):
    w = words[i]
    if w == "page" and i + 1 < len(words) and words[i + 1] in ("up", "down"):
        return "page" + words[i + 1], i + 2
    if w == "function":
        num = parse_number(words, i + 1)
        if num and 1 <= num[0] <= 12:
            return f"f{num[0]}", num[1]
        return None
    if w in SPOKEN_KEYS:
        return SPOKEN_KEYS[w], i + 1
    if w in LETTER_WORDS:
        return LETTER_WORDS[w], i + 1
    return None


def _parse_press(words: list[str], i: int):
    """Parse everything after 'press'. Returns (list[Chord], next_i)."""
    n = len(words)
    chords: list[Chord] = []
    mods: list[str] = []
    countable = False           # last chord was a non-digit key a number can repeat
    while i < n:
        w = words[i]
        if w == "[unk]":
            i += 1
        elif w in ("left", "right", "double") and words[i + 1:i + 2] == ["click"]:
            break               # a mouse click, not an arrow key
        elif w in MODIFIERS:
            mods.append(MODIFIERS[w])
            i += 1
        elif w in UNITS or w in TENS:
            num = parse_number(words, i) if (chords and not mods and countable) else None
            if num:             # "down twenty [times]" -> repeat last key
                c = chords[-1]
                chords[-1] = Chord(c.mods, c.key, min(num[0], MAX_REPEAT))
                i = num[1]
                if i < n and words[i] == "times":
                    i += 1
                countable = False
            elif w in UNITS and UNITS[w] < 10:      # digit key
                chords.append(Chord(tuple(mods), str(UNITS[w])))
                mods, countable = [], False
                i += 1
            else:
                break
        else:
            key = _parse_key(words, i)
            if not key:
                break
            name, i = key
            chords.append(Chord(tuple(mods), name))
            mods, countable = [], True
    if mods:                    # e.g. "press windows" / "press shift" on their own
        chords.append(Chord(tuple(mods[:-1]), mods[-1]))
    return chords, i


def parse_commands(text: str) -> list:
    """Turn recognised text into commands: 'start', 'grid', '1'..'9', ... or KeyPress objects."""
    words = text.lower().split()
    out: list = []
    i = 0
    while i < len(words):
        if words[i] == "scroll":
            if i + 1 < len(words) and words[i + 1] in ("up", "down", "left", "right"):
                direction, i = words[i + 1], i + 2
                amount = SCROLL_DEFAULT
                num = parse_number(words, i)
                if num:
                    amount, i = min(num[0], MAX_REPEAT), num[1]
                    if i < len(words) and words[i] == "times":
                        i += 1
                out.append(Scroll(direction, amount))
            else:
                i += 1
            continue
        if words[i] == "page" and words[i + 1:i + 2] in (["up"], ["down"]):
            key, i = "page" + words[i + 1], i + 2           # bare "page down [N] [times]"
            count = 1
            num = parse_number(words, i)
            if num:
                count, i = min(num[0], MAX_REPEAT), num[1]
                if i < len(words) and words[i] == "times":
                    i += 1
            out.append(KeyPress((Chord((), key, count),)))
            continue
        if words[i] == "press":
            chords, i = _parse_press(words, i + 1)
            if chords:
                out.append(KeyPress(tuple(chords)))
            continue
        two = tuple(words[i:i + 2])
        if len(two) == 2 and two in PHRASES:
            out.append(PHRASES[two])
            i += 2
        elif (words[i],) in PHRASES:
            out.append(PHRASES[(words[i],)])
            i += 1
        elif words[i] in NUMBER_WORDS:
            out.append(str(NUMBER_WORDS[words[i]]))
            i += 1
        else:
            i += 1   # [unk] or a stray word
    return out


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float

    def cell(self, n: int) -> "Region":
        """Cell n (1-9), numbered like a phone keypad: 1 2 3 / 4 5 6 / 7 8 9."""
        row, col = divmod(n - 1, 3)
        cw, ch = self.w / 3, self.h / 3
        return Region(self.x + col * cw, self.y + row * ch, cw, ch)

    @property
    def center(self) -> tuple[int, int]:
        return int(self.x + self.w / 2), int(self.y + self.h / 2)


class GridNavigator:
    def __init__(self, bounds: Region):
        self.bounds = bounds
        self.stack = [bounds]

    @property
    def current(self) -> Region:
        return self.stack[-1]

    def reset(self) -> None:
        self.stack = [self.bounds]

    def select(self, n: int) -> bool:
        cur = self.current
        if cur.w / 3 < MIN_CELL_PX or cur.h / 3 < MIN_CELL_PX:
            return False
        self.stack.append(cur.cell(n))
        return True

    def back(self) -> bool:
        if len(self.stack) > 1:
            self.stack.pop()
            return True
        return False


SLEEPING, AWAKE, GRID = "sleeping", "awake", "grid"


class Controller:
    """State machine: SLEEPING <-> AWAKE <-> GRID. Talks to `mouse` and `overlay`."""

    def __init__(self, bounds: Region, mouse, overlay, on_state=lambda s: None, keyboard=None):
        self.nav = GridNavigator(bounds)
        self.mouse, self.overlay, self.on_state = mouse, overlay, on_state
        self.keyboard = keyboard
        self.state = SLEEPING
        self.mark: tuple[int, int] | None = None

    def _set(self, state: str) -> None:
        if state == SLEEPING:
            # However we got here (voice, hotkey, status-box click), drop everything in flight:
            # the grid overlay, any zoom levels and any pending drag mark.
            self.overlay.hide()
            self.mark = None
            self.nav.reset()
        self.state = state
        self.on_state(state)

    def _show(self) -> None:
        self.overlay.show(self.nav.current, self.mark)

    def _leave_grid(self, new_state: str = AWAKE) -> None:
        self.overlay.hide()
        self.mark = None
        self.nav.reset()
        self._set(new_state)

    def handle(self, cmd) -> None:
        if isinstance(cmd, Scroll):
            if self.state != SLEEPING:
                self.mouse.scroll(cmd.direction, cmd.amount)
            return

        if isinstance(cmd, KeyPress):
            if self.state != SLEEPING and self.keyboard:
                for ch in cmd.chords:
                    self.keyboard.press(ch.mods, ch.key, ch.count)
            return

        if self.state == SLEEPING:
            if cmd == "start":
                self._set(AWAKE)
            return

        if self.state == AWAKE:
            if cmd == "stop":
                self._set(SLEEPING)
            elif cmd == "grid":
                self.nav.reset()
                self.mark = None
                self._set(GRID)
                self._show()
            return

        # ---- GRID ----
        if cmd.isdigit():
            if self.nav.select(int(cmd)):
                self.mouse.move(*self.nav.current.center)
                self._show()
        elif cmd == "back":
            if self.nav.back():
                self.mouse.move(*self.nav.current.center)
                self._show()
        elif cmd == "grid":
            self.nav.reset()
            self._show()
        elif cmd == "mark":
            self.mark = self.nav.current.center
            self.nav.reset()
            self._show()
        elif cmd in ("left", "right", "double"):
            target = self.nav.current.center
            self.overlay.hide()          # make sure the overlay never eats the click
            time.sleep(0.08)
            self.mouse.move(*target)
            print(f"{cmd} click at {target}" + (f" (drag from {self.mark})" if self.mark and cmd != "double" else ""))
            if self.mark and cmd != "double":
                self.mouse.drag(cmd, self.mark, target)
            else:
                self.mouse.click("left" if cmd == "double" else cmd, double=(cmd == "double"))
            self._leave_grid(AWAKE)
        elif cmd == "move":
            target = self.nav.current.center
            self.overlay.hide()
            self.mouse.move(*target)
            print(f"moved mouse to {target}")
            self._leave_grid(AWAKE)         # no click; any pending mark is dropped
        elif cmd == "cancel":
            self._leave_grid(AWAKE)
        elif cmd == "stop":
            self._leave_grid(SLEEPING)


# --------------------------------------------------------------------------
# Windows specifics
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


def primary_screen() -> Region:
    import ctypes
    u = ctypes.windll.user32
    return Region(0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))


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


class HotkeyWatcher:
    """Detects a clean Ctrl + Left-Win tap (no other key pressed during it).

    Polled from the UI loop. `is_down(vk)` and `mask()` are injected so the logic is testable.
    `mask()` taps an unassigned key while Win is held so Windows doesn't open the Start menu
    when Win is released.
    """
    CTRL, LWIN = (0x11,), 0x5B
    IGNORE = {0x11, 0xA2, 0xA3, 0x5B, 0xE8}          # ctrl variants, left win, our mask key

    def __init__(self, is_down, mask):
        self.is_down, self.mask = is_down, mask
        self.active = False
        self.dirty = False

    def poll(self) -> bool:
        """True exactly once when a clean Ctrl+LWin chord has just been released."""
        if self.is_down(0x11) and self.is_down(self.LWIN):
            if not self.active:
                self.active, self.dirty = True, False
                self.mask()
            elif not self.dirty:
                self.dirty = any(self.is_down(vk) for vk in range(0x08, 0xFF)
                                 if vk not in self.IGNORE)
            return False
        if self.active:
            fired = not self.dirty
            self.active = False
            return fired
        return False


def make_win_hotkey() -> HotkeyWatcher:
    import ctypes
    u = ctypes.windll.user32

    def is_down(vk: int) -> bool:
        return bool(u.GetAsyncKeyState(vk) & 0x8000)

    def mask() -> None:
        u.keybd_event(0xE8, 0, 0, 0)
        u.keybd_event(0xE8, 0, 0x0002, 0)

    return HotkeyWatcher(is_down, mask)


def make_click_through(widget, clickable: bool = False) -> None:
    """Layered + no-activate window that never takes focus. Unless `clickable`, mouse clicks
    also pass straight through it to whatever is underneath."""
    import ctypes
    u = ctypes.windll.user32
    widget.update_idletasks()
    hwnd = u.GetAncestor(widget.winfo_id(), 2)           # GA_ROOT
    GWL_EXSTYLE = -20
    style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    extra = 0x80000 | 0x80 | 0x08000000                  # LAYERED | TOOLWINDOW | NOACTIVATE
    if not clickable:
        extra |= 0x20                                    # TRANSPARENT (click-through)
    u.SetWindowLongW(hwnd, GWL_EXSTYLE, style | extra)


class Overlay:
    KEY = "#010203"      # colour treated as fully transparent

    def __init__(self, root, screen: Region):
        import tkinter as tk
        self.tk, self.screen = tk, screen
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{int(screen.w)}x{int(screen.h)}+{int(screen.x)}+{int(screen.y)}")
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(self.win, bg=self.KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        make_click_through(self.win)
        self.win.withdraw()

    def hide(self) -> None:
        self.win.withdraw()
        self.win.update()        # process the unmap now; Tk would otherwise defer it until idle

    def show(self, r: Region, mark: tuple[int, int] | None) -> None:
        c, s = self.canvas, self.screen
        c.delete("all")
        # dim everything outside the active region
        dim = dict(fill="black", stipple="gray50", outline="")
        c.create_rectangle(0, 0, s.w, r.y, **dim)
        c.create_rectangle(0, r.y + r.h, s.w, s.h, **dim)
        c.create_rectangle(0, r.y, r.x, r.y + r.h, **dim)
        c.create_rectangle(r.x + r.w, r.y, s.w, r.y + r.h, **dim)
        # grid
        c.create_rectangle(r.x, r.y, r.x + r.w, r.y + r.h, outline="#ff2d2d", width=3)
        for i in (1, 2):
            c.create_line(r.x + r.w * i / 3, r.y, r.x + r.w * i / 3, r.y + r.h, fill="#ff2d2d", width=2)
            c.create_line(r.x, r.y + r.h * i / 3, r.x + r.w, r.y + r.h * i / 3, fill="#ff2d2d", width=2)
        size = int(max(10, min(80, min(r.w, r.h) / 3 * 0.45)))
        for n in range(1, 10):
            cx, cy = r.cell(n).center
            font = ("Segoe UI", -size, "bold")
            c.create_text(cx + 2, cy + 2, text=str(n), font=font, fill="black")
            c.create_text(cx, cy, text=str(n), font=font, fill="#ffe600")
        if mark:
            mx, my = mark
            c.create_oval(mx - 10, my - 10, mx + 10, my + 10, outline="#00e5ff", width=3)
            c.create_line(mx - 16, my, mx + 16, my, fill="#00e5ff", width=2)
            c.create_line(mx, my - 16, mx, my + 16, fill="#00e5ff", width=2)
        self.win.deiconify()
        self.win.attributes("-topmost", True)


class StatusPill:
    COLORS = {SLEEPING: ("#444444", "Sleeping - say \"start listening\""),
              AWAKE: ("#1e8e3e", "Listening - \"mouse grid\" or \"press ...\""),
              GRID: ("#c5221f", "Grid - say 1-9, back, mark, cancel")}
    METER_W, METER_H = 90, 10

    CORNERS = ("bottom-right", "bottom-left", "top-left", "top-right")   # order the button cycles

    def __init__(self, root, screen: Region, corner: str = "bottom-right"):
        import tkinter as tk
        self.corner = corner                  # which screen corner the box sits in
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.85)
        self.frame = tk.Frame(self.win)
        self.frame.pack()
        self.label = tk.Label(self.frame, font=("Segoe UI", 10, "bold"), fg="white", padx=10, pady=4)
        self.label.pack(side="left")
        self.meter = tk.Canvas(self.frame, width=self.METER_W, height=self.METER_H,
                               bg="#1b1b1b", highlightthickness=0)
        self.meter.pack(side="left", padx=(0, 4))
        # Move handle: cycles the box through the four screen corners. Its handler returns "break"
        # so the click does not also reach the toplevel binding that toggles listening.
        self.mover = tk.Label(self.frame, text="\u21c4", font=("Segoe UI Symbol", 12, "bold"),
                              fg="white", padx=8, pady=2)
        self.mover.pack(side="left", padx=(0, 4))
        self.mover.bind("<Button-1>", self._flip_click)
        self.bar = self.meter.create_rectangle(0, 0, 0, self.METER_H, width=0, fill="#34c759")
        self.screen = screen
        self.level = 0.0
        self.on_click = lambda: None          # set by main(); toggles listening
        # Bind ONCE on the toplevel: clicks on the label/meter bubble up to it through Tk's
        # bindtags, so binding every child as well made each click fire twice (wake, then sleep).
        self._last_click = 0.0
        self.win.bind("<Button-1>", self._clicked)
        for w in (self.win, self.frame, self.label, self.meter, self.mover):
            w.config(cursor="hand2")
        self.set(SLEEPING)
        make_click_through(self.win, clickable=True)   # takes clicks but never steals focus

    def _clicked(self, event=None) -> None:
        now = time.monotonic()
        if now - self._last_click < 0.35:       # ignore bounce / duplicate events
            return
        self._last_click = now
        self.on_click()

    def _flip_click(self, event=None) -> str:
        i = self.CORNERS.index(self.corner)
        self.corner = self.CORNERS[(i + 1) % len(self.CORNERS)]
        self._place()
        return "break"                        # don't let this click toggle listening

    def _place(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = 16 if "left" in self.corner else self.screen.w - w - 16
        y = 16 if "top" in self.corner else self.screen.h - h - 56      # 56 clears the taskbar
        self.win.geometry(f"+{int(x)}+{int(y)}")

    def set(self, state: str) -> None:
        colour, text = self.COLORS[state]
        self.label.config(text=text, bg=colour)
        self.mover.config(bg=colour)
        self.frame.config(bg=colour)
        self._place()

    def set_level(self, v: float) -> None:
        """Fast attack, slow decay so short words are visible."""
        self.level = max(v, self.level * 0.8)
        colour = "#34c759" if self.level < 0.6 else "#ffcc00" if self.level < 0.85 else "#ff3b30"
        self.meter.coords(self.bar, 0, 0, self.level * self.METER_W, self.METER_H)
        self.meter.itemconfig(self.bar, fill=colour)


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------
def ensure_model(path: str | None) -> str:
    if path:
        return path
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    target = os.path.join(base, MODEL_NAME)
    if os.path.isdir(target):
        return target
    os.makedirs(base, exist_ok=True)
    zip_path = target + ".zip"
    print(f"Downloading speech model (~40 MB) from {MODEL_URL} ...")
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(base)
    os.remove(zip_path)
    return target


class SpeechThread(threading.Thread):
    """Mic -> Vosk. Uses a wake-only grammar while asleep and the command grammar otherwise."""

    def __init__(self, model_path, device, min_conf, get_state, out_queue, open_vocab=False):
        super().__init__(daemon=True)
        self.model_path, self.device, self.min_conf = model_path, device, min_conf
        self.open_vocab = open_vocab
        self.level = 0.0         # latest mic loudness, 0..1, read by the UI for the meter
        self.get_state, self.out = get_state, out_queue
        self.audio: queue.Queue[bytes] = queue.Queue()

    def _confident(self, result: dict) -> bool:
        words = result.get("result") or []
        if not words:
            return False
        return sum(w.get("conf", 1.0) for w in words) / len(words) >= self.min_conf

    def run(self) -> None:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        model = Model(self.model_path)

        def make(grammar):
            r = (KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar)) if grammar
                 else KaldiRecognizer(model, SAMPLE_RATE))     # no grammar = open vocabulary
            r.SetWords(True)
            return r

        wake = make(WAKE_GRAMMAR)
        command = make(None if self.open_vocab else COMMAND_GRAMMAR)
        last_asleep = True

        def cb(indata, frames, t, status):
            data = bytes(indata)
            self.level = level_from_pcm(data)
            self.audio.put(data)

        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=800, device=self.device,
                               dtype="int16", channels=1, callback=cb):
            print("Microphone open. Say \"start listening\".")
            while True:
                data = self.audio.get()
                asleep = self.get_state() == SLEEPING
                if asleep != last_asleep:                 # state flipped: drop stale audio
                    (wake if asleep else command).Reset()
                    last_asleep = asleep
                rec = wake if asleep else command
                if rec.AcceptWaveform(data):
                    res = json.loads(rec.Result())
                    text = res.get("text", "")
                    if text and self._confident(res):
                        print(f"heard: {text}")
                        for cmd in parse_commands(text):
                            self.out.put(cmd)


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Voice-controlled mouse grid for Windows")
    ap.add_argument("--model", help="path to an unpacked Vosk model (default: auto-download)")
    ap.add_argument("--device", type=int, help="input device index (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--min-conf", type=float, default=0.6,
                    help="ignore results below this average word confidence (default 0.6)")
    ap.add_argument("--start-awake", action="store_true")
    ap.add_argument("--corner", choices=StatusPill.CORNERS, default="bottom-right",
                    help="screen corner the status box starts in (the \u21c4 button cycles through all four)")
    ap.add_argument("--no-hotkey", action="store_true",
                    help="disable the Ctrl + Left-Windows listen/sleep toggle")
    ap.add_argument("--open-vocab", action="store_true",
                    help="don't restrict awake-mode recognition to the command words; use this if "
                         "multi-word chains are being cut short (more false triggers, though)")
    args = ap.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    if sys.platform != "win32":
        sys.exit("This tool controls the Windows mouse; run it on Windows.")

    try:
        import sounddevice, vosk  # noqa: F401
    except ImportError as e:
        sys.exit(f"Missing package ({e.name}). Install the requirements with:\n"
                 f"    {os.path.basename(sys.executable)} -m pip install vosk sounddevice")

    import tkinter as tk
    make_dpi_aware()
    model_path = ensure_model(args.model)

    root = tk.Tk()
    root.withdraw()
    screen = primary_screen()
    pill = StatusPill(root, screen, corner=args.corner)
    overlay = Overlay(root, screen)
    ctl = Controller(screen, WinMouse(), overlay, on_state=pill.set, keyboard=WinKeyboard())
    if args.start_awake:
        ctl.handle("start")

    cmds: queue.Queue[str] = queue.Queue()
    speech = SpeechThread(model_path, args.device, args.min_conf, lambda: ctl.state, cmds,
                          args.open_vocab)
    speech.start()

    def meter_poll():
        pill.set_level(speech.level)
        root.after(40, meter_poll)

    root.after(40, meter_poll)

    def poll():
        try:
            while True:
                cmd = cmds.get_nowait()
                try:
                    ctl.handle(cmd)
                except Exception as e:      # never let one bad command kill the poll loop
                    print(f"error handling {cmd!r}: {e}")
        except queue.Empty:
            pass
        root.after(30, poll)

    root.after(30, poll)

    import winsound

    def toggle(source: str) -> None:
        ctl.handle("start" if ctl.state == SLEEPING else "stop")
        awake = ctl.state != SLEEPING
        print(f"{source}: " + ("listening" if awake else "sleeping"))
        threading.Thread(target=winsound.Beep, args=(1000 if awake else 500, 90),
                         daemon=True).start()

    pill.on_click = lambda: toggle("click")

    if not args.no_hotkey:
        watcher = make_win_hotkey()

        def hotkey_poll():
            try:
                if watcher.poll():
                    toggle("hotkey")
            except Exception as e:
                print(f"hotkey error: {e}")
            root.after(20, hotkey_poll)

        root.after(20, hotkey_poll)
        print("Hotkey: tap Ctrl + Left Windows to toggle listening.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
