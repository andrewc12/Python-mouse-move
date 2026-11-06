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
  "dictate"                          type what you say into the focused window: a fast draft model
                                     while you talk, corrected by an accurate one at each pause (see
                                     "Dictation engine" below). The status box turns blue and says
                                     Dictating, with a high beep (a low one when it ends).
  Pause after saying "dictate": it must be a phrase of its own. You then have 6 s to start talking
  (--dictate-idle plus --dictate-start-wait), and after that 3 s of silence ends it (--dictate-idle).
  It also ends when you say "stop dictation" or "stop listening" as a phrase of its own. All of these
  go back to listening; the hotkey / box click goes to sleep instead.
  Inside dictation, as whole phrases: "new line", "new paragraph", "scratch that" (deletes the last
  phrase; also "delete that").
  The models load (the first run downloads about 750 MB into the shared models folder, --models-dir) in a
  background thread at start-up, while the mouse and keyboard commands are already usable; the status
  box says when dictation is ready. If you say "dictate" before then, it starts by itself once loaded.
  --lazy-dictation waits until the first "dictate" instead; --no-dictation turns the command off. Needs: pip install sherpa-onnx webrtcvad-wheels numpy
  (requirements.txt). The console prints what dictation hears ("dictation: heard '...'") and, when it
  ends, how many audio frames had speech in them: zero means the microphone / --dictate-vad-level.
  Other knobs: --draft-model / --final-model (a sherpa-onnx or Whisper model name, e.g. small.en),
  --no-draft (only type at pauses; least CPU), --dictate-device cuda, --dictate-pause-ms,
  --dictate-prompt (names to bias Whisper), --dictate-verbose (decode timings).

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
That elevates the whole program, models included. The safer way is to elevate only the small
voice_mouse_hands.py, which does all the clicking, keys and typing and imports nothing but the
standard library: start with --admin-hands (the program starts it elevated if it is not running),
or run voice_mouse_hands.py --admin yourself and start this with --use-hands. The hands keep
running like a server until closed (install_hands_task.bat starts them elevated at every logon, with
no prompt). Speech recognition,
the models and the screen overlay then run as your normal user. Anything running as you can still
read the hands' token file and ask them to press keys, so this limits the elevated code; it does
not make an untrusted program on your account harmless.

No console window: run it with  pythonw voice_mouse.py  (or double-click a .pyw copy) and there is
never a console. --hide-console hides the console after start-up instead; it does not work inside
Windows Terminal (the Windows 11 default), where only the tab can be closed. A compiled build can use
--windows-console-mode=disable (MAIN_CONSOLE in build.bat). With no console, messages go
nowhere; heard.jsonl (--log) still records what was recognised.

Log and crashes: everything the console shows (with time stamps, and any traceback or native crash)
is also written to voice_mouse.log next to the program (--console-log FILE, --no-console-log), so it
is still there with no console or after a crash. The program runs as a small supervisor plus the
real program: if the real one crashes (or its speech thread dies) it is started again after 2 s,
already listening, up to 5 times a minute; Ctrl+C, closing the window and the reload phrase end it for good.
--no-restart runs it as a single process.

Models: never packed into an exe. All of them live in one shared folder (--models-dir, default
%LOCALAPPDATA%\\voice_mouse\\models, or the VOICE_MOUSE_MODELS variable), so every build and copy
reuses the same download. voice_mouse.py --download-models fetches them all and exits.

Build: build.bat makes dist\\voice_mouse_hands.exe and dist\\voice_mouse.exe (two single-file builds).

Run:  python voice_mouse.py            (downloads the ~40 MB model on first run)
      python voice_mouse.py --list-devices
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import math
import os
import queue
import re
import socket
import sys
import threading
import time
import traceback
import urllib.request
import zipfile
from dataclasses import dataclass

from voice_mouse_ui import (   # the grid overlay, status box and screen geometry (Tk, standard library only)
    AWAKE, BUSY_STATES, CORNERS, DICTATE, GRID, MAX_INSET, SLEEPING, Overlay, Region, StatusPill, make_click_through,
    next_inset, notification_state, primary_screen, raise_topmost)
from voice_mouse_hands import (   # the input classes and key tables live in the small elevated-capable file
    MAX_BACKSPACES, MAX_LINE, MAX_TEXT, default_token_file, read_token_file,
    EXTENDED_KEYS, KEYUP, MEDIA_APPCOMMAND, MEDIA_VK, MODIFIER_KEYS, UNICODE, VK, VK_BACK, VK_RETURN,
    WinKeyboard, WinMedia, WinMouse, WinTyper, WinWindow, is_admin, key_events, make_dpi_aware)

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
def self_command() -> list[str]:
    """Command line that starts this program again exactly as it was started."""
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    args, skip = [], False
    for a in sys.argv[1:]:                  # --supervised-by belongs to ONE supervisor: never pass it on
        if skip:
            skip = False
        elif a == "--supervised-by":
            skip = True
        elif not a.startswith("--supervised-by="):
            args.append(a)
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


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------
def default_models_dir() -> str:
    """One folder for every model, shared by all builds and copies of the program: the environment
    variable VOICE_MOUSE_MODELS, else %LOCALAPPDATA%\\voice_mouse\\models. Nothing is packed into the exe."""
    env = os.environ.get("VOICE_MOUSE_MODELS")
    if env:
        return os.path.abspath(env)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "voice_mouse", "models")


def ensure_model(path: str | None, models_dir: str | None = None) -> str:
    """The Vosk model folder: --model if given, else <models dir>/<name>, downloading it on first use.
    A copy in ./models beside the program (where older versions kept it) is used rather than downloaded again."""
    if path:
        return path
    base = models_dir or default_models_dir()
    target = os.path.join(base, MODEL_NAME)
    if os.path.isdir(target):
        return target
    legacy = os.path.join(app_dir(), "models", MODEL_NAME)
    if os.path.isdir(legacy):
        return legacy
    os.makedirs(base, exist_ok=True)
    zip_path = target + ".zip"
    print(f"Downloading speech model (~40 MB) from {MODEL_URL} into {base} ...")
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(base)
    os.remove(zip_path)
    return target


def download_models(models_dir: str, opts: "DictationOptions | None" = None, dictation: bool = True) -> None:
    """Fetch every model the program can use into `models_dir` (what --download-models runs), so a
    build never has to carry them. Whisper models are fetched by faster-whisper the first time they load."""
    print(f"Models folder: {models_dir}")
    print(f"  speech commands: {ensure_model(None, models_dir)}")
    if not dictation:
        return
    opts = opts or DictationOptions()
    for name in dict.fromkeys([opts.draft_model or DEFAULT_DRAFT, opts.final_model or DEFAULT_FINAL]):
        if engine_kind(name) == "whisper":
            print(f"  {name}: downloaded by faster-whisper when first used")
        else:
            print(f"  dictation: {ensure_sherpa_model(name, models_dir)}")
    print("All models are in place.")


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
# Dictation engine: voice activity -> phrases -> draft / final models -> text typed into the focused
# window. While you speak a fast "draft" model keeps guessing and the text on screen is corrected in
# place (backspace the wrong tail, type the better one), like Windows voice typing; at each pause a
# more accurate "final" model re-reads the phrase and fixes it, with punctuation and capitals.
#
#     microphone -> VAD -> utterance Segmenter
#                      |-- every ~0.3 s ----> DRAFT model (small, fast)  -> type / correct on screen
#                      '-- at a pause -------> FINAL model (bigger)      -> final correction, commit
#
# Default engines (offline, through sherpa-onnx; no GPU needed):
#   draft  sherpa-onnx-streaming-zipformer-en-2023-06-26   streaming; lower case, no punctuation
#   final  sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8      NVIDIA Parakeet TDT 0.6B; punctuation + capitals
# A Whisper name (e.g. small.en, via faster-whisper) works for either role. A model name picks the
# engine: "sherpa-onnx-streaming*" = streaming, "sherpa-onnx-nemo*" = Parakeet-style offline, else Whisper.
# Text is only corrected while a phrase is still being decided; once final it is never touched again
# except by "scratch that". If focus moves to another window mid-phrase the old window is abandoned
# (never backspaced into). Typing uses SendInput with Unicode characters; Windows blocks it into
# administrator windows unless this program is elevated (--admin).
# --------------------------------------------------------------------------

FRAME_MS = 30                                   # webrtcvad takes 10, 20 or 30 ms frames


FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2


# ---- cleaning what the model says -------------------------------------------------------------
# Whisper invents these on silence, breaths and keyboard noise.
HALLUCINATIONS = {"you", "thanks for watching", "thank you for watching", "please subscribe",
                  "subtitles by the amara org community"}


def _spoken_words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def squash_repeats(text: str, limit: int = 3) -> str:
    """Whisper sometimes loops ("the the the the ..."): keep at most `limit` of a repeated word."""
    out, run, prev = [], 0, None
    for tok in text.split():
        key = tok.lower().strip(".,!?")
        run = run + 1 if key == prev else 1
        prev = key
        if run <= limit:
            out.append(tok)
    return " ".join(out)


def clean_transcript(text: str) -> str:
    """Tidy one model result; '' means 'nothing worth typing' (noise tags, known hallucinations)."""
    t = " ".join((text or "").split())
    if not t or re.fullmatch(r"[\[(].*[\])]", t):          # [BLANK_AUDIO], (music), ...
        return ""
    if " ".join(_spoken_words(t)) in HALLUCINATIONS:
        return ""
    return squash_repeats(t)


def clean_draft(text: str) -> str:
    """A draft is cleaned the same way, and loses a trailing '.' / ',' / '...' : the model puts one
    on every guess, and it would otherwise be typed and backspaced again on each update."""
    return re.sub(r"[\s.,\u2026]+$", "", clean_transcript(text))


# ---- voice commands ---------------------------------------------------------------------------
DICTATION_COMMANDS: dict[tuple[str, ...], str] = {
    ("new", "line"): "newline", ("newline",): "newline", ("new", "paragraph"): "paragraph",
    ("scratch", "that"): "scratch", ("delete", "that"): "scratch",
    ("stop", "listening"): "stop", ("stop", "dictation"): "stop",
}


def parse_dictation_command(text: str):
    """The command a whole phrase stands for ('newline', 'paragraph', 'scratch', 'stop'), or None."""
    return DICTATION_COMMANDS.get(tuple(_spoken_words(text)))


def is_dictation_command_prefix(text: str) -> bool:
    """Could this (possibly unfinished) phrase still turn out to be a command? Drafts that might be
    are held back rather than typed and then deleted."""
    w = tuple(_spoken_words(text))
    return bool(w) and any(k[:len(w)] == w for k in DICTATION_COMMANDS)


# ---- voice activity -> utterances ---------------------------------------------------------------
class Segmenter:
    """Turns a stream of 30 ms frames plus a speech / not-speech flag per frame into utterances.

    feed() returns events:
      ("start", uid)                       an utterance began (its pre-roll is included)
      ("end", uid, pcm, reason)            it finished; reason: pause / soft / max / flush
      ("cancel", uid)                      too short to be speech; throw it away

    * start: `ring_need` of the last `ring` frames are speech (a single click is not enough).
    * end: `end_silence_ms` of silence. A long phrase is also cut at a shorter pause (`soft_*`) and
      at `max_s` regardless, because the model's cost grows with the length of what it re-reads.
    * a little pre-roll is kept so the first syllable is not clipped, and a little trailing silence.
    """

    def __init__(self, frame_ms: int = FRAME_MS, ring: int = 5, ring_need: int = 3,
                 pre_roll_ms: int = 300, end_silence_ms: int = 600, soft_after_s: float = 6.0,
                 soft_silence_ms: int = 300, max_s: float = 14.0, min_speech_ms: int = 240,
                 tail_keep_ms: int = 150):
        self.frame_ms, self.ring_need = frame_ms, ring_need
        self.end_silence_ms, self.soft_after_s = end_silence_ms, soft_after_s
        self.soft_silence_ms, self.max_s = soft_silence_ms, max_s
        self.min_speech_ms, self.tail_keep = min_speech_ms, tail_keep_ms // frame_ms
        self._ring = collections.deque(maxlen=ring)
        self._pre = collections.deque(maxlen=max(1, pre_roll_ms // frame_ms))
        self.uid = 0
        self.active = False
        self.buf: list[bytes] = []
        self.voiced = self.silent = 0

    @property
    def seconds(self) -> float:
        return len(self.buf) * self.frame_ms / 1000.0

    def snapshot(self) -> bytes:
        return b"".join(self.buf)

    def reset(self) -> None:
        self.active, self.buf, self.voiced, self.silent = False, [], 0, 0
        self._ring.clear()
        self._pre.clear()

    def _begin(self, frames, voiced: int) -> tuple:
        self.uid += 1
        self.active, self.buf, self.voiced, self.silent = True, list(frames), voiced, 0
        return ("start", self.uid)

    def _finish(self, reason: str) -> tuple:
        uid, voiced_ms = self.uid, self.voiced * self.frame_ms
        drop = max(0, self.silent - self.tail_keep)
        buf = self.buf[:len(self.buf) - drop] if drop else self.buf
        self.reset()
        if voiced_ms < self.min_speech_ms:
            return ("cancel", uid)
        return ("end", uid, b"".join(buf), reason)

    def force_end(self) -> list:
        """End the utterance in progress (used when dictation is paused mid-sentence)."""
        return [self._finish("flush")] if self.active else []

    def feed(self, frame: bytes, speech: bool) -> list:
        ev: list = []
        if not self.active:
            self._pre.append(frame)
            self._ring.append(speech)
            if speech and sum(self._ring) >= self.ring_need:
                ev.append(self._begin(self._pre, sum(self._ring)))
                self._pre.clear()
                self._ring.clear()
            return ev
        self.buf.append(frame)
        if speech:
            self.voiced += 1
            self.silent = 0
        else:
            self.silent += 1
        sil_ms = self.silent * self.frame_ms
        if sil_ms >= self.end_silence_ms:
            reason = "pause"
        elif self.seconds >= self.soft_after_s and sil_ms >= self.soft_silence_ms:
            reason = "soft"
        elif self.seconds >= self.max_s:
            reason = "max"
        else:
            return ev
        ev.append(self._finish(reason))
        if reason == "max" and speech:             # still talking: carry straight on, no gap
            ev.append(self._begin([], 0))
        return ev


class Pipeline:
    """VAD thread's brain: frames in; utterance events and decode jobs out.

    out receives ("start", uid) / ("cancel", uid), and ("idle",) once when `idle_s` seconds pass with no
    speech (the owner then pauses dictation). Decode jobs go through submit_draft(uid, pcm)
    (called every `draft_every_s` while someone is speaking, once `draft_after_s` of audio exists;
    pass None to disable drafts) and submit_final(uid, pcm). discard_draft(uid) is called when an
    utterance ends so a stale draft is not decoded after its final.
    """

    def __init__(self, vad, submit_draft, submit_final, out, segmenter=None, draft_after_s: float = 0.45,
                 draft_every_s: float = 0.3, discard_draft=lambda uid: None, clock=time.monotonic,
                 idle_s: float = 0.0):
        self.vad, self.submit_draft, self.submit_final, self.out = vad, submit_draft, submit_final, out
        self.seg = segmenter or Segmenter()
        self.draft_after_s, self.draft_every_s, self.clock = draft_after_s, draft_every_s, clock
        self.discard_draft = discard_draft
        self.idle_s = idle_s                            # 0 = never stop by itself
        self.active = False
        self._last_draft = 0.0
        self._last_speech = clock()

    def set_active(self, on: bool) -> None:
        if self.active and not on:
            self._handle(self.seg.force_end())          # pausing mid-sentence still delivers it
        if on and not self.active:
            self._last_speech = self.clock()            # the silence clock starts now
        self.active = on
        if not on:
            self.seg.reset()

    def _handle(self, events: list) -> None:
        for e in events:
            kind, uid = e[0], e[1]
            if kind == "start":
                self._last_draft = 0.0
                self.out.put(("start", uid))
            elif kind == "cancel":
                self.discard_draft(uid)
                self.out.put(("cancel", uid))
            elif kind == "end":
                self.discard_draft(uid)
                self.submit_final(uid, e[2])

    def feed(self, frame: bytes) -> None:
        if not self.active:
            return
        now = self.clock()
        speech = bool(self.vad(frame))
        if speech or self.seg.active:                   # talking (or mid-phrase): not idle
            self._last_speech = now
        self._handle(self.seg.feed(frame, speech))
        if self.idle_s and now - self._last_speech >= self.idle_s:
            self._last_speech = now                     # one "idle" per quiet spell
            self.out.put(("idle",))
        if self.submit_draft and self.seg.active and self.seg.seconds >= self.draft_after_s:
            now = self.clock()
            if now - self._last_draft >= self.draft_every_s:
                self._last_draft = now
                self.submit_draft(self.seg.uid, self.seg.snapshot())


# ---- the text on screen -------------------------------------------------------------------------
@dataclass
class Part:
    """One utterance's contribution to the text still being decided."""
    uid: int
    text: str = ""
    kind: str = "text"          # text / newline / paragraph / scratch / stop
    final: bool = False

    def shown(self) -> str:
        return {"newline": "\n", "paragraph": "\n\n", "scratch": "", "stop": ""}.get(self.kind, self.text)


def _needs_space(last: str | None, text: str) -> bool:
    return bool(last) and not last.isspace() and last not in "([{" \
        and not text[0].isspace() and text[0] not in ",.;:!?)]}%\u2026"


class Dictator:
    """Keeps the text on screen equal to the best current reading of what was said.

    `parts` are the utterances not yet settled, oldest first; `shown` is exactly what is on screen for
    them. Every draft or final just changes a part and calls _update(), which renders all the parts
    to one string, finds where it first differs from `shown`, and sends the typist "backspace this
    many, then type this". So a late FINAL for an earlier phrase can fix it even though the next
    phrase has already started appearing after it. Settled (final, front-of-queue) parts move to
    `history` and are never edited again, except by "scratch that".

    typist.edit(backspaces, text) types. foreground() returns the active window id: if it changes
    while text is still undecided, the old window is abandoned instead of being backspaced into.
    """
    HISTORY = 50

    def __init__(self, typist, foreground=lambda: 0, on_stop=lambda: None, notice=lambda s: None):
        self.typist, self.foreground, self.on_stop, self.notice = typist, foreground, on_stop, notice
        self.parts: list[Part] = []
        self.shown = ""
        self.history: list[str] = []          # rendered text of settled phrases, newest last
        self.committed_last: str | None = None
        self.ignore_upto = 0                  # utterances at or below this were abandoned
        self._hwnd = None

    # -- events from the pipeline
    def begin(self, uid: int) -> None:
        self._sync_focus()
        if uid > self.ignore_upto and not self._find(uid):
            self.parts.append(Part(uid))

    def draft(self, uid: int, text: str) -> None:
        self._sync_focus()
        part = self._find(uid)
        if not part or part.final or uid <= self.ignore_upto:
            return
        part.text = "" if is_dictation_command_prefix(text) else clean_draft(text)
        self._update()

    def final(self, uid: int, text: str) -> None:
        self._sync_focus()
        part = self._find(uid)
        if not part or uid <= self.ignore_upto:
            return
        cleaned = clean_transcript(text)
        part.kind = parse_dictation_command(cleaned) or "text"
        part.text = "" if part.kind != "text" else cleaned
        part.final = True
        self._update()

    def cancel(self, uid: int) -> None:
        part = self._find(uid)
        if part and not part.final:
            self.parts.remove(part)
            self._update()

    # -- internals
    def _find(self, uid: int):
        return next((p for p in self.parts if p.uid == uid), None)

    def _sync_focus(self) -> None:
        hwnd = self.foreground()
        if self._hwnd is None:
            self._hwnd = hwnd
        elif hwnd != self._hwnd:
            if self.shown and self.parts:                 # undecided text sits in the old window
                self.ignore_upto = max(self.ignore_upto, max(p.uid for p in self.parts))
                self.parts.clear()
                self.notice("window changed")
            self.shown = ""
            self.history.clear()                          # "scratch that" must not reach into it
            self.committed_last = None
            self._hwnd = hwnd

    def _pieces(self) -> list[tuple[Part, str]]:
        out, last = [], self.committed_last
        for p in self.parts:
            t = p.shown()
            if not t:
                out.append((p, ""))
                continue
            out.append((p, (" " if _needs_space(last, t) else "") + t))
            last = t[-1]
        return out

    def _apply(self) -> None:
        target = "".join(piece for _, piece in self._pieces())
        if target == self.shown:
            return
        n = min(len(target), len(self.shown))
        i = 0
        while i < n and target[i] == self.shown[i]:
            i += 1
        self.typist.edit(len(self.shown) - i, target[i:])
        self.shown = target

    def _update(self) -> None:
        for _ in range(500):
            self._apply()
            if not self.parts or not self.parts[0].final:
                return
            front = self.parts[0]
            if front.kind == "stop":
                self.parts.pop(0)
                self.on_stop()
            elif front.kind == "scratch":
                self.parts.pop(0)
                if self.history:                          # un-settle the last phrase; _apply deletes it
                    self.shown = self.history.pop() + self.shown
                    self.committed_last = self.history[-1][-1] if self.history else None
                    self.notice("scratched")
                else:
                    self.notice("nothing to scratch")
            else:
                piece = self._pieces()[0][1]
                self.parts.pop(0)
                if piece:
                    self.history.append(piece)
                    del self.history[:-self.HISTORY]
                    self.committed_last = piece[-1]
                    self.shown = self.shown[len(piece):]


# --------------------------------------------------------------------------
# Windows specifics
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# The hands: input done by a separate, small (optionally elevated) process
# --------------------------------------------------------------------------
class HandsError(RuntimeError):
    """The hands process could not be reached, or refused a request."""


class HandsClient:
    """Sends input requests (plain JSON, one per line) to voice_mouse_hands.py over loopback.
    Each call waits for the reply, so actions happen in the order they were asked for."""

    def __init__(self, token_file: str, timeout: float = 30.0, connect=socket.create_connection):
        self.token_file, self.timeout, self._connect = token_file, timeout, connect
        self.sock = self.rfile = None
        self.admin = self.ui = self.uiaccess = False     # what the hands said about themselves in their hello reply
        self.on_open: list = []               # called after every (re)connect, e.g. to send the UI settings again
        self.lock = threading.RLock()

    def open(self) -> "HandsClient":
        info = read_token_file(self.token_file)
        sock = self._connect(("127.0.0.1", info["port"]), 3)
        sock.settimeout(self.timeout)
        rfile = sock.makefile("rb")
        try:
            sock.sendall((json.dumps({"op": "hello", "token": info["token"]}) + "\n").encode("utf-8"))
            reply = json.loads(rfile.readline(MAX_LINE) or b"{}")
        except Exception:
            sock.close()
            raise
        if not reply.get("ok"):
            sock.close()
            raise HandsError(f"the hands refused the connection ({reply.get('error', 'no reply')})")
        self.sock, self.rfile, self.admin, self.ui = sock, rfile, bool(reply.get("admin")), bool(reply.get("ui"))
        self.uiaccess = bool(reply.get("uiaccess"))
        for hook in list(self.on_open):
            hook()
        return self

    def close(self) -> None:
        for f in (self.rfile, self.sock):
            try:
                f and f.close()
            except OSError:
                pass
        self.sock = self.rfile = None

    def call(self, op: str, **fields) -> dict:
        data = (json.dumps({"op": op, **fields}) + "\n").encode("utf-8")
        with self.lock:
            try:
                if self.sock is None:
                    self.open()
                self.sock.sendall(data)
            except (OSError, ValueError, KeyError):        # not delivered: reconnect once and send again
                self.close()
                try:
                    self.open()
                    self.sock.sendall(data)
                except (OSError, ValueError, KeyError) as e:
                    self.close()
                    raise HandsError(f"cannot reach the hands process: {e}") from e
            try:
                line = self.rfile.readline(MAX_LINE)
            except OSError as e:                           # delivered, reply lost: do NOT send it again
                self.close()
                raise HandsError(f"lost contact with the hands process: {e}") from e
            if not line:
                self.close()
                raise HandsError("the hands process closed the connection")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise HandsError(f"{op}: {reply.get('error', 'refused')}")
        return reply


class RemoteMouse:
    def __init__(self, hands: HandsClient):
        self.hands = hands

    def move(self, x, y) -> None:
        self.hands.call("move", x=int(x), y=int(y))

    def click(self, button: str, double: bool = False) -> None:
        self.hands.call("click", button=button, double=bool(double))

    def scroll(self, direction: str, amount: int) -> None:
        self.hands.call("scroll", direction=direction, amount=int(amount))

    def drag(self, button: str, start, end) -> None:
        self.hands.call("drag", button=button, start=[int(start[0]), int(start[1])],
                        end=[int(end[0]), int(end[1])])


class RemoteKeyboard:
    def __init__(self, hands: HandsClient):
        self.hands = hands

    def press(self, mods, key: str, count: int = 1) -> None:
        self.hands.call("press", mods=list(mods), key=key, count=int(count))

    def hold(self, mods) -> None:
        self.hands.call("hold", mods=list(mods))

    def release(self, mods) -> None:
        self.hands.call("release", mods=list(mods))


class RemoteWindow:
    def __init__(self, hands: HandsClient):
        self.hands = hands

    def act(self, action: str) -> None:
        self.hands.call("window", action=action)


class RemoteMedia:
    def __init__(self, hands: HandsClient):
        self.hands = hands

    def send(self, action: str) -> None:
        self.hands.call("media", action=action)


class RemoteTyper:
    def __init__(self, hands: HandsClient):
        self.hands = hands

    def edit(self, backspaces: int, text: str) -> None:
        while backspaces > MAX_BACKSPACES:                  # the hands cap one request's size
            self.hands.call("edit", backspaces=MAX_BACKSPACES, text="")
            backspaces -= MAX_BACKSPACES
        self.hands.call("edit", backspaces=backspaces, text=text[:MAX_TEXT])
        for i in range(MAX_TEXT, len(text), MAX_TEXT):
            self.hands.call("edit", backspaces=0, text=text[i:i + MAX_TEXT])


class RemoteOverlay:
    """The grid, drawn by the hands process (which may hold the UI-access privilege)."""

    def __init__(self, hands: HandsClient):
        self.hands = hands

    def show(self, r: Region, mark) -> None:
        self.hands.call("overlay_show", region=[r.x, r.y, r.w, r.h], mark=list(mark) if mark else None)

    def hide(self) -> None:
        self.hands.call("overlay_hide")

    def raise_(self) -> None:
        pass                                   # the hands keep their own windows on top


class RemotePill:
    """The status box, drawn by the hands process. State changes go over at once; the level and the
    last-heard phrase are sent together by flush(), once per poll, whose reply also carries clicks."""
    CORNERS = CORNERS

    def __init__(self, hands: HandsClient, corner: str = "bottom-right"):
        self.hands, self.corner = hands, corner
        self.state, self.level, self.heard, self.seq = SLEEPING, 0.0, "", 0
        self.on_click = lambda: None
        self._sent_seq = None
        self._last_error = 0.0

    def set(self, state: str) -> None:
        self.state = state
        self._send(state=state)

    def set_level(self, v: float) -> None:
        self.level = v

    def set_heard(self, text: str, seq: int = 0) -> None:
        self.heard, self.seq = text, seq

    def flush(self) -> None:
        fields = {"level": round(min(1.0, max(0.0, self.level)), 3)}
        if self.seq != self._sent_seq:
            fields.update(heard=self.heard[:300], seq=int(self.seq))
        if self._send(**fields):
            self._sent_seq = self.seq

    def raise_(self) -> None:
        pass

    def _send(self, **fields) -> bool:
        try:
            reply = self.hands.call("pill", **fields)
        except HandsError as e:
            if time.monotonic() - self._last_error > 5:        # say so, but not 25 times a second
                self._last_error = time.monotonic()
                print(f"status box: {e}")
            return False
        for event in reply.get("events", []):
            if event == "click":
                self.on_click()
        return True


def start_remote_ui(hands: HandsClient, corner: str, minor_grid: bool, inset: int, adapt: bool,
                    keep_on_top: bool) -> tuple[RemoteOverlay, RemotePill]:
    """Tell the hands how to draw (now, and again whenever the link is re-made) and return the stand-ins."""
    overlay, pill = RemoteOverlay(hands), RemotePill(hands, corner)

    def configure() -> None:
        hands.call("ui_init", corner=pill.corner, minor_grid=minor_grid, inset=inset, adapt=adapt,
                   keep_on_top=keep_on_top)
        pill._sent_seq = None
        hands.call("pill", state=pill.state)
    configure()
    hands.on_open.append(configure)
    return overlay, pill


def find_hands_exe(here: str) -> str:
    """The hands exe to start: the signed copy installed under Program Files (the only place a UI-access
    program may run from) if there is one, else one beside this program. If none exists, the first
    place looked is returned so the error message names a sensible path."""
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    candidates = [os.path.join(program_files, "VoiceMouse", "hands", "voice_mouse_hands.exe"),
                  os.path.join(here, "hands", "voice_mouse_hands.exe"),
                  os.path.join(here, "voice_mouse_hands.exe")]
    return next((c for c in candidates if os.path.isfile(c)), candidates[0])


def hands_command(token_file: str, idle_exit: float = 0.0) -> list[str]:
    """Command line that starts the hands process (the caller adds elevation). It runs until it is
    closed, like a server; pass idle_exit seconds to make it quit when unused."""
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    here = os.path.dirname(os.path.abspath(sys.argv[0] if frozen else __file__))
    if frozen:
        target = [find_hands_exe(here)]
    else:
        target = [sys.executable, os.path.join(here, "voice_mouse_hands.py")]
    return target + ["--token-file", token_file] + (["--idle-exit", f"{idle_exit:g}"] if idle_exit else [])


def connect_hands(token_file: str, wait: float = 0.0, sleep=time.sleep, clock=time.monotonic,
                  client_factory=HandsClient) -> HandsClient:
    """Connect to a running hands process, retrying for `wait` seconds (it may still be starting,
    or waiting for the UAC prompt to be answered)."""
    deadline = clock() + wait
    while True:
        try:
            return client_factory(token_file).open()
        except HandsError:
            raise
        except (OSError, ValueError, KeyError) as e:
            if clock() >= deadline:
                raise HandsError(f"no hands process found via {token_file} ({e}). Start it with "
                                 f"voice_mouse_hands.py --admin, or use --admin-hands") from e
            sleep(0.25)


def launch_hands_admin(token_file: str, wait: float = 60.0) -> HandsClient:
    """Use a hands process that is already running; if there is none, start one elevated (UAC
    prompt) and connect to it. Reusing one means a reload or a crash restart never asks again."""
    try:
        return connect_hands(token_file)
    except HandsError:
        pass
    import ctypes
    import subprocess
    exe, *args = hands_command(token_file)
    print("Starting the input helper as administrator (accept the Windows prompt) ...")
    if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), None, 1) <= 32:
        raise HandsError("could not start the hands as administrator (prompt declined?)")
    return connect_hands(token_file, wait=wait)


def foreground_window() -> int:
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    return u.GetForegroundWindow() or 0


# --------------------------------------------------------------------------
# Speech: VAD, models, workers, microphone
# --------------------------------------------------------------------------
def make_vad(level: int):
    """frame bytes -> is it speech? webrtcvad if installed, else a plain loudness threshold."""
    try:
        import webrtcvad
        v = webrtcvad.Vad(level)
        return lambda frame: v.is_speech(frame, SAMPLE_RATE)
    except ImportError:
        print("webrtcvad not installed (pip install webrtcvad-wheels); using a loudness threshold")
        return lambda frame: level_from_pcm(frame) > 0.35


class WhisperTranscriber:
    """pcm16 mono 16 kHz bytes -> cleaned text, with faster-whisper."""

    def __init__(self, name: str, threads: int, beam: int, device: str = "cpu", compute: str = "int8",
                 language: str | None = "en", prompt: str | None = None, model_dir: str | None = None):
        self.name, self.threads, self.beam, self.device, self.compute = name, threads, beam, device, compute
        self.language, self.prompt, self.model_dir = language, prompt, model_dir
        self.model = None

    def load(self) -> "WhisperTranscriber":
        from faster_whisper import WhisperModel
        self.model = WhisperModel(self.name, device=self.device, compute_type=self.compute,
                                  cpu_threads=self.threads, download_root=self.model_dir)
        return self

    def __call__(self, pcm: bytes, uid=None) -> str:
        import numpy as np
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=self.language, beam_size=self.beam, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True, vad_filter=False,
            initial_prompt=self.prompt)
        keep = [s.text for s in segments if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        return clean_transcript("".join(keep))


# ---- sherpa-onnx engines ------------------------------------------------------------------------
SHERPA_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{}.tar.bz2"


DEFAULT_DRAFT = "sherpa-onnx-streaming-zipformer-en-2023-06-26"


DEFAULT_FINAL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"


def engine_kind(name: str) -> str:
    """Which engine a model name belongs to: 'stream', 'nemo' or 'whisper'."""
    if name.startswith("sherpa-onnx-streaming"):
        return "stream"
    if name.startswith("sherpa-onnx-nemo"):
        return "nemo"
    return "whisper"


def find_model_files(d: str) -> dict:
    """encoder / decoder / joiner / tokens inside an unpacked sherpa-onnx transducer model folder.
    The int8 files are preferred (smaller and faster on a CPU) when both kinds are present."""
    files = os.listdir(d)

    def pick(prefix: str) -> str:
        found = sorted((f for f in files if f.startswith(prefix) and f.endswith(".onnx")),
                       key=lambda f: ("int8" not in f, len(f), f))
        if not found:
            raise FileNotFoundError(f"no {prefix}*.onnx in {d}")
        return os.path.join(d, found[0])

    tokens = os.path.join(d, "tokens.txt")
    if not os.path.isfile(tokens):
        raise FileNotFoundError(f"no tokens.txt in {d}")
    return {"encoder": pick("encoder"), "decoder": pick("decoder"), "joiner": pick("joiner"),
            "tokens": tokens}


def ensure_sherpa_model(name: str, model_dir: str) -> str:
    """Folder of the named sherpa-onnx model, downloading and unpacking it on first use."""
    import tarfile
    target = os.path.join(model_dir, name)
    if os.path.isdir(target):
        return target
    os.makedirs(model_dir, exist_ok=True)
    archive = target + ".tar.bz2"
    url = SHERPA_RELEASE.format(name)
    print(f"Downloading {name} from {url} ...")
    urllib.request.urlretrieve(url, archive)
    with tarfile.open(archive, "r:bz2") as tf:
        root = os.path.realpath(model_dir)
        for m in tf.getmembers():                           # refuse paths that escape the folder
            if not os.path.realpath(os.path.join(model_dir, m.name)).startswith(root + os.sep):
                raise RuntimeError(f"unsafe path in archive: {m.name}")
        tf.extractall(model_dir)
    os.remove(archive)
    if not os.path.isdir(target):
        raise RuntimeError(f"{archive} did not unpack to {target}")
    return target


def _pcm_to_float(pcm: bytes):
    import numpy as np
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def _result_text(result) -> str:
    return result if isinstance(result, str) else getattr(result, "text", "")


class SherpaStreaming:
    """Streaming recogniser as the DRAFT stage.

    One recogniser stream is kept per phrase and each call feeds it only the audio that arrived since
    the last call, so the work per update stays the same however long the phrase gets (the model's
    state carries the earlier words along). A new phrase, or a snapshot that is shorter than what was
    already fed, starts a fresh stream. The text lags the audio by a fraction of a second (the model
    needs a little right-hand context), which is fine for a draft: the final pass has the last word.
    Output is lower-cased; the final pass supplies the capitals and punctuation."""

    def __init__(self, name: str, threads: int, device: str = "cpu", model_dir: str | None = None):
        self.name, self.threads, self.device, self.model_dir = name, threads, device, model_dir
        self.model = None
        self._uid, self._stream, self._fed = None, None, 0       # bytes of the phrase already fed

    def load(self) -> "SherpaStreaming":
        import sherpa_onnx
        f = find_model_files(ensure_sherpa_model(self.name, self.model_dir or "models"))
        self.model = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=f["tokens"], encoder=f["encoder"], decoder=f["decoder"], joiner=f["joiner"],
            num_threads=self.threads, sample_rate=SAMPLE_RATE, feature_dim=80,
            decoding_method="greedy_search", provider="cuda" if self.device == "cuda" else "cpu")
        return self

    def __call__(self, pcm: bytes, uid=None) -> str:
        rec = self.model
        if self._stream is None or uid is None or uid != self._uid or len(pcm) < self._fed:
            self._stream, self._uid, self._fed = rec.create_stream(), uid, 0
        new = pcm[self._fed:len(pcm) // 2 * 2]
        if new:
            self._stream.accept_waveform(SAMPLE_RATE, _pcm_to_float(new))
            self._fed += len(new)
        while rec.is_ready(self._stream):
            rec.decode_stream(self._stream)
        return clean_transcript(_result_text(rec.get_result(self._stream)).lower())


class SherpaNemo:
    """Offline NeMo transducer (Parakeet) as the FINAL stage: whole phrase in, punctuated text out."""

    def __init__(self, name: str, threads: int, device: str = "cpu", model_dir: str | None = None):
        self.name, self.threads, self.device, self.model_dir = name, threads, device, model_dir
        self.model = None

    def load(self) -> "SherpaNemo":
        import sherpa_onnx
        f = find_model_files(ensure_sherpa_model(self.name, self.model_dir or "models"))
        kw = dict(tokens=f["tokens"], encoder=f["encoder"], decoder=f["decoder"], joiner=f["joiner"],
                  num_threads=self.threads, sample_rate=SAMPLE_RATE, feature_dim=128,
                  decoding_method="greedy_search", provider="cuda" if self.device == "cuda" else "cpu")
        try:
            self.model = sherpa_onnx.OfflineRecognizer.from_transducer(model_type="nemo_transducer", **kw)
        except TypeError:                                  # an older build without the model_type argument
            self.model = sherpa_onnx.OfflineRecognizer.from_transducer(**kw)
        return self

    def __call__(self, pcm: bytes, uid=None) -> str:
        stream = self.model.create_stream()
        stream.accept_waveform(SAMPLE_RATE, _pcm_to_float(pcm))
        self.model.decode_stream(stream)
        return clean_transcript(_result_text(stream.result))


def make_transcriber(name: str, threads: int, beam: int, args, prompt=None):
    """The right engine object for a model name (not loaded yet; call .load())."""
    kind = engine_kind(name)
    if kind == "stream":
        return SherpaStreaming(name, threads, args.device, args.model_dir)
    if kind == "nemo":
        return SherpaNemo(name, threads, args.device, args.model_dir)
    return WhisperTranscriber(name, threads, beam, args.device, args.compute_type or "int8",
                              args.language, prompt, args.model_dir)


class LatestWorker(threading.Thread):
    """Runs fn(job) on the newest submitted job only: if jobs arrive faster than fn finishes, the
    ones in between are dropped (a draft that is already out of date is not worth decoding)."""

    def __init__(self, fn, name="draft"):
        super().__init__(daemon=True, name=name)
        self.fn, self.cv, self.job = fn, threading.Condition(), None

    def submit(self, job) -> None:
        with self.cv:
            self.job = job
            self.cv.notify()

    def discard(self, uid) -> None:
        with self.cv:
            if self.job and self.job[0] == uid:
                self.job = None

    def run(self) -> None:
        while True:
            with self.cv:
                while self.job is None:
                    self.cv.wait()
                job, self.job = self.job, None
            try:
                self.fn(job)
            except Exception:
                traceback.print_exc()


class FifoWorker(threading.Thread):
    """Runs fn(job) for every job, in order."""

    def __init__(self, fn, name="final"):
        super().__init__(daemon=True, name=name)
        self.fn, self.q = fn, queue.Queue()

    def submit(self, job) -> None:
        self.q.put(job)

    def run(self) -> None:
        while True:
            job = self.q.get()
            try:
                self.fn(job)
            except Exception:
                traceback.print_exc()


# --------------------------------------------------------------------------
# Dictation ("dictate"): connecting the engine to voice_mouse. While it is on, the microphone audio
# goes to the engine instead of Vosk; it hands control back to listening when you stop talking.
# --------------------------------------------------------------------------
@dataclass
class DictationOptions:
    draft_model: str | None = None        # None = DEFAULT_DRAFT
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
    start_wait: float = 3.0               # extra seconds allowed before the FIRST words (the command
                                          # that started dictation, and any model loading, lag behind you)
    verbose: bool = False


def dictation_available(opts: DictationOptions) -> tuple[bool, str]:
    """Are the packages the chosen dictation models need installed? (ok, message if not)"""
    try:
        import numpy, sounddevice  # noqa: F401
        names = [opts.final_model or DEFAULT_FINAL] + ([] if opts.no_draft else [opts.draft_model or DEFAULT_DRAFT])
        if any(engine_kind(n) == "whisper" for n in names):
            import faster_whisper  # noqa: F401
        if any(engine_kind(n) != "whisper" for n in names):
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
    speech thread. The engine above does the actual work; this class connects it to voice_mouse.
    """

    def __init__(self, opts: DictationOptions, say, on_idle, on_stop, on_ready, typist=None,
                 foreground=None, vad=None, load=None, clock=time.monotonic):
        self.opts, self.say = opts, say
        self.on_idle, self.on_stop, self.on_ready = on_idle, on_stop, on_ready
        self.draft_tr = self.final_tr = None
        self._loader = load or self._load_models
        self._ready = threading.Event()
        self._loading = False
        self.wanted = False                     # "dictate" was said while the models were loading
        self._lock = threading.Lock()           # speech thread feeds, UI thread starts / stops
        self.out: queue.Queue = queue.Queue()
        self.reframer = Reframer(FRAME_BYTES)
        self.draft_worker = None if opts.no_draft else LatestWorker(self._run_draft)
        self.final_worker = FifoWorker(self._run_final)
        self.final_worker.start()
        if self.draft_worker:
            self.draft_worker.start()
        base_vad = vad or make_vad(opts.vad_level)
        self.stats = {"frames": 0, "speech": 0, "phrases": 0}     # what the microphone gave us this time

        def counting_vad(frame):
            heard = bool(base_vad(frame))
            self.stats["frames"] += 1
            self.stats["speech"] += heard
            return heard
        self._load_started = self._last_note = 0.0
        self.pipeline = Pipeline(
            counting_vad,
            (lambda uid, pcm: self.draft_worker.submit((uid, pcm))) if self.draft_worker else None,
            lambda uid, pcm: self.final_worker.submit((uid, pcm)), self.out,
            Segmenter(end_silence_ms=opts.pause_ms, soft_after_s=opts.long_after,
                         soft_silence_ms=min(opts.long_pause_ms, opts.pause_ms), max_s=opts.max_phrase),
            draft_every_s=opts.draft_interval,
            discard_draft=self.draft_worker.discard if self.draft_worker else (lambda uid: None),
            idle_s=opts.idle, clock=clock)
        self.dictator = Dictator(typist or WinTyper(), foreground or foreground_window,
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
        self._load_started = self._last_note = time.monotonic()
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
        o = self.opts
        cores = os.cpu_count() or 4
        if o.no_draft:
            dthreads, fthreads = 0, o.final_threads or cores
        else:
            dthreads = o.draft_threads or max(1, cores // 2)
            fthreads = o.final_threads or max(1, cores - dthreads)
        from types import SimpleNamespace
        args = SimpleNamespace(device=o.device, model_dir=o.model_dir, compute_type=o.compute_type,
                               language=o.language)
        final = make_transcriber(o.final_model or DEFAULT_FINAL, fthreads, o.beam, args, o.prompt)
        draft = None if o.no_draft else make_transcriber(o.draft_model or DEFAULT_DRAFT, dthreads, 1, args)
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
            self.stats.update(frames=0, speech=0, phrases=0)
            idle = self.opts.idle
            self.pipeline.idle_s = idle + self.opts.start_wait if idle else 0.0   # until the first words
            self.pipeline.set_active(True)              # the idle clock starts now
        wait = f" ({idle + self.opts.start_wait:g}s to start, then {idle:g}s of silence ends it)" if idle else ""
        print(f"dictation: listening{wait}")

    def stop(self) -> None:
        with self._lock:
            self.pipeline.set_active(False)
        s = self.stats
        print(f"dictation: ended - {s['frames']} audio frames, {s['speech']} with speech, {s['phrases']} phrases")

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
                    s = self.stats
                    self.say("dictation heard no speech (is the microphone level too low?) - back to listening"
                             if not s["speech"] else
                             f"no speech for {self.opts.idle:g}s - back to listening")
                    self.on_idle()
                else:
                    if ev[0] == "start":
                        self.stats["phrases"] += 1
                        self.pipeline.idle_s = self.opts.idle        # the first words arrived: normal timeout
                        print("dictation: speech detected")
                    elif ev[0] == "final":
                        print(f"dictation: heard {ev[2]!r}")
                    handlers[ev[0]](*ev[1:])
            except Exception:
                traceback.print_exc()
        if self._loading and time.monotonic() - self._last_note >= 5.0:
            self._last_note = time.monotonic()
            self.say(f"still loading dictation models ... {time.monotonic() - self._load_started:.0f}s")
        if self.wanted and self.ready:
            self.wanted = False
            self.on_ready()


# --------------------------------------------------------------------------
# Running unattended: a log file with everything the console shows, and a supervisor that restarts
# the program if it crashes.
# --------------------------------------------------------------------------
def app_dir() -> str:
    frozen = "__compiled__" in globals() or getattr(sys, "frozen", False)
    return os.path.dirname(os.path.abspath(sys.argv[0] if frozen else __file__))


class Tee:
    """A stand-in for sys.stdout / sys.stderr that also writes every line, with a time stamp, to a
    log file. The original stream may be None (pythonw has no console): then only the file gets it."""

    def __init__(self, stream, fh, tag: str = ""):
        self.stream, self.fh, self.tag, self._buf = stream, fh, tag, ""

    def write(self, text) -> int:
        text = str(text)
        if self.stream is not None:
            try:
                self.stream.write(text)
            except Exception:
                pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._emit(line)
        return len(text)

    def _emit(self, line: str) -> None:
        try:                                 # one write per line, so two processes rarely interleave
            self.fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.tag}{line}\n")
            self.fh.flush()
        except Exception:
            pass

    def flush(self) -> None:
        if self._buf:                        # a partial line is still worth keeping
            line, self._buf = self._buf, ""
            self._emit(line)
        if self.stream is not None:
            try:
                self.stream.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return bool(self.stream is not None and getattr(self.stream, "isatty", lambda: False)())

    def __getattr__(self, name):             # encoding, fileno, ... come from the real stream
        if self.stream is None:
            raise AttributeError(name)
        return getattr(self.stream, name)


def rotate_log(path: str, max_bytes: int = 5_000_000) -> None:
    """Keep the log from growing for ever: past max_bytes it becomes <path>.1 (one old copy is kept)."""
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except OSError:
        pass


def start_console_log(path: str, rotate: bool = True):
    """Copy everything printed (and every traceback) to `path`, from now on. Also records native
    crashes (a segfault inside a library), which Python cannot otherwise print. Returns the file."""
    if rotate:
        rotate_log(path)
    fh = open(path, "a", encoding="utf-8", errors="replace")
    sys.stdout = Tee(sys.stdout, fh)
    sys.stderr = Tee(sys.stderr, fh, "[err] ")
    try:
        import faulthandler
        faulthandler.enable(fh)
    except Exception:
        pass
    print(f"==== voice_mouse started (pid {os.getpid()}): {' '.join(sys.argv)}")
    return fh


def install_crash_hooks(exit=os._exit) -> None:
    """If the speech thread dies the program is deaf but looks alive: stop it with a failure code so
    the supervisor restarts it. (Any other thread's traceback is just printed, as usual.)"""
    def hook(args) -> None:
        print(f"Exception in thread {getattr(args.thread, 'name', '?')}:", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)   # to the log too
        if isinstance(args.thread, SpeechThread):
            print("fatal: the speech thread died; exiting so it can be restarted")
            exit(1)
    threading.excepthook = hook
    return hook


def parent_alive(pid: int) -> bool:
    """Is process `pid` still running?"""
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x00100000, False, pid)            # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102     # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def watch_parent(pid: int, interval: float = 2.0, gone=lambda: os._exit(0)) -> threading.Thread:
    """In the supervised program: if the supervisor goes away (closed, killed) quit too, instead of
    carrying on as an orphan that nothing can restart or stop."""
    def run() -> None:
        while parent_alive(pid):
            time.sleep(interval)
        gone()
    t = threading.Thread(target=run, daemon=True, name="parent-watch")
    t.start()
    return t


def restart_command(cmd: list[str], restarted: bool) -> list[str]:
    """The command for one launch: after a crash the program comes back already listening (it was
    almost certainly in use), instead of asleep waiting for "start listening"."""
    return cmd + ["--start-awake"] if restarted and "--start-awake" not in cmd else list(cmd)


def supervise(launch=None, max_crashes: int = 5, window: float = 60.0, delay: float = 2.0,
              sleep=time.sleep, clock=time.monotonic) -> int:
    """Run the program as a child process and start it again whenever it crashes (exit code other
    than 0). A normal exit (0: Ctrl+C, the reload phrase) is final. More than `max_crashes` crashes
    within `window` seconds means something is badly wrong, so it stops instead of looping."""
    import subprocess
    cmd = [*("--use-hands" if a == "--admin-hands" else a for a in self_command()),   # hands already running
           "--supervised-by", str(os.getpid())]
    launches = [0]

    def run_child() -> int:
        launches[0] += 1
        return subprocess.run(restart_command(cmd, launches[0] > 1)).returncode
    launch = launch or run_child
    crashes: list[float] = []
    print(f"supervisor: starting (pid {os.getpid()}); it restarts the program if it crashes")
    while True:
        try:
            code = launch()
        except KeyboardInterrupt:
            return 0
        if code == 0:
            print("supervisor: the program exited normally")
            return 0
        now = clock()
        crashes = [t for t in crashes if now - t < window] + [now]
        if len(crashes) > max_crashes:
            print(f"supervisor: {len(crashes)} crashes within {window:g}s (last exit code {code}); giving up")
            return code
        print(f"supervisor: the program crashed (exit code {code}); restarting in {delay:g}s "
              f"[{len(crashes)}/{max_crashes} recent crashes]")
        sleep(delay)


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
    ap.add_argument("--use-hands", action="store_true",
                    help="send all clicks, keys and typing to a separate voice_mouse_hands.py process "
                         "(which may run as administrator) instead of doing them here")
    ap.add_argument("--admin-hands", action="store_true",
                    help="start voice_mouse_hands.py elevated (UAC prompt) if it is not already running, "
                         "and use it. Only that small file is elevated; this program and its models are not")
    ap.add_argument("--local-ui", action="store_true",
                    help="with --use-hands: draw the grid and status box in this program instead of in the "
                         "hands (they are drawn by the hands, which can hold the UI-access privilege, when "
                         "the hands support it)")
    ap.add_argument("--hands-file", default=default_token_file(), metavar="FILE",
                    help="where the hands process publishes its port and token (default: %(default)s)")
    ap.add_argument("--hide-console", action="store_true",
                    help="hide the console window once started (see the note in the docstring: "
                         "pythonw is the reliable way to run with no console at all)")
    ap.add_argument("--no-media", action="store_true",
                    help="turn off the media-button commands (\"media play\", \"media next\", ...)")
    ap.add_argument("--no-dictation", action="store_true",
                    help="turn off the \"dictate\" command (typing what you say)")
    ap.add_argument("--dictate-idle", type=float, default=3.0, metavar="SECONDS",
                    help="dictation goes back to listening after this many seconds of silence "
                         "(default 3; 0 = never)")
    ap.add_argument("--dictate-start-wait", type=float, default=3.0, metavar="SECONDS",
                    help="extra time allowed before your first words, on top of --dictate-idle (default 3), "
                         "because the \"dictate\" command and any model loading lag a little behind you")
    ap.add_argument("--dictate-vad-level", type=int, choices=(0, 1, 2, 3), default=2,
                    help="dictation voice-activity strictness: 3 ignores more noise, 0 hears more (default 2; "
                         "try 0 or 1 if it does not pick up quiet speech)")
    ap.add_argument("--dictate-verbose", action="store_true",
                    help="print every dictation decode with its timing")
    ap.add_argument("--lazy-dictation", action="store_true",
                    help="don't load the dictation models at start-up; wait until the first time you "
                         "say \"dictate\" (saves memory and start-up CPU, but that first use is slow, "
                         "and the very first run downloads about 750 MB)")
    ap.add_argument("--draft-model", help=f"dictation: fast live model (default {DEFAULT_DRAFT})")
    ap.add_argument("--final-model", help=f"dictation: accurate model run at each pause (default {DEFAULT_FINAL})")
    ap.add_argument("--no-draft", action="store_true",
                    help="dictation: no live typing, only type each phrase when you pause (least CPU)")
    ap.add_argument("--dictate-device", choices=("cpu", "cuda", "auto"), default="cpu",
                    help="dictation: where the models run (default cpu)")
    ap.add_argument("--dictate-pause-ms", type=int, default=900,
                    help="dictation: silence that ends a phrase (default 900)")
    ap.add_argument("--dictate-prompt", help="dictation: names / jargon to bias a Whisper final model towards")
    ap.add_argument("--models-dir", default=default_models_dir(), metavar="DIR",
                    help="where ALL models are kept and downloaded, shared by every build (default: %(default)s; "
                         "or set VOICE_MOUSE_MODELS). They are never packed into the exe")
    ap.add_argument("--download-models", action="store_true",
                    help="download every model into --models-dir, then exit (run it once after building)")
    ap.add_argument("--dictate-model-dir", default=None, metavar="DIR",
                    help="dictation: use this folder for its models instead of --models-dir")
    ap.add_argument("--console-log", metavar="FILE", default=os.path.join(app_dir(), "voice_mouse.log"),
                    help="write everything the console shows, with time stamps and any crash, to FILE "
                         "(default: voice_mouse.log next to the program; kept to about 5 MB + one old copy)")
    ap.add_argument("--no-console-log", action="store_true", help="don't write the console log file")
    ap.add_argument("--no-restart", action="store_true",
                    help="don't restart the program automatically if it crashes")
    ap.add_argument("--supervised-by", type=int, help=argparse.SUPPRESS)
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
    if args.download_models:
        download_models(args.models_dir, DictationOptions(draft_model=args.draft_model, final_model=args.final_model,
                                                          no_draft=args.no_draft), dictation=not args.no_dictation)
        return
    if sys.platform != "win32":
        sys.exit("This tool controls the Windows mouse; run it on Windows.")

    if not args.no_console_log:
        try:
            start_console_log(args.console_log, rotate=not args.supervised_by)
        except OSError as e:
            print(f"warning: cannot write the console log {args.console_log}: {e}")
    install_crash_hooks()

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
    hands = None
    if args.admin_hands and not args.supervised_by:       # once, in the outermost process: restarts reuse it
        try:
            hands = launch_hands_admin(args.hands_file)
        except HandsError as e:
            sys.exit(f"Could not start the elevated input helper: {e}")
        args.use_hands = True
        if not args.no_restart:                           # the supervisor only needed to know it works
            hands.close()
            hands = None
    if args.hide_console:
        hide_console()                   # after the start-up checks above, so their errors are still seen
    if args.supervised_by:               # we are the child: follow the supervisor out
        watch_parent(args.supervised_by)
    elif not args.no_restart:            # we are the supervisor: run the real program and restart it
        sys.exit(supervise())

    import tkinter as tk
    make_dpi_aware()
    model_path = ensure_model(args.model, args.models_dir)
    log_path = None if args.no_log else os.path.abspath(args.log)

    root = tk.Tk()
    root.withdraw()
    if args.use_hands:
        try:
            hands = hands or connect_hands(args.hands_file, wait=20.0)
        except HandsError as e:
            sys.exit(f"Could not reach the input helper: {e}")
        print(f"Input goes through the hands process ({'administrator' if hands.admin else 'NOT elevated'}"
              f"{', UI access' if hands.uiaccess else ''}).")
        if not hands.admin and not hands.uiaccess:
            print("note: it is neither elevated nor has UI access, so administrator windows still ignore clicks "
                  "and keys (run install_hands_signed.bat)")
        mouse, keyboard, window, media_dev, typer = (RemoteMouse(hands), RemoteKeyboard(hands),
                                                     RemoteWindow(hands), RemoteMedia(hands), RemoteTyper(hands))
    else:
        mouse, keyboard, window, media_dev, typer = WinMouse(), WinKeyboard(), WinWindow(), WinMedia(), None
    screen = primary_screen()
    if hands is not None and hands.ui and not args.local_ui:
        overlay, pill = start_remote_ui(hands, args.corner, not args.no_minor_grid, args.overlay_inset,
                                        not args.no_adapt_inset, not args.no_keep_on_top)
        print("The grid and status box are drawn by the hands process "
              f"({'with' if hands.uiaccess else 'WITHOUT'} UI access"
              + ("" if hands.uiaccess else "; run install_hands_signed.bat to get the top layer") + ").")
    else:
        pill = StatusPill(root, screen, corner=args.corner)
        overlay = Overlay(root, screen, minor_grid=not args.no_minor_grid, inset=args.overlay_inset,
                          adapt=not args.no_adapt_inset)
    import winsound
    last_state = [SLEEPING]

    def on_state(state: str) -> None:
        pill.set(state)
        was, last_state[0] = last_state[0], state
        if state == DICTATE or (was == DICTATE and state == AWAKE):   # a beep marks each way round
            threading.Thread(target=winsound.Beep, args=(1300 if state == DICTATE else 700, 70),
                             daemon=True).start()

    ctl = Controller(screen, mouse, overlay, on_state=on_state, keyboard=keyboard,
                     media=None if args.no_media else media_dev, on_reload=reload_program,
                     windows=window)
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
            device=args.dictate_device, model_dir=args.dictate_model_dir or args.models_dir, prompt=args.dictate_prompt,
            pause_ms=args.dictate_pause_ms, idle=args.dictate_idle, start_wait=args.dictate_start_wait,
            vad_level=args.dictate_vad_level, verbose=args.dictate_verbose)
        ok, why = dictation_available(d_opts)
        if not ok:
            print(f"note: {why}")
            dictation = DictationUnavailable(say, why)
        else:
            dictation = DictationSession(
                d_opts, say, on_idle=lambda: ctl.handle("listen"), on_stop=lambda: ctl.handle("listen"),
                on_ready=lambda: ctl.handle("dictate"), typist=typer)
            speech.dictation_feed = dictation.feed
            if not args.lazy_dictation:           # load (first run: download) in the background now,
                dictation.request(want=False)     # so "dictate" works at once; Vosk starts meanwhile
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
        if hasattr(pill, "flush"):
            pill.flush()                    # remote status box: send the level and phrase in one message
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
