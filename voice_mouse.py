"""
voice_mouse.py - hands-free mouse control for Windows using a tiny offline
speech model (Vosk) restricted to a handful of command words.

Voice commands
--------------
Asleep   : "start listening"             -> wake up (only phrase heard while asleep)
Awake    : "stop listening"              -> go back to sleep
           "mouse grid"                  -> open the 3x3 grid over the whole screen
           "left click" / "right click"  -> click at the current cursor position (no grid needed)
           "double click"                -> double-click at the current cursor position
In grid  : "one" ... "nine"              -> zoom into that cell (cursor moves to its centre)
           "back"                        -> undo the last zoom
           "mark"                        -> remember this spot as a drag start, restart grid
           "left click" / "right click"  -> click at the aimed spot (or drag from the mark)
           "double click"                -> double-click at the aimed spot
           "move mouse"                  -> put the cursor at the aimed spot and leave the grid,
                                            without clicking
           "cancel"                      -> leave the grid (and forget any mark)

Dictation (awake only)
----------------------
  "dictate"                          type what you say into the focused window (voice_dictate.py's
                                     engines: a fast draft while you talk, corrected at each pause).
                                     The status box turns blue and says Dictating.
  stops by itself after 3 s of silence (--dictate-idle), or say "stop dictation" / "stop listening"
  as a phrase of its own: both go back to listening. The hotkey / box click goes to sleep instead.
  "new line", "new paragraph", "scratch that" work inside dictation (see voice_dictate.py).
  The first "dictate" loads the models in the background (the first run downloads about 750 MB);
  dictation then starts by itself. --preload-dictation loads them at start-up; --no-dictation turns
  the command off. Needs: pip install sherpa-onnx webrtcvad-wheels numpy (see requirements.txt).

Keyboard (awake only; ignored while the mouse grid is open)
------------------------------------
  "press tab"                        one key
  "press down down enter"            keys one after another
  "press down four times"            a key followed by "<number> times" repeats it (down x4)
  "press down four"                  no "times": press down, then type the digit 4 ("twenty" types 2, 0)
  "press control c"                  modifiers (control, alt, shift, windows) apply to the next key
  "press control shift escape"       ... several modifiers
  "press control c control v"        chords one after another
  "press function five"              F5          "press page down fifty times"   Page Down x50
  "press one two three"              digit keys  (numbers without "times" are always typed digits)
  letters: say the letter ("a", "bee", "see"...) or NATO words ("alpha", "bravo", ...)
  other keys: enter return tab escape space backspace delete insert home end up down left
              right period comma slash backslash dash equals semicolon
  volume keys: "press volume up" / "press volume down" / "press mute"; add "<number> times" to repeat
              ("press volume up ten" = ten steps). These are ordinary key presses, so --no-media
              does not turn them off.
  multi-word keys: "back space" (or "backspace"), "space bar", "caps lock", "print screen",
              "left arrow" / "right arrow" / "up arrow" / "down arrow"
  punctuation: "question mark", "exclamation mark", "colon", "quote", "single quote", "apostrophe",
              "open/close bracket", "open/close brace", "open/close paren", "underscore", "hyphen",
              "plus", "asterisk", "at sign", "hash", "dollar sign", "percent", "caret", "ampersand",
              "tilde", "back tick", "pipe", "less than", "greater than"  (US/Australian layout)
Page keys (no "press" needed; go to the window with keyboard focus; ignored in the grid)
  "page down" / "page up"              one page
  "page down five [times]"             N pages, e.g. "page up twenty"
Scrolling (awake, or inside the grid; scrolls whatever window is under the cursor)
  "scroll down" / "scroll up"          default 5 notches
  "scroll down twenty [times]"         N notches (also "scroll left" / "scroll right")
  "scroll down ten scroll up two"      chainable
Everything can be chained in one breath: "mouse grid five one left click press hello" style.

Modified clicks (awake or in the grid): say the modifier(s) first
  "control left click"                 ctrl-click        "shift left click"   shift-click
  "control shift left click"           chords of control / shift / alt, in any order
  "alt right click"  "control double click"  "shift click" (= shift + left click)
  The modifiers are held only for that click and released straight after. In the grid the click
  happens at the aimed spot as usual ("... one five control left click"), and "mark" + a modified
  click drags with the modifiers held. Windows is not offered as a click modifier.

Windows (awake only; acts on the window you are using, never the desktop or taskbar)
  "minimize window"                    minimise it to the taskbar
  "maximize window"                    maximise it
  "restore window"                     bring a maximised window back to its normal size
  (US spellings: that is what the speech model knows.)
  "start menu"                         taps the Windows key (opens the Start menu); same as "press windows"
  "press context menu"                 the keyboard's menu key: opens the right-click menu for whatever
                                       has keyboard focus (use "right click" to open it at the pointer)

Media buttons (awake only; say "media" first so "stop", "next", "back" etc. keep their other meanings)
  "media play" / "media pause"         play/pause toggle (Windows has a single play/pause key)
  "media stop"                         stop
  "media next" / "media previous"      next / previous track     ("media skip forward" / "media skip back" are the same)
  "media fast forward" / "media rewind"  sent to the focused window as a media command; only some
                                         players act on it
  Turn all of this off with --no-media.

Developer
  "super secret dev menu reload"       restart the program (same options, comes back listening);
                                       awake only, and the whole phrase has to be heard

Hotkey (no voice needed): tap Ctrl + Left-Windows together, then let go. It toggles between
sleeping and listening (and leaves the grid). A high beep = now listening, low beep = sleeping.
Ctrl+Win combined with any other key (e.g. virtual-desktop switching) is left alone.
Disable with --no-hotkey.
You can also click the status box in the bottom-right corner to toggle listening; its \u21c4
button moves the box round the four screen corners (start somewhere else with --corner top-left).

How recognition is kept tidy (the "page delta" problem): (1) the recogniser's vocabulary comes from
the BNF-style grammar in this file, with a separate grammar per state (asleep / awake / grid);
(2) every result is then checked strictly against the same rules and ignored unless it is a
complete, well-ordered command for the current state ("page" only before up/down, a count only
after a key, grid words only in the grid ...); (3) with --nbest the best-ranked alternative that
passes the check wins. --lenient restores the old skip-stray-words behaviour.

Do Not Disturb: the grid overlay stops 1 pixel short of the screen's bottom edge (--overlay-inset N),
because a window that covers the monitor exactly makes Windows think a full-screen app is running and
turn on Do Not Disturb (which also shifts the taskbar's notification icons).

If Windows still switches Do Not Disturb on, the program notices (it asks Windows what it thinks is
running) and shrinks the overlay one more pixel at a time, up to 8, printing a line when it does.
It then remembers the size for the session. --no-adapt-inset turns that off.

Always on top: the status box and the grid are raised to the top of the always-on-top order a few
times a second, so they stay above the taskbar, the Start menu and other topmost windows (turn off
with --no-keep-on-top). Windows' own highest layer (on-screen keyboard, Magnifier, the lock screen)
cannot be covered by an ordinary program.

Priority: the program runs at high process priority so recognition and clicks stay responsive while
other things hog the CPU (--priority normal / above / high; real-time is deliberately not offered).

Elevated windows: Windows (UIPI) stops a normal program from clicking or typing into windows that
run as administrator, such as Task Manager or an installer. Start with --admin (or right-click ->
Run as administrator) to reach them. It has no effect on windows that were not elevated.

No console window: run it with  pythonw voice_mouse.py  (or double-click a .pyw copy) and there is
never a console. --hide-console hides the console after start-up instead; it does not work inside
Windows Terminal (the Windows 11 default), where only the tab can be closed. A compiled build can use
--windows-console-mode=disable in build_exe.bat / build_onefile.bat. With no console, messages go
nowhere; heard.jsonl (--log) still records what was recognised.

Run:  python voice_mouse.py            (downloads the ~40 MB model on first run)
      python voice_mouse.py --list-devices
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import queue
import sys
import threading
import time
import traceback
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

# Modifiers that may precede a click ("control shift left click"). Not "windows": tapping the Windows
# key on its own can open the Start menu.
CLICK_MODIFIERS = {"control", "alt", "shift"}

SLEEPING, AWAKE, GRID, DICTATE = "sleeping", "awake", "grid", "dictating"

# ---- the command table ------------------------------------------------------
# One row per command token: what is said, and in which states it may be said. PHRASES (spoken words
# -> token), ALLOWED (token -> legal states) and the window-command grammar/examples are all derived
# from it. Tokens with no phrases here (press, scroll, media, digits) are built by their own parsers.
# "window" commands are phrases only, never the bare verb, so a stray word cannot minimise whatever
# you are working in. `phrases` that are not in PHRASES (reload) are matched by their own code.
@dataclass(frozen=True)
class CommandSpec:
    token: str
    states: frozenset
    phrases: tuple = ()
    in_phrases: bool = True            # False: matched by dedicated parser code, not the PHRASES lookup
    window: bool = False               # a "<verb> window" command
    awake_only: bool = False           # its phrases are in the awake/any grammar but never the grid's


_AW, _GR, _SL, _DI = (frozenset({AWAKE}), frozenset({GRID}), frozenset({SLEEPING}), frozenset({DICTATE}))
_AG = _AW | _GR
COMMAND_TABLE: tuple[CommandSpec, ...] = (
    CommandSpec("start", _SL, (("start", "listening"),)),
    CommandSpec("stop", _AG | _DI, (("stop", "listening"),)),
    CommandSpec("grid", _AG, (("mouse", "grid"),)),
    CommandSpec("move", _GR, (("move", "mouse"), ("move",))),       # bare word: Vosk sometimes drops "mouse"
    CommandSpec("left", _AG, (("left", "click"), ("click",), ("left",))),   # plain "click" = left click
    CommandSpec("right", _AG, (("right", "click"), ("right",))),    # bare words: Vosk sometimes drops
    CommandSpec("double", _AG, (("double", "click"), ("double",))),  # "click" (arrow keys need "press")
    CommandSpec("mark", _GR, (("mark",),)),
    CommandSpec("back", _GR, (("back",),)),
    CommandSpec("cancel", _GR, (("cancel",),)),
    CommandSpec("minimize", _AW, (("minimize", "window"),), window=True, awake_only=True),
    CommandSpec("maximize", _AW, (("maximize", "window"),), window=True, awake_only=True),
    CommandSpec("restore", _AW, (("restore", "window"),), window=True, awake_only=True),
    CommandSpec("reload", _AW, (("super", "secret", "dev", "menu", "reload"),), in_phrases=False),
    CommandSpec("dictate", _AW, (("dictate",),), awake_only=True),   # awake -> typing what you say
    CommandSpec("listen", _DI),                # end dictation, back to listening (not spoken: timeout / "stop dictation")
    CommandSpec("press", _AW),                 # no key presses in the grid
    CommandSpec("scroll", _AG),
    CommandSpec("media", _AW),                 # never in the grid
    *[CommandSpec(str(n), _GR) for n in range(1, 10)],
)
WINDOW_COMMANDS = {p: c.token for c in COMMAND_TABLE if c.window for p in c.phrases}
RELOAD_PHRASE = next(c.phrases[0] for c in COMMAND_TABLE if c.token == "reload")   # -> "reload"
# Two-word phrases first, then single words (the parser relies on that order).
PHRASES = {p: c.token for n in (5, 3, 2, 1) for c in COMMAND_TABLE if c.in_phrases
           for p in c.phrases if len(p) == n}

# Media buttons: spoken words after "media" -> action. Windows has real keys for play/pause (one
# toggle), stop, next and previous; fast forward / rewind exist only as WM_APPCOMMAND messages.
MEDIA_ACTIONS: dict[tuple[str, ...], str] = {
    ("play",): "play_pause", ("pause",): "play_pause", ("stop",): "stop",
    ("next",): "next", ("previous",): "previous",
    ("skip", "forward"): "next", ("skip", "back"): "previous",
    ("fast", "forward"): "fast_forward", ("rewind",): "rewind",
}
MEDIA_VK = {"play_pause": 0xB3, "stop": 0xB2, "next": 0xB0, "previous": 0xB1}   # VK_MEDIA_*
MEDIA_APPCOMMAND = {"fast_forward": 49, "rewind": 50}                            # APPCOMMAND_MEDIA_*
MEDIA_EXAMPLES = ["media play", "media pause", "media stop", "media next", "media previous",
                  "media fast forward", "media rewind", "media skip back", "media skip forward"]

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
    "lbracket": 0xDB, "rbracket": 0xDD, "quote": 0xDE, "backtick": 0xC0,
    "capslock": 0x14, "printscreen": 0x2C,
    "volumeup": 0xAF, "volumedown": 0xAE, "mute": 0xAD, "contextmenu": 0x5D,   # 0x5D = VK_APPS
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
})
EXTENDED_KEYS = {"delete", "insert", "home", "end", "pageup", "pagedown",
                 "left", "up", "right", "down", "win", "printscreen",
                 "volumeup", "volumedown", "mute", "contextmenu"}

# Multi-word and punctuation key names: spoken phrase -> (extra modifiers, key). Symbols that need
# Shift are Shift + the key that carries them on a US layout (the Australian layout is the same).
# Vosk often hears "backspace" as "back space", so both work.
SYMBOL_KEYS: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {
    ("back", "space"): ((), "backspace"), ("space", "bar"): ((), "space"),
    ("caps", "lock"): ((), "capslock"), ("print", "screen"): ((), "printscreen"),
    ("volume", "up"): ((), "volumeup"), ("volume", "down"): ((), "volumedown"), ("mute",): ((), "mute"),
    ("context", "menu"): ((), "contextmenu"),
    ("left", "arrow"): ((), "left"), ("right", "arrow"): ((), "right"),
    ("up", "arrow"): ((), "up"), ("down", "arrow"): ((), "down"),
    ("question", "mark"): (("shift",), "slash"),
    ("exclamation", "mark"): (("shift",), "1"), ("exclamation", "point"): (("shift",), "1"),
    ("colon",): (("shift",), "semicolon"),
    ("quote",): (("shift",), "quote"), ("double", "quote"): (("shift",), "quote"),
    ("single", "quote"): ((), "quote"), ("apostrophe",): ((), "quote"),
    ("open", "bracket"): ((), "lbracket"), ("close", "bracket"): ((), "rbracket"),
    ("open", "brace"): (("shift",), "lbracket"), ("close", "brace"): (("shift",), "rbracket"),
    ("open", "paren"): (("shift",), "9"), ("close", "paren"): (("shift",), "0"),
    ("open", "parenthesis"): (("shift",), "9"), ("close", "parenthesis"): (("shift",), "0"),
    ("underscore",): (("shift",), "dash"), ("hyphen",): ((), "dash"), ("plus",): (("shift",), "equals"),
    ("asterisk",): (("shift",), "8"), ("at", "sign"): (("shift",), "2"),
    ("hash",): (("shift",), "3"), ("pound",): (("shift",), "3"),
    ("dollar", "sign"): (("shift",), "4"), ("percent",): (("shift",), "5"),
    ("caret",): (("shift",), "6"), ("ampersand",): (("shift",), "7"),
    ("tilde",): (("shift",), "backtick"), ("back", "tick"): ((), "backtick"),
    ("pipe",): (("shift",), "backslash"),
    ("less", "than"): (("shift",), "comma"), ("greater", "than"): (("shift",), "period"),
}

_KEY_WORDS = (set(SPOKEN_KEYS) | set(LETTER_WORDS) | set(MODIFIERS) | set(UNITS) | set(TENS)
              | {"press", "times", "function", "page", "hundred", "click", "scroll", "media"}
              | set(RELOAD_PHRASE) | {"menu"} | {w for phrase in WINDOW_COMMANDS for w in phrase}
              | {w for phrase in MEDIA_ACTIONS for w in phrase}
              | {w for phrase in SYMBOL_KEYS for w in phrase})

WAKE_GRAMMAR = ["start listening", "[unk]"]
# Flat word list: only used by tests / as a reference; recognition uses the generated sentences below.
COMMAND_GRAMMAR = list(dict.fromkeys(
    ["stop listening", "mouse grid", "move mouse", "click", "left click", "right click", "double click",
     "mark", "back", "cancel", "start listening"]
    + list(NUMBER_WORDS) + sorted(_KEY_WORDS) + ["[unk]"]
))

# ---- the command grammar ------------------------------------------------------------------
# Vosk does not take a real grammar. As I read recognizer.cc (not testable here), the list you give it becomes a *bigram*
# language model (ngram_order = 2, discount = 0.5): it only learns "which word may follow which
# word", counted from the phrases supplied. Handing it loose single words therefore teaches it
# nothing about order, which is how "page" ended up followed by "delta".
#
# So we write the grammar once, BNF-style, below, work out every legal word->word transition
# (the "bigrams") and emit enough example sentences to cover every legal pair, several times
# each. Pairs that are not legal ("page" -> "delta") never appear, so they only get the small
# back-off probability. Constraints are therefore strong but soft, and only one word deep.
#
#   utterance := command+
#   command   := "start listening" | "stop listening" | "mouse grid" | "move mouse"   (per state: see build_command_grammar)
#              | "left click" | "right click" | "double click" | "click" | mark | back | cancel
#              | one..nine | left | right | double | move                  (bare forms, see parser)
#              | "page" (up|down) [count]
#              | "scroll" (up|down|left|right) [count]
#              | "press" (modifier* key | modifier+) [count] ...   (repeated)
#   count     := number ["times"]
#   key       := letter | NATO word | named key | "page" (up|down) | "function" number | digit
GRAMMAR_REPEAT = 2          # each covering sentence is repeated this often (stronger constraint)
GRAMMAR_MAX_LEN = 16        # words per generated sentence


class _G:
    """Glushkov summary of a regular expression over words: enough to list every bigram."""
    __slots__ = ("nullable", "first", "last", "pairs")

    def __init__(self, nullable, first, last, pairs):
        self.nullable, self.first, self.last, self.pairs = nullable, first, last, pairs


def _W(w):
    return _G(False, {w}, {w}, set())


def _seq(*xs):
    r = xs[0]
    for b in xs[1:]:
        a = r
        r = _G(a.nullable and b.nullable,
               a.first | (b.first if a.nullable else set()),
               b.last | (a.last if b.nullable else set()),
               a.pairs | b.pairs | {(x, y) for x in a.last for y in b.first})
    return r


def _alt(*xs):
    return _G(any(x.nullable for x in xs), set().union(*(x.first for x in xs)),
              set().union(*(x.last for x in xs)), set().union(*(x.pairs for x in xs)))


def _opt(x):
    return _G(True, x.first, x.last, x.pairs)


def _plus(x):
    return _G(x.nullable, x.first, x.last, x.pairs | {(l, f) for l in x.last for f in x.first})


def _words(ws):
    return _alt(*[_W(w) for w in ws])


def _phrase(text):
    return _seq(*[_W(w) for w in text.split()])


def build_command_grammar(mode: str = "any", media: bool = True) -> _G:
    """The grammar as word-order rules, one per state.

    mode "any"  : every command anywhere (state-blind).
    mode "grid" : what can be said while the mouse grid is open.
    mode "awake": what can be said when awake and NOT in the grid. Clicks, page, scroll, press and
                  "mouse grid" start an utterance; the grid-only words (1-9, back, mark, cancel,
                  move mouse) are legal only after "mouse grid" in the same breath.
    media=False leaves out the "media <button>" commands (--no-media). They are legal when awake
    (and in "any"), never in the grid.
    It mirrors ALLOWED / next_state() below, and a test keeps the two in step.
    """
    units19 = [w for w, v in UNITS.items() if 1 <= v <= 9]
    tens_part = _seq(_words(TENS), _opt(_words(units19)))
    number = _alt(_words(UNITS), tens_part,
                  _seq(_words(units19), _W("hundred"), _opt(_alt(_words(UNITS), tens_part))))
    count = _seq(number, _opt(_W("times")))
    mods = _words(MODIFIERS)
    key = _alt(_words(set(LETTER_WORDS) | set(SPOKEN_KEYS)), number,        # a number types its digits
               _seq(_W("page"), _words(["up", "down"])),
               _seq(_W("function"), _words(units19 + ["ten", "eleven", "twelve"])),
               *[_phrase(" ".join(k)) for k in SYMBOL_KEYS])
    key_item = _alt(_seq(_opt(_plus(mods)), key), _plus(mods))
    press = _seq(_W("press"), _plus(_seq(key_item, _opt(_seq(number, _W("times"))))))   # "down 4 times"
    page = _seq(_W("page"), _words(["up", "down"]), _opt(count))
    scroll = _seq(_W("scroll"), _words(["up", "down", "left", "right"]), _opt(count))
    plain_clicks = _alt(*[_phrase(p) for p in ("left click", "right click", "double click")],
                        _words(["click", "left", "right", "double"]))
    clicks = _alt(plain_clicks, _seq(_plus(_words(sorted(CLICK_MODIFIERS))), plain_clicks))
    grid_only = _alt(_phrase("move mouse"), _words(["move", "mark", "back", "cancel"] + list(NUMBER_WORDS)))
    stop, mouse_grid = _phrase("stop listening"), _phrase("mouse grid")
    common = [page, scroll, press, clicks, mouse_grid, stop]
    # Commands legal when awake (and in "any") but never in the grid: media buttons, the dev reload
    # phrase, "start menu" (= press windows), "dictate" and the "<verb> window" commands.
    awake_only = [_seq(_W("media"), _alt(*[_phrase(" ".join(k)) for k in MEDIA_ACTIONS]))] if media else []
    awake_only.append(_phrase(" ".join(RELOAD_PHRASE)))
    awake_only.append(_phrase("start menu"))
    awake_only += [_phrase(" ".join(p)) for c in COMMAND_TABLE if c.awake_only for p in c.phrases]
    if mode == "any":
        return _plus(_alt(_phrase("start listening"), *common, *awake_only, grid_only))
    if mode == "grid":
        return _plus(_alt(*common, grid_only))
    if mode == "awake":
        in_grid = _alt(*common, grid_only)              # after "mouse grid" anything may follow
        return _plus(_alt(page, scroll, press, clicks, stop, *awake_only,
                          _seq(mouse_grid, _opt(_plus(in_grid)))))
    raise ValueError(mode)


_CLICKS = ["left click", "right click", "double click", "click",
           "control left click", "shift left click", "alt right click", "control shift left click"]
_COMMON_EXAMPLES = ["mouse grid", "page down", "page up", "scroll down", "scroll up",
                    "page down five", "scroll down ten times", "press tab", "press enter",
                    "press control c", "press down twenty times", "press back space", "press question mark",
                    "press left arrow", "stop listening"] + _CLICKS
BASE_EXAMPLES = _COMMON_EXAMPLES + ["move mouse", "mark", "back", "cancel", "start listening"] + list(NUMBER_WORDS)
GRID_BASE_EXAMPLES = [e for e in BASE_EXAMPLES if e != "start listening"]
AWAKE_BASE_EXAMPLES = (list(_COMMON_EXAMPLES) + MEDIA_EXAMPLES + [" ".join(RELOAD_PHRASE)]
                       + [" ".join(k) for k in WINDOW_COMMANDS] + ["press context menu", "start menu", "dictate"])


def grammar_sentences(g: _G, repeat: int = GRAMMAR_REPEAT, max_len: int = GRAMMAR_MAX_LEN,
                      base=None) -> list[str]:
    """Example sentences covering every legal word pair of `g` (plus start/end), repeated."""
    from collections import deque
    START, END = "<s>", "</s>"
    adj: dict[str, list[str]] = {}
    for a, b in g.pairs:
        adj.setdefault(a, []).append(b)
    for f in g.first:
        adj.setdefault(START, []).append(f)
    for l in g.last:
        adj.setdefault(l, []).append(END)
    for k in adj:
        adj[k].sort()
    unc = {a: set(bs) for a, bs in adj.items()}

    parent = {START: None}                               # shortest path START -> node
    q = deque([START])
    while q:
        n = q.popleft()
        for m in adj.get(n, ()):
            if m != END and m not in parent:
                parent[m] = n
                q.append(m)
    radj: dict[str, list[str]] = {}
    for a, bs in adj.items():
        for b in bs:
            radj.setdefault(b, []).append(a)
    to_end = {END: None}                                 # next hop on the shortest path -> END
    q = deque([END])
    while q:
        n = q.popleft()
        for m in radj.get(n, ()):
            if m not in to_end:
                to_end[m] = n
                q.append(m)

    def cover(a, b):
        unc[a].discard(b)

    nodes = sorted(adj)
    out: list[str] = []
    while True:
        n0 = next((n for n in nodes if unc[n]), None)
        if n0 is None:
            break
        path, n = [], n0                                  # START ... n0
        while parent[n] is not None:
            path.append(n)
            n = parent[n]
        path.append(START)
        path.reverse()                                    # [START, ..., n0]
        for a, b in zip(path, path[1:]):
            cover(a, b)
        sent, cur = path[1:], n0
        while len(sent) < max_len:
            nxt = next((m for m in sorted(unc[cur]) if m != END), None)
            if nxt is None:                               # hop to the most useful legal successor
                best = max((m for m in adj[cur] if m != END), key=lambda m: len(unc[m]), default=None)
                if best is None or not unc[best]:
                    break
                nxt = best
            cover(cur, nxt)
            sent.append(nxt)
            cur = nxt
        while cur != END:                                 # finish along the shortest legal ending
            nxt = to_end[cur]
            cover(cur, nxt)
            if nxt != END:
                sent.append(nxt)
            cur = nxt
        out.append(" ".join(sent))
    base = BASE_EXAMPLES if base is None else base
    return out * repeat + base * (repeat * 3) + ["[unk]"] * (repeat * 3)


COMMAND_GRAMMAR_G = build_command_grammar()
COMMAND_SENTENCES = grammar_sentences(COMMAND_GRAMMAR_G)
# every word the command grammar uses (handy for tests)
COMMAND_VOCAB = {w for sent in COMMAND_SENTENCES for w in sent.split()}

# One recogniser per state, so e.g. "five" or "click" cannot even be heard while the grid is closed
# (unless said right after "mouse grid"), and nothing but the wake phrase is heard while asleep.
AWAKE_GRAMMAR_G = build_command_grammar("awake")
GRID_GRAMMAR_G = build_command_grammar("grid")
AWAKE_SENTENCES = grammar_sentences(AWAKE_GRAMMAR_G, base=AWAKE_BASE_EXAMPLES)
GRID_SENTENCES = grammar_sentences(GRID_GRAMMAR_G, base=GRID_BASE_EXAMPLES)


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
class ModClick:
    kind: str                   # left / right / double
    mods: tuple[str, ...]       # ctrl / alt / shift, held for the click


@dataclass(frozen=True)
class Media:
    action: str         # play_pause / stop / next / previous / fast_forward / rewind


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


def _parse_symbol(words: list[str], i: int):
    """Longest multi-word / punctuation key name at words[i]: (mods, key, next_i) or None."""
    for n in (3, 2, 1):
        hit = SYMBOL_KEYS.get(tuple(words[i:i + n]))
        if len(words[i:i + n]) == n and hit:
            return hit[0], hit[1], i + n
    return None


def _starts_click(words: list[str], j: int) -> bool:
    """Do the words from j begin an explicit click ("left click", "right click", "double click" or
    "click")? Bare "left"/"right" are NOT counted: inside "press" they are arrow keys."""
    return words[j:j + 1] == ["click"] or tuple(words[j:j + 2]) in (
        ("left", "click"), ("right", "click"), ("double", "click"))


def _parse_press(words: list[str], i: int, strict: bool = False):
    """Parse everything after 'press'. Returns (list[Chord], next_i)."""
    n = len(words)
    chords: list[Chord] = []
    mods: list[str] = []
    countable = False           # the last chord is a key that "<number> times" can repeat
    while i < n:
        w = words[i]
        if w == "[unk]":
            if strict:
                break
            i += 1
        elif w in ("left", "right", "double") and words[i + 1:i + 2] == ["click"]:
            break               # a mouse click, not an arrow key
        elif w in MODIFIERS:
            j = i
            while j < n and words[j] in CLICK_MODIFIERS:
                j += 1
            if _starts_click(words, j):
                mods = []           # "press tab control left click": those modifiers belong to the click
                break
            mods.append(MODIFIERS[w])
            i += 1
        elif w in UNITS or w in TENS:
            num = parse_number(words, i)
            value, j = num
            if chords and not mods and countable and words[j:j + 1] == ["times"]:
                c = chords[-1]              # "down four times" -> repeat the last key
                chords[-1] = Chord(c.mods, c.key, min(value, MAX_REPEAT))
                i, countable = j + 1, False
            else:                           # "down four" -> press down, then type 4 ("twenty" = 2, 0)
                for k, digit in enumerate(str(value)):
                    chords.append(Chord(tuple(mods) if k == 0 else (), digit))
                i, mods, countable = j, [], True
        else:
            sym = _parse_symbol(words, i)
            if sym:                 # "question mark", "back space", "left arrow" ...
                smods, name, i = sym
                chords.append(Chord(tuple(dict.fromkeys([*mods, *smods])), name))
                mods, countable = [], True
                continue
            key = _parse_key(words, i)
            if not key:
                break
            name, i = key
            chords.append(Chord(tuple(mods), name))
            mods, countable = [], True
    if mods:                    # e.g. "press windows" / "press shift" on their own
        chords.append(Chord(tuple(mods[:-1]), mods[-1]))
    return chords, i


def parse_commands(text, min_word_conf: float = 0.0, strict: bool = False, media: bool = True):
    """Turn recognised words into commands: 'start', 'grid', '1'..'9', ... or KeyPress objects.

    `text` may be the raw recognised string or Vosk's per-word result list
    (``[{"word": ..., "conf": ...}, ...]``). Any word whose confidence is below
    `min_word_conf` is dropped before parsing, so a single mis-heard word inside an
    otherwise good phrase cannot fire a command. A plain string counts as fully
    confident, which keeps callers (and tests) that pass text unchanged.

    Lenient (default): words that fit nothing, or fall below the floor, are skipped.
    strict=True: the WHOLE utterance must be well formed ("page" only before up/down, a count only
    after a key, no leftover words, no word under the floor) or the result is None. A mis-heard
    word then rejects the utterance instead of being silently dropped, because dropping can change
    the meaning ("scroll down <twenty>" would become the default 5).
    media=False treats "media ..." as stray words (the --no-media option).
    """
    bad = False
    if isinstance(text, str):
        words = text.lower().split()
    else:
        items = list(text or [])
        words = [str(w.get("word", "")).lower()
                 for w in items if float(w.get("conf", 1.0)) >= min_word_conf]
        bad = len(words) != len(items)
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
                bad = True
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
        if words[i] in CLICK_MODIFIERS:                    # "control shift left click"
            j, mods = i, []
            while j < len(words) and words[j] in CLICK_MODIFIERS:
                mods.append(MODIFIERS[words[j]])
                j += 1
            kind, used = None, 0
            two = tuple(words[j:j + 2])
            if two in (("left", "click"), ("right", "click"), ("double", "click")):
                kind, used = two[0], 2
            elif words[j:j + 1] == ["click"]:
                kind, used = "left", 1
            elif words[j:j + 1] in (["left"], ["right"], ["double"]):   # "click" dropped by the recogniser
                kind, used = words[j], 1
            if kind:
                out.append(ModClick(kind, tuple(dict.fromkeys(mods))))
            else:
                bad = True                                  # modifier(s) with nothing to click
            i = j + used
            continue
        if words[i:i + 2] == ["start", "menu"]:             # same as "press windows": taps the Windows key
            out.append(KeyPress((Chord((), "win", 1),)))
            i += 2
            continue
        if tuple(words[i:i + len(RELOAD_PHRASE)]) == RELOAD_PHRASE:      # whole phrase or nothing
            out.append("reload")
            i += len(RELOAD_PHRASE)
            continue
        if words[i] == "media" and media:
            for n in (2, 1):                                # "fast forward" before a one-word name
                action = MEDIA_ACTIONS.get(tuple(words[i + 1:i + 1 + n]))
                if action and len(words[i + 1:i + 1 + n]) == n:
                    out.append(Media(action))
                    i += 1 + n
                    break
            else:
                bad = True
                i += 1
            continue
        if words[i] == "press":
            chords, i = _parse_press(words, i + 1, strict)
            if chords:
                out.append(KeyPress(tuple(chords)))
            else:
                bad = True
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
            bad = True
            i += 1   # [unk] or a stray word
    if strict and (bad or not out):
        return None
    return out


def is_noise(text: str) -> bool:
    """True for an empty result or one made only of [unk] markers (Vosk's 'heard something, no word')."""
    return not text.replace("[unk]", "").strip()


def leading_digits(text: str) -> list[int]:
    """The run of grid-number words at the start of a (partial) transcript: 'five two' -> [5, 2]."""
    out = []
    for w in text.split():
        if w not in NUMBER_WORDS:
            break
        out.append(NUMBER_WORDS[w])
    return out


def stable_prefix(a: list, b: list) -> list:
    """Common prefix of two lists (what two successive partial results agree on)."""
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return out


def drop_applied_digits(cmds: list, n: int) -> list:
    """Remove the first `n` leading digit commands (already sent early, from partial results)."""
    out = list(cmds)
    while n and out and isinstance(out[0], str) and out[0].isdigit():
        out.pop(0)
        n -= 1
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



# Which canonical commands have any effect in each state (keys are the canonical strings produced
# by parse_commands; "press"/"scroll" stand for any KeyPress/Scroll object and the digits are the
# grid cells). The controller consults this so "what is appropriate right now" lives in one place.
# AWAKE and GRID share the same two-tier *grammar* in the speech thread (a single breath can cross
# the boundary, e.g. "mouse grid five"), but they are listed separately here because these sets are
# read in execution order, after the state has actually advanced.
ALLOWED: dict[str, set] = {st: {c.token for c in COMMAND_TABLE if st in c.states}
                    for st in (SLEEPING, AWAKE, GRID, DICTATE)}


def command_token(cmd) -> str:
    """The ALLOWED key for a parsed command (KeyPress/Scroll collapse to 'press'/'scroll')."""
    if isinstance(cmd, KeyPress):
        return "press"
    if isinstance(cmd, Scroll):
        return "scroll"
    if isinstance(cmd, Media):
        return "media"
    if isinstance(cmd, ModClick):
        return cmd.kind                 # a modified click is allowed wherever the plain click is
    return cmd


def next_state(state: str, token: str) -> str:
    """State after an (allowed) command; mirrors what Controller.handle does."""
    if token == "stop":
        return SLEEPING
    if state == SLEEPING:
        return AWAKE if token == "start" else state
    if state == AWAKE:
        return GRID if token == "grid" else DICTATE if token == "dictate" else state
    if state == DICTATE:
        return AWAKE if token == "listen" else state
    return AWAKE if token in ("left", "right", "double", "move", "cancel") else state   # GRID


def sequence_valid(cmds: list, state: str) -> bool:
    """Can this command sequence be said starting in `state`? Uses ALLOWED and next_state, so
    grid words only count inside the grid (or right after "mouse grid"), "start listening" only
    when asleep, nothing but "start" while asleep, and so on."""
    for c in cmds:
        token = command_token(c)
        if token not in ALLOWED[state]:
            return False
        state = next_state(state, token)
    return True


def validate(text, state: str, min_word_conf: float = 0.0, media: bool = True):
    """Commands for `text` (a string or Vosk's word list) if it is a complete, well-ordered
    utterance in `state`; None if anything is stray, incomplete or out of place."""
    cmds = parse_commands(text, min_word_conf=min_word_conf, strict=True, media=media)
    return cmds if cmds and sequence_valid(cmds, state) else None


class Controller:
    """State machine: SLEEPING <-> AWAKE <-> GRID. Talks to `mouse` and `overlay`."""

    def __init__(self, bounds: Region, mouse, overlay, on_state=lambda s: None, keyboard=None,
                 media=None, on_reload=None, windows=None, dictation=None):
        self.nav = GridNavigator(bounds)
        self.on_reload = on_reload or (lambda: print("reload requested (nothing wired up)"))
        self.mouse, self.overlay, self.on_state = mouse, overlay, on_state
        self.keyboard = keyboard
        self.media = media                    # object with .send(action), or None (--no-media)
        self.windows = windows                # object with .act(action): minimize/maximize/restore
        self.dictation = dictation            # DictationSession (or a stand-in); see "dictate"
        self.state = SLEEPING
        self.mark: tuple[int, int] | None = None

    def _set(self, state: str) -> None:
        if state == SLEEPING:
            # However we got here (voice, hotkey, status-box click), drop everything in flight:
            # the grid overlay, any zoom levels and any pending drag mark.
            self.overlay.hide()
            self.mark = None
            self.nav.reset()
        was, self.state = self.state, state
        if was != state and self.dictation:
            self.dictation.cancel_pending()           # a queued "dictate" is stale once anything changes
            if state == DICTATE:
                self.dictation.start()
            elif was == DICTATE:
                self.dictation.stop()                 # also delivers a phrase still being spoken
        self.on_state(state)

    def _show(self) -> None:
        self.overlay.show(self.nav.current, self.mark)

    def _start_dictation(self) -> None:
        """"dictate": switch to typing what is said. If the speech models are not loaded yet this
        starts loading them, and dictation begins by itself when they are ready."""
        if self.dictation is None:
            print("dictation is not available")
        elif not self.dictation.ready:
            self.dictation.request()
        else:
            self._set(DICTATE)

    def _leave_grid(self, new_state: str = AWAKE) -> None:
        self.overlay.hide()
        self.mark = None
        self.nav.reset()
        self._set(new_state)

    def _hold(self, mods) -> None:
        if mods and self.keyboard and hasattr(self.keyboard, "hold"):
            self.keyboard.hold(mods)

    def _release(self, mods) -> None:
        if mods and self.keyboard and hasattr(self.keyboard, "release"):
            self.keyboard.release(mods)

    def _click_here(self, cmd: str, mods=()) -> None:
        """Click at the current cursor position (used while awake, with no grid open)."""
        button = "left" if cmd == "double" else cmd
        self._hold(mods)
        try:
            self.mouse.click(button, double=(cmd == "double"))
        finally:
            self._release(mods)
        print(f"{'+'.join(mods) + '+' if mods else ''}{cmd} click at cursor")

    def handle(self, cmd) -> None:
        # One gate decides whether a command is appropriate right now (see ALLOWED); anything else
        # is dropped here instead of silently by whichever branch happened to run. This is evaluated
        # in execution order, so a single utterance can advance the state mid-breath: "mouse grid
        # five" opens the grid (allowed while AWAKE) and only then uses the digit (allowed in GRID).
        token = command_token(cmd)
        if token not in ALLOWED[self.state]:
            if self.state == GRID and (token in ("press", "media", "reload", "dictate")
                                       or token in WINDOW_COMMANDS.values()):
                print("ignored: key presses, media buttons, dictation and window commands are off "
                      "while the mouse grid is open (click, move mouse or cancel first)")
            return

        if isinstance(cmd, Media):
            if self.media:
                self.media.send(cmd.action)
            return

        mods: tuple = ()
        if isinstance(cmd, ModClick):                  # same as the plain click, with keys held
            mods, cmd = cmd.mods, cmd.kind

        if isinstance(cmd, Scroll):
            self.mouse.scroll(cmd.direction, cmd.amount)
            return

        if isinstance(cmd, KeyPress):
            if self.keyboard:
                for ch in cmd.chords:
                    self.keyboard.press(ch.mods, ch.key, ch.count)
            return

        if self.state == SLEEPING:
            if cmd == "start":
                self._set(AWAKE)
            return

        if self.state == DICTATE:             # speech is going to the dictation engine, not Vosk
            if cmd == "listen":                   # timeout, or "stop dictation": back to listening
                self._set(AWAKE)
            elif cmd == "stop":                   # the hotkey / status-box toggle: go to sleep
                self._set(SLEEPING)
            return

        if self.state == AWAKE:
            if cmd == "stop":
                self._set(SLEEPING)
            elif cmd == "dictate":
                self._start_dictation()
            elif cmd == "reload":
                self.on_reload()
            elif cmd in WINDOW_COMMANDS.values():
                if self.windows:
                    self.windows.act(cmd)
            elif cmd == "grid":
                self.nav.reset()
                self.mark = None
                self._set(GRID)
                self._show()
            elif cmd in ("left", "right", "double"):
                self._click_here(cmd, mods)   # click wherever the cursor already is, no grid needed
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
            print((f"{'+'.join(mods)}+" if mods else "") + f"{cmd} click at {target}"
                  + (f" (drag from {self.mark})" if self.mark and cmd != "double" else ""))
            self._hold(mods)
            try:
                if self.mark and cmd != "double":
                    self.mouse.drag(cmd, self.mark, target)
                else:
                    self.mouse.click("left" if cmd == "double" else cmd, double=(cmd == "double"))
            finally:
                self._release(mods)
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


def self_command() -> list[str]:
    """Command line that starts this program again exactly as it was started."""
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    args = list(sys.argv[1:])
    if frozen:
        return [os.path.abspath(sys.argv[0]), *args]
    return [sys.executable, os.path.abspath(sys.argv[0]), *args]


def relaunch_command() -> list[str]:
    """Command line that starts this program again with the same options, listening from the start."""
    cmd = self_command()
    if "--start-awake" not in cmd:
        cmd.append("--start-awake")
    return cmd


# Windows process priority classes. "realtime" is deliberately not offered: it can starve the system's
# own input handling (mouse and keyboard) and the audio drivers this program depends on.
PRIORITY_CLASSES = {"normal": 0x00000020, "above": 0x00008000, "high": 0x00000080}


def set_priority(level: str) -> bool:
    """Give this process the named Windows priority class. True on success."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    return bool(k.SetPriorityClass(k.GetCurrentProcess(), PRIORITY_CLASSES[level]))


def is_admin() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Ask Windows to start a copy of this program elevated (shows the UAC prompt). True if the
    elevated copy was started - the caller should then exit; False if it was refused or failed."""
    import ctypes
    import subprocess
    exe, *args = self_command()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), None, 1)
    return rc > 32


def hide_console() -> None:
    """Hide this program's console window (if it has one). Output still goes to it, unseen."""
    import ctypes
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)             # SW_HIDE


def reload_program() -> None:
    """Start a fresh copy, then exit this one (which frees the microphone and the hooks)."""
    import subprocess
    print("reloading ...")
    subprocess.Popen(relaunch_command())
    if sys.stdout:                      # None when run with pythonw / no console
        sys.stdout.flush()
    os._exit(0)


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


def raise_topmost(widget) -> None:
    """Put the window at the very top of the always-on-top band, without taking focus or moving it.
    Windows keeps topmost windows in the order they were last raised, so re-raising ours (it is
    called a few times a second) puts it back above the taskbar, the Start menu and other
    always-on-top windows that have since been raised. Windows in the system's higher UI-access band
    (the on-screen keyboard, Magnifier, Task Manager when set to stay on top, the lock screen) cannot
    be covered by a normal program."""
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.GetAncestor(widget.winfo_id(), 2)           # GA_ROOT
    HWND_TOPMOST, FLAGS = -1, 0x0001 | 0x0002 | 0x0010   # NOSIZE | NOMOVE | NOACTIVATE
    u.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, FLAGS)


# SHQueryUserNotificationState values: 2 = a full-screen app is running (Do Not Disturb kicks in),
# 3 = a Direct3D full-screen app is running.
BUSY_STATES = (2, 3)
MAX_INSET = 8


def notification_state():
    """Windows' idea of what the user is doing (see BUSY_STATES), or None if it cannot be read."""
    import ctypes
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value
    except Exception:
        pass
    return None


def next_inset(state, baseline_busy: bool, inset: int, limit: int = MAX_INSET) -> int:
    """How far short of the screen the grid overlay should stop, given what Windows reports now.

    If Windows reports a full-screen app *because of the overlay* (it was not busy before the grid
    opened), make the overlay one pixel smaller and look again, up to `limit`. If something else
    was already full-screen, or Windows is happy, leave it alone."""
    if state in BUSY_STATES and not baseline_busy and inset < limit:
        return inset + 1
    return inset


class Overlay:
    KEY = "#010203"      # colour treated as fully transparent

    def __init__(self, root, screen: Region, minor_grid: bool = True, inset: int = 1, adapt: bool = True):
        import tkinter as tk
        self.tk, self.screen = tk, screen
        self.minor_grid = minor_grid          # thin 9x9 preview lines inside the 3x3 grid
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        # A borderless window that covers the monitor exactly is treated by Windows as a full-screen
        # app, which switches on Do Not Disturb / Focus Assist and shuffles the taskbar's notification
        # area. Stopping `inset` pixel(s) short of the bottom edge avoids that, and is not noticeable.
        self.inset = max(0, int(inset))
        self.adapt = adapt                    # grow the inset if Windows still thinks it is full-screen
        self._apply_geometry()
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(self.win, bg=self.KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        make_click_through(self.win)
        self.win.withdraw()
        self.shown = False
        self._baseline_busy = False

    def _apply_geometry(self) -> None:
        s = self.screen
        self.win.geometry(f"{int(s.w) - self.inset}x{int(s.h) - self.inset}+{int(s.x)}+{int(s.y)}")

    def _check_notification_state(self, tries_left: int) -> None:
        """Windows decides asynchronously whether a full-screen app is running. If it has just
        decided that the grid is one, shrink the overlay a pixel and look again."""
        if not self.shown or tries_left <= 0:
            return
        new = next_inset(notification_state(), self._baseline_busy, self.inset)
        if new != self.inset:
            self.inset = new
            self._apply_geometry()
            print(f"Windows treated the grid as a full-screen app; overlay is now {new}px smaller")
            tries_left = 5
        self.win.after(300, self._check_notification_state, tries_left - 1)

    def raise_(self) -> None:
        """Back to the top of the screen (only while the grid is showing)."""
        if self.shown:
            raise_topmost(self.win)

    def hide(self) -> None:
        self.shown = False
        self.win.withdraw()
        self.win.update()        # process the unmap now; Tk would otherwise defer it until idle

    def show(self, r: Region, mark: tuple[int, int] | None) -> None:
        c, s = self.canvas, self.screen
        c.delete("all")
        # minor grid: each of the nine cells split 3x3 again (a preview of the next zoom level),
        # thin and dashed so it reads as secondary. Skipped when the minor cells would be tiny.
        if self.minor_grid and min(r.w, r.h) / 9 >= 4:
            minor = dict(fill="#ff5a5a", width=1, dash=(6, 6))     # 1px: as thin as Tk draws
            for k in range(1, 9):
                if k % 3 == 0:
                    continue                      # those are the major lines, drawn below
                x, y = r.x + r.w * k / 9, r.y + r.h * k / 9
                c.create_line(x, r.y, x, r.y + r.h, **minor)
                c.create_line(r.x, y, r.x + r.w, y, **minor)
        # major grid (the rest of the screen is left undimmed)
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
        if not self.shown:
            self._baseline_busy = notification_state() in BUSY_STATES    # already busy before we appeared?
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        first_time = not self.shown
        self.shown = True
        raise_topmost(self.win)
        if first_time and self.adapt:
            self.win.after(300, self._check_notification_state, 5)


class StatusPill:
    COLORS = {SLEEPING: ("#444444", "Sleeping", "say \"start listening\""),
              AWAKE: ("#1e8e3e", "Listening", "\"mouse grid\", \"press ...\" or \"dictate\""),
              GRID: ("#c5221f", "Grid", "say 1-9, back, mark, cancel"),
              DICTATE: ("#1a5fb4", "Dictating", "just talk; go quiet to stop")}
    METER_W, METER_H = 90, 10
    HINT_SECONDS = 6          # how long the hint / last-heard phrase stay visible
    PAD = 8                   # spacing between every element and around the edge
    # Where the visual middle of a line of text sits above its baseline, as a fraction of the font
    # size (about half an x-height plus a little for capitals). Every text item - and the meter and
    # arrow - is centred on one shared line using this, so differing fonts don't look high or low.
    VISUAL_MID = 0.30

    CORNERS = ("bottom-right", "bottom-left", "top-left", "top-right")   # order the button cycles

    def __init__(self, root, screen: Region, corner: str = "bottom-right"):
        import tkinter as tk
        import tkinter.font as tkfont
        self.corner = corner                  # which screen corner the box sits in
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.85)
        self.canvas = tk.Canvas(self.win, highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        self.f_label = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_heard = tkfont.Font(family="Calibri", size=10)   # proportional cousin of Consolas (same designer)
        self.f_arrow = tkfont.Font(family="Segoe UI Symbol", size=12, weight="bold")
        self.screen = screen
        self.level = 0.0
        self.state = SLEEPING
        self.label_text = ""
        self.heard_text = ""
        self.meter_x = 0                      # set by _draw
        self.cy = 0
        self.on_click = lambda: None          # set by main(); toggles listening
        # Bind ONCE on the toplevel (see earlier double-toggle bug). One handler decides whether the
        # click landed on the arrow (move the box) or elsewhere (toggle listening).
        self._last_click = 0.0
        self._arrow_x0 = 0
        self.win.bind("<Button-1>", self._clicked)
        self._hint_job = self._heard_job = None
        self._heard_seq = -1
        self.set(SLEEPING)
        make_click_through(self.win, clickable=True)   # takes clicks but never steals focus

    # ---- drawing -----------------------------------------------------------
    def _em_px(self, font) -> float:
        size = font.cget("size")
        return abs(size) if size < 0 else size * self.win.winfo_fpixels("1i") / 72.0

    def _baseline(self) -> float:
        """The one baseline shared by the state text and the heard phrase, chosen so the state
        text's visual middle sits on the centre line. (Centring each font separately put the
        monospace phrase about a pixel higher than the state text.)"""
        return self._text_y(self.f_label) + (self.f_label.metrics("ascent")
                                             - self.f_label.metrics("linespace") / 2.0)

    def _text_y(self, font, baseline: float | None = None) -> float:
        """y for anchor='w' text. With `baseline`, the text's baseline lands exactly there;
        without it, its visual middle lands on the centre line (used for the arrow glyph)."""
        m = font.metrics()
        if baseline is not None:
            return baseline - (m["ascent"] - m["linespace"] / 2.0)
        visual_mid = m["ascent"] - self.VISUAL_MID * self._em_px(font)
        return self.cy + (m["linespace"] / 2.0 - visual_mid)

    def _draw(self) -> None:
        P, c = self.PAD, self.canvas
        colour = self.COLORS[self.state][0]
        c.delete("all")
        arrow = "\u21c4"
        label_w = self.f_label.measure(self.label_text)
        heard_w = self.f_heard.measure(self.heard_text) if self.heard_text else 0
        arrow_w = self.f_arrow.measure(arrow)
        height = max(self.f_label.metrics("linespace"), self.f_arrow.metrics("linespace"),
                     self.METER_H) + 2 * P
        x = P + 2
        width = (x + label_w + (P + heard_w if heard_w else 0)
                 + P + self.METER_W + P + arrow_w + P)
        c.config(width=int(width), height=int(height), bg=colour)
        self.cy = height / 2.0
        base = self._baseline()
        c.create_text(x, self._text_y(self.f_label, base), text=self.label_text, anchor="w",
                      font=self.f_label, fill="white")
        x += label_w
        if heard_w:
            x += P
            c.create_text(x, self._text_y(self.f_heard, base), text=self.heard_text, anchor="w",
                          font=self.f_heard, fill="white")
            x += heard_w
        x += P
        self.meter_x = x
        c.create_rectangle(x, self.cy - self.METER_H / 2, x + self.METER_W,
                           self.cy + self.METER_H / 2, width=0, fill="#1b1b1b")
        self.bar = c.create_rectangle(x, self.cy - self.METER_H / 2, x, self.cy + self.METER_H / 2,
                                      width=0, fill="#34c759")
        x += self.METER_W + P
        self._arrow_x0 = x - P / 2
        c.create_text(x, self._text_y(self.f_arrow), text=arrow, anchor="w",
                      font=self.f_arrow, fill="white")
        self._paint_level()
        self._place()

    def _paint_level(self) -> None:
        colour = "#34c759" if self.level < 0.6 else "#ffcc00" if self.level < 0.85 else "#ff3b30"
        top, bottom = self.cy - self.METER_H / 2, self.cy + self.METER_H / 2
        self.canvas.coords(self.bar, self.meter_x, top, self.meter_x + self.level * self.METER_W, bottom)
        self.canvas.itemconfig(self.bar, fill=colour)

    # ---- interaction ---------------------------------------------------------
    def raise_(self) -> None:
        raise_topmost(self.win)

    def _clicked(self, event=None) -> None:
        now = time.monotonic()
        if now - self._last_click < 0.35:       # ignore bounce / duplicate events
            return
        self._last_click = now
        if event is not None and event.x >= self._arrow_x0:
            self._flip()                         # arrow: move the box, don't toggle listening
        else:
            self.on_click()

    def _flip(self) -> None:
        i = self.CORNERS.index(self.corner)
        self.corner = self.CORNERS[(i + 1) % len(self.CORNERS)]
        self._place()

    def _place(self) -> None:
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = 16 if "left" in self.corner else self.screen.w - w - 16
        y = 16 if "top" in self.corner else self.screen.h - h - 56      # 56 clears the taskbar
        self.win.geometry(f"+{int(x)}+{int(y)}")

    # ---- state / text ----------------------------------------------------------
    def set(self, state: str) -> None:
        _, name, hint = self.COLORS[state]
        self.state = state
        self.label_text = f"{name} - {hint}"
        if self._hint_job is not None:                      # restart the hint timer on every change
            self.win.after_cancel(self._hint_job)
        self._hint_job = self.win.after(int(self.HINT_SECONDS * 1000), self._hide_hint)
        self._draw()

    def _hide_hint(self) -> None:
        """Shrink 'Listening - "mouse grid" or ...' to just 'Listening' once it has been read."""
        self._hint_job = None
        self.label_text = self.COLORS[self.state][1]
        self._draw()

    def set_heard(self, text: str, seq: int = 0) -> None:
        """Show the last recognised phrase for a few seconds. `seq` changes with every new
        recognition (so a repeated phrase refreshes the timer); the UI poll loop calls this
        constantly."""
        if seq == self._heard_seq:                      # nothing new since the last poll
            return
        self._heard_seq = seq
        if self._heard_job is not None:
            self.win.after_cancel(self._heard_job)
            self._heard_job = None
        if self.heard_text != text:
            self.heard_text = text
            self._draw()
        if text:
            self._heard_job = self.win.after(int(self.HINT_SECONDS * 1000), self._clear_heard)

    def _clear_heard(self) -> None:
        self._heard_job = None
        self.heard_text = ""
        self._draw()

    def set_level(self, v: float) -> None:
        """Fast attack, slow decay so short words are visible."""
        self.level = max(v, self.level * 0.8)
        self._paint_level()


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------
def ensure_model(path: str | None) -> str:
    if path:
        return path
    # Look in order: bundled inside the program (onefile builds unpack beside __file__), next to
    # the executable (compiled __file__ may be a temp folder, so use argv[0] there), else download.
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0] if frozen else __file__))
    bundled = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", MODEL_NAME)
    beside = os.path.join(exe_dir, "models", MODEL_NAME)
    for candidate in (bundled, beside):
        if os.path.isdir(candidate):
            return candidate
    base = os.path.join(exe_dir, "models")
    target = os.path.join(base, MODEL_NAME)
    os.makedirs(base, exist_ok=True)
    zip_path = target + ".zip"
    print(f"Downloading speech model (~40 MB) from {MODEL_URL} ...")
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(base)
    os.remove(zip_path)
    return target


def find_input_device(devices, name: str, hostapi=None):
    """Index of the input device called `name` in sounddevice's device list, or None.

    Device numbers change when a microphone is unplugged and plugged back in, so the program
    remembers the NAME and looks it up again. Preference: same name on the same host API, then the
    same name anywhere, then a name that contains / is contained in it (Windows sometimes appends
    or drops a suffix such as "(2)"). Only devices that can record count."""
    want = name.strip().lower()
    cands = [(i, d) for i, d in enumerate(devices) if d.get("max_input_channels", 0) > 0]
    tiers = (
        lambda d: d["name"].strip().lower() == want and (hostapi is None or d.get("hostapi") == hostapi),
        lambda d: d["name"].strip().lower() == want,
        lambda d: want in d["name"].lower() or d["name"].strip().lower() in want,
    )
    for ok in tiers:
        for i, d in cands:
            if ok(d):
                return i
    return None


class SpeechThread(threading.Thread):
    """Mic -> Vosk with one recogniser per state (wake-only / awake / grid), then a hard grammar
    check: an utterance is acted on only if it is complete and well-ordered for the current state
    ("page delta" is rejected; a lower-ranked "page down" alternative is used if --nbest has one)."""

    def __init__(self, model_path, device, min_conf, get_state, out_queue, open_vocab=False,
                 word_conf=0.0, nbest=0, log_path=None, lenient=False, flat_grammar=False,
                 early_digits=True, media=True):
        super().__init__(daemon=True)
        self.model_path, self.device, self.min_conf = model_path, device, min_conf
        self.open_vocab = open_vocab
        self.word_conf = word_conf    # per-word floor: drop single words the model isn't sure of
        self.nbest = nbest            # 0 = single result; N>0 = ask for N alternative hypotheses
        self.log_path = log_path      # if set, append each recognition (JSONL) here for analysis
        self.lenient = lenient        # True = old behaviour: skip stray words instead of rejecting
        self.flat_grammar = flat_grammar   # True = old flat word list instead of the BNF sentences
        self.media = media                 # False (--no-media): "media ..." is neither heard nor run
        self.early_digits = early_digits   # in the grid, zoom on each number as soon as it is stable
        self.level = 0.0         # latest mic loudness, 0..1, read by the UI for the meter
        self.last_heard = ""     # last recognised phrase, read by the UI
        self.heard_seq = 0       # bumped on each recognition so the UI can tell repeats apart
        self.get_state, self.out = get_state, out_queue
        self.dictation_feed = None      # while the state is DICTATE, mic audio goes here instead of Vosk
        self.audio: queue.Queue[bytes] = queue.Queue()
        self.mic_ok = False             # True while audio is flowing
        self._last_audio = time.monotonic()
        self._want_name = None          # name of the chosen microphone, to find it again after a replug
        self._want_hostapi = None

    def _confident(self, words: list) -> bool:
        if not words:
            return False
        return sum(w.get("conf", 1.0) for w in words) / len(words) >= self.min_conf

    @staticmethod
    def _hypotheses(result: dict) -> list:
        """Return [(text, confidence, words), ...] best-first, for both result shapes.

        Without alternatives the recogniser returns {"text": ..., "result": [...]}. With
        SetMaxAlternatives(n) it returns {"alternatives": [{"text","confidence","words"}, ...]}
        where "confidence" is a raw acoustic score (not a probability).
        """
        alts = result.get("alternatives")
        if alts is not None:
            return [(a.get("text", ""), a.get("confidence"),
                     a.get("words") or a.get("result") or []) for a in alts]
        return [(result.get("text", ""), None, result.get("result") or [])]

    def _acceptable(self, text: str, words: list, state: str) -> bool:
        src = words or text
        if self.lenient:        # old rule: anything that parses to some command valid in this state
            return any(command_token(c) in ALLOWED[state]
                       for c in parse_commands(src, min_word_conf=self.word_conf, media=self.media))
        return validate(src, state, self.word_conf, self.media) is not None

    def _commands(self, text: str, words: list, state: str):
        """The commands to run for one hypothesis, or None to ignore it."""
        src = words or text
        if self.lenient:
            return parse_commands(src, min_word_conf=self.word_conf, media=self.media) or None
        return validate(src, state, self.word_conf, self.media)

    def _choose(self, hyps: list, state: str) -> int:
        """Index of the best hypothesis that is a valid utterance in `state`.

        Grammar decoding flattens per-word confidences, so the alternatives' own ordering is the
        only usable signal. The top guess is sometimes junk ("h down", "page delta" for "page
        down"), so take the highest-ranked hypothesis that passes the strict grammar check. If
        none does, return 0 (the caller then ignores the utterance rather than guessing).
        """
        for i, (text, _, words) in enumerate(hyps):
            if self._acceptable(text, words, state):
                return i
        return 0

    def _report(self, hyps: list, chosen: int = 0, accepted: bool = True) -> None:
        """Log each recognised word with its confidence and remember a short summary for the UI.

        The per-word numbers are what --word-conf acts on; avg is what --min-conf gates, and min
        is the weakest word (the first one dropped). Competing hypotheses from --nbest are listed
        too, each with the recogniser's own (raw, non-probability) score; `chosen` marks the one
        actually used (0 = the top guess, which the chooser only overrides on --nbest).
        """
        text, _, words = hyps[0]
        confs = [float(w.get("conf", 1.0)) for w in words]
        label = "heard" if accepted else "ignored (not a valid command here)"
        if confs:
            detail = " ".join(f"{w.get('word', '?')}={c:.2f}" for w, c in zip(words, confs))
            print(f"{label}: {text}   [{detail}]   avg {sum(confs)/len(confs):.2f}  min {min(confs):.2f}")
        else:
            print(f"{label}: {text}")
        for j, (alt_text, alt_conf, _) in enumerate(hyps[1:], start=1):
            score = f"{alt_conf:.1f}" if isinstance(alt_conf, (int, float)) else "?"
            mark = "   <- chosen" if j == chosen else ""
            print(f"        alt: {alt_text}   (score {score}){mark}")
        if chosen > 0 and accepted:
            print("        (top guess was not a valid command here; using the chosen alternative)")
        # The status-pill summary reflects what we actually applied.
        ctext, _, cwords = hyps[chosen]
        self.heard_seq += 1
        self.last_heard = ctext                    # just the phrase; avg/min stay in the console
        if not accepted and ctext:
            self.last_heard = "\u2717 " + self.last_heard          # shows a rejected phrase

    def _write_log(self, fh, state: str, asleep: bool, hyps: list, chosen: int,
                   valid=None) -> None:
        """Append one JSON object (one line) describing this recognition to the JSONL log.

        Everything the recogniser produced is kept - the top guess, the alternatives with their
        raw scores, and each word with its confidence - plus the state and which hypothesis ran, so
        common mishearings can be mined later (e.g. group by `heard` and inspect `hypotheses`).
        """
        record = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "state": state,
            "asleep": asleep,
            "heard": hyps[0][0],                       # the recogniser's top guess
            "chosen": chosen,                          # index into hypotheses that was applied
            "used": hyps[chosen][0],                   # the phrase actually acted on
            "hypotheses": [
                {"text": t, "score": s,
                 "words": [{"word": w.get("word"), "conf": w.get("conf")} for w in ws]}
                for t, s, ws in hyps],
        }
        if valid is not None:
            record["valid"] = bool(valid)              # did the chosen phrase pass the grammar check
        try:
            fh.write(json.dumps(record) + "\n")
            fh.flush()
        except OSError as e:
            print(f"warning: log write failed: {e}")

    # ---- microphone handling: survive unplug / replug ----------------------------------------
    STALL_SECONDS = 2.0       # no audio for this long means the microphone has gone
    RETRY_SECONDS = 1.0       # how often to look for it again

    def _say(self, text: str) -> None:
        """Print and show a short notice in the status box."""
        print(text)
        self.heard_seq += 1
        self.last_heard = text

    @staticmethod
    def _refresh_audio(sd) -> None:
        """Make PortAudio re-scan the audio devices (it caches the list; without this a replugged
        microphone is never seen). Only safe while no stream is open."""
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass

    def _resolve_device(self, sd):
        """Device to open now. With no --device the system default is followed. With --device the
        microphone is found again by NAME, because its number can change after a replug."""
        if self.device is None:
            return None
        if self._want_name is None:                  # first open: remember what was asked for
            if isinstance(self.device, str):
                self._want_name = self.device
            else:
                try:
                    info = sd.query_devices(self.device)
                    self._want_name, self._want_hostapi = info["name"], info.get("hostapi")
                except Exception:
                    return self.device
            return self.device
        idx = find_input_device(list(sd.query_devices()), self._want_name, self._want_hostapi)
        if idx is None:
            raise RuntimeError(f"microphone '{self._want_name}' not found")
        return idx

    def _open_mic(self, sd, callback, sleep=time.sleep):
        """Open the microphone stream, retrying until it works (also covers 'not plugged in yet')."""
        last_err = None
        while True:
            try:
                stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=800,
                                           device=self._resolve_device(sd), dtype="int16",
                                           channels=1, callback=callback)
                stream.start()
                self._last_audio = time.monotonic()
                self.mic_ok = True
                return stream
            except Exception as e:
                if str(e) != last_err:               # say it once per distinct problem, not every retry
                    last_err = str(e)
                    self._say(f"\u26a0 no microphone ({last_err}); waiting for it ...")
                sleep(self.RETRY_SECONDS)
                self._refresh_audio(sd)

    def _mic_lost(self, stream) -> bool:
        """The stream has stopped, or has delivered nothing for a while (device unplugged)."""
        try:
            stopped = not stream.active
        except Exception:
            stopped = True
        return stopped or time.monotonic() - self._last_audio > self.STALL_SECONDS

    def _close_mic(self, sd, stream) -> None:
        for how in ("abort", "close"):
            try:
                getattr(stream, how)()
            except Exception:
                pass
        self.level = 0.0
        self.mic_ok = False
        self._say("\u26a0 microphone lost; reconnecting ...")
        self._refresh_audio(sd)

    # ---- the speech loop, in small pieces ------------------------------------
    # Two threads share the work (the audio callback is a third, owned by PortAudio):
    #   decoder  (this thread): audio chunk -> Vosk -> raw result      (the heavy, C++ part)
    #   finisher (own thread) : raw result -> n-best choice, grammar check, log, pill, commands out
    # Vosk releases the GIL while it decodes, so the finisher's Python work (JSON, parsing, disk and
    # console writes) overlaps the decoding of the next chunk instead of delaying it. Everything that
    # reaches the controller goes through the finisher's single queue, so commands keep their order.

    def _make_recogniser(self, model, KaldiRecognizer, grammar):
        r = (KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar)) if grammar
             else KaldiRecognizer(model, SAMPLE_RATE))        # no grammar = open vocabulary
        r.SetWords(True)
        if self.nbest > 0:
            r.SetMaxAlternatives(self.nbest)                   # n-best hypotheses (changes the JSON shape)
        return r

    def _grammars(self) -> dict:
        """The recogniser grammar (sentence list, word list or None) for each state."""
        if self.open_vocab:
            awake_g = grid_g = None
        elif self.flat_grammar:
            awake_g = grid_g = COMMAND_GRAMMAR
        else:
            awake_g, grid_g = AWAKE_SENTENCES, GRID_SENTENCES
            if not self.media:               # same grammar without the "media ..." commands
                awake_g = grammar_sentences(build_command_grammar("awake", media=False),
                                            base=list(_COMMON_EXAMPLES))
        return {SLEEPING: WAKE_GRAMMAR, AWAKE: awake_g, GRID: grid_g}

    def _build_recognisers(self, model, KaldiRecognizer) -> dict:
        """One recogniser per state. Each compiles its own grammar inside Vosk (C++, GIL released),
        so the three are built side by side; if that fails for any reason, build them one by one."""
        grammars = self._grammars()
        build = lambda st: self._make_recogniser(model, KaldiRecognizer, grammars[st])
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(grammars)) as pool:
                recs = dict(zip(grammars, pool.map(build, grammars)))
        except Exception as e:
            print(f"parallel start-up failed ({e}); building one at a time")
            recs = {st: build(st) for st in grammars}
        return recs

    def _open_log(self):
        if not self.log_path:
            return None
        try:
            fh = open(self.log_path, "a", encoding="utf-8")
            print(f"Logging recognitions to {self.log_path}")
            return fh
        except OSError as e:
            print(f"warning: cannot write log file {self.log_path}: {e}")
            return None

    def _finish(self, item, log) -> None:
        """Finisher: turn one decoder item into commands for the controller."""
        kind = item[0]
        if kind == "digit":                       # an early zoom digit from a partial result
            self.out.put(item[1])
            return
        _, state, result, sent = item             # a final result
        hyps = self._hypotheses(result)
        text, _, words = hyps[0]
        if is_noise(text):                        # "", " " or only [unk]: not worth logging or showing
            return
        # With --nbest, prefer the highest-ranked alternative that is a valid utterance in this
        # state (so "page delta" loses to "page down").
        chosen = self._choose(hyps, state) if len(hyps) > 1 else 0
        ctext, _, cwords = hyps[chosen]
        cmds = self._commands(ctext, cwords, state)
        if log is not None:                       # record every recognition, even weak ones
            self._write_log(log, state, state == SLEEPING, hyps, chosen, valid=cmds)
        # Weak overall confidence is ignored; no per-word data (some result shapes have none)
        # cannot be judged, so the grammar check decides.
        if cwords and not self._confident(cwords):
            return
        self._report(hyps, chosen, accepted=bool(cmds))
        if sent and cmds:                         # those leading numbers have already been acted on
            cmds = drop_applied_digits(cmds, sent)
        for cmd in cmds or ():
            self.out.put(cmd)

    def _finisher_loop(self, items: "queue.Queue", log) -> None:
        while True:
            item = items.get()
            if item is None:
                return
            try:
                self._finish(item, log)
            except Exception:                     # one bad result must not stop the pipeline
                import traceback
                traceback.print_exc()

    def _decode(self, rec, state, data, loop, emit) -> None:
        """Decoder: feed one audio chunk to the recogniser for `state` and emit what comes out."""
        if rec.AcceptWaveform(data):
            emit(("final", state, json.loads(rec.Result()), loop.early))
            loop.early, loop.prev_digits = 0, []
        elif state == GRID and self.early_digits:
            # Mid-utterance: zoom as soon as a spoken number is stable (unchanged between two
            # successive partials), instead of waiting for the whole sequence to end.
            digits = leading_digits(json.loads(rec.PartialResult()).get("partial", ""))
            for d in stable_prefix(loop.prev_digits, digits)[loop.early:]:
                emit(("digit", str(d)))
                loop.early += 1
            loop.prev_digits = digits

    class _Loop:
        """Decoder bookkeeping between chunks."""
        def __init__(self):
            self.last_state = SLEEPING
            self.early = 0                  # grid numbers already sent from partials
            self.prev_digits = []           # the last partial's run of numbers

        def reset(self):
            self.early, self.prev_digits = 0, []

    def _listen(self, sd, recs, emit) -> None:
        """Decoder loop: keep the microphone open and decode until the thread is killed."""
        def cb(indata, frames, t, status):
            data = bytes(indata)
            self._last_audio = time.monotonic()
            self.level = level_from_pcm(data)
            self.audio.put(data)

        loop, stream, opened_before = self._Loop(), None, False
        try:
            while True:
                if stream is None:                    # first start, or the microphone came back
                    stream = self._open_mic(sd, cb)
                    while not self.audio.empty():     # drop audio from before the gap
                        self.audio.get_nowait()
                    for r in recs.values():
                        r.Reset()
                    loop.reset()
                    self._say("microphone back" if opened_before else
                              "Microphone open. Say \"start listening\".")
                    opened_before = True
                try:
                    data = self.audio.get(timeout=0.5)
                except queue.Empty:
                    if self._mic_lost(stream):
                        self._close_mic(sd, stream)
                        stream = None
                    continue
                state = self.get_state()
                if state == DICTATE:                  # the dictation engine owns the audio now
                    loop.last_state = state
                    if self.dictation_feed:
                        self.dictation_feed(data)
                    continue
                if state != loop.last_state:          # state flipped: drop stale audio
                    recs[state].Reset()
                    loop.last_state = state
                    loop.reset()
                self._decode(recs[state], state, data, loop, emit)
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def run(self) -> None:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        model = Model(self.model_path)
        t0 = time.time()
        recs = self._build_recognisers(model, KaldiRecognizer)
        g = self._grammars()
        kind = "open vocabulary" if self.open_vocab else ("flat word list" if self.flat_grammar
                                                          else f"{len(g[AWAKE])}/{len(g[GRID])} sentences")
        print(f"Recognisers ready in {time.time() - t0:.1f}s (grammar: {kind})")
        log = self._open_log()
        items: "queue.Queue" = queue.Queue()
        finisher = threading.Thread(target=self._finisher_loop, args=(items, log), daemon=True,
                                    name="finisher")
        finisher.start()
        try:
            self._listen(sd, recs, items.put)
        finally:
            items.put(None)                           # let the finisher drain, then stop
            finisher.join(timeout=2)
            if log is not None:
                log.close()


# --------------------------------------------------------------------------
# Dictation ("dictate"): type what you say into the focused window. The engine is voice_dictate.py
# (draft model while you speak, accurate final model at each pause). While it is on, the microphone
# audio goes to it instead of Vosk; it hands control back to listening when you stop talking.
# --------------------------------------------------------------------------
@dataclass
class DictationOptions:
    draft_model: str | None = None        # None = voice_dictate's default
    final_model: str | None = None
    no_draft: bool = False                # True: only type each phrase when you pause
    device: str = "cpu"                   # cpu / cuda / auto
    model_dir: str | None = None
    compute_type: str | None = None       # Whisper models only
    language: str | None = "en"
    prompt: str | None = None
    beam: int = 3
    draft_threads: int = 0                # 0 = share the CPU cores sensibly
    final_threads: int = 0
    vad_level: int = 2
    pause_ms: int = 900                   # silence that ends a phrase
    long_after: float = 12.0
    long_pause_ms: int = 600
    max_phrase: float = 20.0
    draft_interval: float = 0.3
    idle: float = 3.0                     # seconds of silence before it returns to listening (0 = never)
    verbose: bool = False


def dictation_available(opts: DictationOptions) -> tuple[bool, str]:
    """Are the packages the chosen dictation models need installed? (ok, message if not)"""
    try:
        import numpy, sounddevice  # noqa: F401
        vd = __import__("voice_dictate")
        names = [opts.final_model or vd.DEFAULT_FINAL] + ([] if opts.no_draft else [opts.draft_model or vd.DEFAULT_DRAFT])
        if any(vd.engine_kind(n) == "whisper" for n in names):
            import faster_whisper  # noqa: F401
        if any(vd.engine_kind(n) != "whisper" for n in names):
            import sherpa_onnx  # noqa: F401
    except ImportError as e:
        return False, (f"dictation needs the package '{e.name}': "
                       f"{os.path.basename(sys.executable)} -m pip install -r requirements.txt")
    return True, ""


class Reframer:
    """Re-cuts the microphone's blocks into the fixed-size frames the voice-activity detector wants."""

    def __init__(self, frame_bytes: int):
        self.n, self.buf = frame_bytes, bytearray()

    def push(self, data: bytes) -> list[bytes]:
        self.buf += data
        out = []
        while len(self.buf) >= self.n:
            out.append(bytes(self.buf[:self.n]))
            del self.buf[:self.n]
        return out

    def reset(self) -> None:
        self.buf.clear()


class DictationUnavailable:
    """Stands in for DictationSession when --no-dictation is given or its packages are missing, so
    saying "dictate" explains why nothing happens instead of failing silently."""
    ready = False

    def __init__(self, say, reason: str):
        self.say, self.reason = say, reason

    def request(self, want: bool = True) -> None:
        self.say(self.reason)

    def cancel_pending(self) -> None: pass
    def start(self) -> None: pass
    def stop(self) -> None: pass
    def feed(self, data: bytes) -> None: pass
    def poll(self) -> None: pass


class DictationSession:
    """Everything dictation needs, behind five calls the rest of the program uses:

        request()   load the models in the background (first use; the first run downloads them).
                    Dictation then starts by itself, via on_ready, if it is still wanted.
        start()/stop()  begin / end typing. stop() still delivers a phrase being spoken.
        feed(pcm)   microphone audio, called from the speech thread while dictating.
        poll()      call from the UI thread a few times a second: types what the engine produced
                    and reports the timeout (on_idle) or the spoken "stop" (on_stop).

    Typing happens on the UI thread (in poll), decoding on worker threads, voice detection on the
    speech thread. voice_dictate does the actual work; this class only connects it to voice_mouse.
    """

    def __init__(self, opts: DictationOptions, say, on_idle, on_stop, on_ready, typist=None,
                 foreground=None, vad=None, load=None, clock=time.monotonic):
        import importlib
        vd = self.vd = importlib.import_module("voice_dictate")
        self.opts, self.say = opts, say
        self.on_idle, self.on_stop, self.on_ready = on_idle, on_stop, on_ready
        self.draft_tr = self.final_tr = None
        self._loader = load or self._load_models
        self._ready = threading.Event()
        self._loading = False
        self.wanted = False                     # "dictate" was said while the models were loading
        self._lock = threading.Lock()           # speech thread feeds, UI thread starts / stops
        self.out: queue.Queue = queue.Queue()
        self.reframer = Reframer(vd.FRAME_BYTES)
        self.draft_worker = None if opts.no_draft else vd.LatestWorker(self._run_draft)
        self.final_worker = vd.FifoWorker(self._run_final)
        self.final_worker.start()
        if self.draft_worker:
            self.draft_worker.start()
        self.pipeline = vd.Pipeline(
            vad or vd.make_vad(opts.vad_level),
            (lambda uid, pcm: self.draft_worker.submit((uid, pcm))) if self.draft_worker else None,
            lambda uid, pcm: self.final_worker.submit((uid, pcm)), self.out,
            vd.Segmenter(end_silence_ms=opts.pause_ms, soft_after_s=opts.long_after,
                         soft_silence_ms=min(opts.long_pause_ms, opts.pause_ms), max_s=opts.max_phrase),
            draft_every_s=opts.draft_interval,
            discard_draft=self.draft_worker.discard if self.draft_worker else (lambda uid: None),
            idle_s=opts.idle, clock=clock)
        self.dictator = vd.Dictator(typist or vd.WinTyper(), foreground or vd.foreground_window,
                                    on_stop=lambda: self.on_stop(), notice=say)

    # ---- models
    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def request(self, want: bool = True) -> None:
        if want:
            self.wanted = True
        if self.ready or self._loading:
            return
        self._loading = True
        self.say("loading dictation models (the first run downloads them, about 750 MB) ...")
        threading.Thread(target=self._load, daemon=True, name="dictation-loader").start()

    def cancel_pending(self) -> None:
        self.wanted = False

    def _load(self) -> None:
        t0, error = time.time(), None
        try:
            self.draft_tr, self.final_tr = self._loader()
        except Exception as e:
            error = e
            traceback.print_exc()
        if error is None:
            self._ready.set()
            self._loading = False
            self.say(f"dictation ready ({time.time() - t0:.1f}s)")
        else:
            self.wanted = False
            self._loading = False                     # so it can be tried again
            self.say(f"dictation models failed to load: {error}")

    def _load_models(self):
        vd, o = self.vd, self.opts
        cores = os.cpu_count() or 4
        if o.no_draft:
            dthreads, fthreads = 0, o.final_threads or cores
        else:
            dthreads = o.draft_threads or max(1, cores // 2)
            fthreads = o.final_threads or max(1, cores - dthreads)
        from types import SimpleNamespace
        args = SimpleNamespace(device=o.device, model_dir=o.model_dir, compute_type=o.compute_type,
                               language=o.language)
        final = vd.make_transcriber(o.final_model or vd.DEFAULT_FINAL, fthreads, o.beam, args, o.prompt)
        draft = None if o.no_draft else vd.make_transcriber(o.draft_model or vd.DEFAULT_DRAFT, dthreads, 1, args)
        models = [m for m in (draft, final) if m]
        threads = [threading.Thread(target=m.load) for m in models]       # loaded side by side
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        if not all(m.model for m in models):
            raise RuntimeError("a model failed to load")
        return draft, final

    # ---- decode jobs (worker threads)
    def _run_draft(self, job) -> None:
        uid, pcm = job
        t = time.time()
        text = self.draft_tr(pcm, uid)
        if self.opts.verbose:
            print(f"draft {uid}: {time.time() - t:.2f}s for {len(pcm) / 32000:.1f}s -> {text!r}")
        self.out.put(("draft", uid, text))

    def _run_final(self, job) -> None:
        uid, pcm = job
        t = time.time()
        try:
            text = self.final_tr(pcm)
        except Exception:
            traceback.print_exc()
            text = ""                                       # never leave a phrase undecided
        if self.opts.verbose:
            print(f"final {uid}: {time.time() - t:.2f}s for {len(pcm) / 32000:.1f}s -> {text!r}")
        self.out.put(("final", uid, text))

    # ---- the calls the program uses
    def start(self) -> None:
        with self._lock:
            self.reframer.reset()
            self.pipeline.set_active(True)              # the idle clock starts now

    def stop(self) -> None:
        with self._lock:
            self.pipeline.set_active(False)

    def feed(self, data: bytes) -> None:
        with self._lock:
            for frame in self.reframer.push(data):
                try:
                    self.pipeline.feed(frame)
                except Exception:
                    traceback.print_exc()

    def poll(self) -> None:
        handlers = {"start": self.dictator.begin, "cancel": self.dictator.cancel,
                    "draft": self.dictator.draft, "final": self.dictator.final}
        while True:
            try:
                ev = self.out.get_nowait()
            except queue.Empty:
                break
            try:
                if ev[0] == "idle":
                    self.on_idle()
                else:
                    handlers[ev[0]](*ev[1:])
            except Exception:
                traceback.print_exc()
        if self.wanted and self.ready:
            self.wanted = False
            self.on_ready()


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Voice-controlled mouse grid for Windows")
    ap.add_argument("--model", help="path to an unpacked Vosk model (default: auto-download)")
    ap.add_argument("--device", type=int, help="input device index (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--min-conf", type=float, default=0.6,
                    help="ignore results below this average word confidence (default 0.6)")
    ap.add_argument("--word-conf", type=float, default=0.5,
                    help="drop individual recognised words below this confidence before parsing "
                         "them into commands (0 disables; default 0.5)")
    ap.add_argument("--nbest", type=int, default=3, metavar="N",
                    help="ask the recogniser for up to N alternative hypotheses, log them, and use "
                         "the best one that parses to a command valid in the current state "
                         "(0 = off; default 3). Their 'score' is a raw acoustic score, not a "
                         "probability.")
    ap.add_argument("--log", metavar="FILE", default="heard.jsonl",
                    help="append every recognition (heard text, alternatives, scores, per-word "
                         "confidences, state, timestamp) to FILE as one JSON object per line, for "
                         "later analysis of common mishearings (default: heard.jsonl)")
    ap.add_argument("--no-log", action="store_true", help="disable the JSONL recognition log")
    ap.add_argument("--lenient", action="store_true",
                    help="old behaviour: skip words that don't fit and run whatever is left, instead "
                         "of ignoring the whole utterance when any part is out of place")
    ap.add_argument("--flat-grammar", action="store_true",
                    help="use the plain word list as the recogniser vocabulary instead of the "
                         "generated BNF sentences (fallback if start-up is slow or recognition is "
                         "worse); the strict grammar check still applies")
    ap.add_argument("--no-early-digits", action="store_true",
                    help="in the grid, wait for the end of the whole utterance before zooming "
                         "(default: zoom on each number as soon as it is recognised)")
    ap.add_argument("--no-minor-grid", action="store_true",
                    help="don't draw the thin dashed 9x9 lines that preview the next zoom level")
    ap.add_argument("--overlay-inset", type=int, default=1, metavar="PIXELS",
                    help="make the grid overlay this many pixels shorter than the screen (default 1) so "
                         "Windows does not treat it as a full-screen app and switch on Do Not Disturb; "
                         "0 = cover the whole screen")
    ap.add_argument("--no-adapt-inset", action="store_true",
                    help="don't auto-shrink the overlay further if Windows still reports a full-screen app")
    ap.add_argument("--no-keep-on-top", action="store_true",
                    help="don't keep re-raising the status box and grid above everything else "
                         "(they are still always-on-top windows)")
    ap.add_argument("--priority", choices=sorted(PRIORITY_CLASSES), default="high",
                    help="Windows process priority (default high). Keeps clicks and speech responsive "
                         "when the PC is busy; 'normal' turns it off")
    ap.add_argument("--admin", action="store_true",
                    help="restart elevated (UAC prompt) so clicks and keys also reach administrator "
                         "windows, which Windows otherwise blocks")
    ap.add_argument("--hide-console", action="store_true",
                    help="hide the console window once started (see the note in the docstring: "
                         "pythonw is the reliable way to run with no console at all)")
    ap.add_argument("--no-media", action="store_true",
                    help="turn off the media-button commands (\"media play\", \"media next\", ...)")
    ap.add_argument("--no-dictation", action="store_true",
                    help="turn off the \"dictate\" command (typing what you say; see voice_dictate.py)")
    ap.add_argument("--dictate-idle", type=float, default=3.0, metavar="SECONDS",
                    help="dictation goes back to listening after this many seconds of silence "
                         "(default 3; 0 = never)")
    ap.add_argument("--preload-dictation", action="store_true",
                    help="load the dictation models at start-up instead of the first time you say "
                         "\"dictate\" (uses memory and CPU for a while at start)")
    ap.add_argument("--draft-model", help="dictation: fast live model (default: voice_dictate's)")
    ap.add_argument("--final-model", help="dictation: accurate model run at each pause")
    ap.add_argument("--no-draft", action="store_true",
                    help="dictation: no live typing, only type each phrase when you pause (least CPU)")
    ap.add_argument("--dictate-device", choices=("cpu", "cuda", "auto"), default="cpu",
                    help="dictation: where the models run (default cpu)")
    ap.add_argument("--dictate-pause-ms", type=int, default=900,
                    help="dictation: silence that ends a phrase (default 900)")
    ap.add_argument("--dictate-prompt", help="dictation: names / jargon to bias a Whisper final model towards")
    ap.add_argument("--dictate-model-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
                    help="dictation: where its models are kept / downloaded (default: ./models)")
    ap.add_argument("--start-awake", action="store_true")
    ap.add_argument("--corner", choices=StatusPill.CORNERS, default="bottom-right",
                    help="screen corner the status box starts in (the arrow button cycles through all four)")
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

    if args.priority != "normal":
        print(f"Process priority: {args.priority}" if set_priority(args.priority)
              else f"Could not set {args.priority} priority; carrying on at normal.")
    if args.admin and not is_admin():
        print("Restarting as administrator (accept the Windows prompt) ...")
        if relaunch_as_admin():
            return
        print("Could not get administrator rights (prompt declined?); carrying on without them.")
    if args.hide_console:
        hide_console()                   # after the start-up checks above, so their errors are still seen

    import tkinter as tk
    make_dpi_aware()
    model_path = ensure_model(args.model)
    log_path = None if args.no_log else os.path.abspath(args.log)

    root = tk.Tk()
    root.withdraw()
    screen = primary_screen()
    pill = StatusPill(root, screen, corner=args.corner)
    overlay = Overlay(root, screen, minor_grid=not args.no_minor_grid, inset=args.overlay_inset,
                      adapt=not args.no_adapt_inset)
    ctl = Controller(screen, WinMouse(), overlay, on_state=pill.set, keyboard=WinKeyboard(),
                     media=None if args.no_media else WinMedia(), on_reload=reload_program,
                     windows=WinWindow())
    if args.start_awake:
        ctl.handle("start")

    cmds: queue.Queue[str] = queue.Queue()
    dictation = None                         # set below; the lambdas only run once it exists
    speech = SpeechThread(model_path, args.device, args.min_conf, lambda: ctl.state, cmds,
                          args.open_vocab, args.word_conf, args.nbest, log_path, args.lenient, args.flat_grammar,
                          early_digits=not args.no_early_digits, media=not args.no_media)

    # ---- dictation: "dictate" types what you say; it returns to listening when you go quiet
    say = lambda text: speech._say(text)
    if args.no_dictation:
        dictation = DictationUnavailable(say, "dictation is turned off (--no-dictation)")
    else:
        d_opts = DictationOptions(
            draft_model=args.draft_model, final_model=args.final_model, no_draft=args.no_draft,
            device=args.dictate_device, model_dir=args.dictate_model_dir, prompt=args.dictate_prompt,
            pause_ms=args.dictate_pause_ms, idle=args.dictate_idle)
        ok, why = dictation_available(d_opts)
        if not ok:
            print(f"note: {why}")
            dictation = DictationUnavailable(say, why)
        else:
            def dictation_idle():
                if ctl.state == DICTATE:
                    say(f"no speech for {args.dictate_idle:g}s - back to listening")
                    ctl.handle("listen")
            dictation = DictationSession(
                d_opts, say, on_idle=dictation_idle, on_stop=lambda: ctl.handle("listen"),
                on_ready=lambda: ctl.handle("dictate"))
            speech.dictation_feed = dictation.feed
            if args.preload_dictation:
                dictation.request(want=False)
    ctl.dictation = dictation
    speech.start()

    def dictation_poll():
        try:
            dictation.poll()
        except Exception as e:
            print(f"dictation error: {e}")
        root.after(15, dictation_poll)

    root.after(15, dictation_poll)

    def meter_poll():
        pill.set_level(speech.level)
        pill.set_heard(speech.last_heard, speech.heard_seq)
        root.after(40, meter_poll)

    root.after(40, meter_poll)

    def keep_on_top():
        overlay.raise_()                    # the grid first ...
        pill.raise_()                       # ... then the status box above it, so it is never hidden
        root.after(250, keep_on_top)

    if not args.no_keep_on_top:
        root.after(250, keep_on_top)

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
