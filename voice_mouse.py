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

Keyboard (awake only; ignored while the mouse grid is open)
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
  multi-word keys: "back space" (or "backspace"), "space bar", "caps lock", "print screen",
              "left arrow" / "right arrow" / "up arrow" / "down arrow"
  punctuation: "question mark", "exclamation mark", "colon", "quote", "single quote", "apostrophe",
              "open/close bracket", "open/close brace", "open/close paren", "underscore", "hyphen",
              "plus", "asterisk", "at sign", "hash", "dollar sign", "percent", "caret", "ampersand",
              "tilde", "back tick", "pipe", "less than", "greater than"  (US/Australian layout)
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

How recognition is kept tidy (the "page delta" problem): (1) the recogniser's vocabulary comes from
the BNF-style grammar in this file, with a separate grammar per state (asleep / awake / grid);
(2) every result is then checked strictly against the same rules and ignored unless it is a
complete, well-ordered command for the current state ("page" only before up/down, a count only
after a key, grid words only in the grid ...); (3) with --nbest the best-ranked alternative that
passes the check wins. --lenient restores the old skip-stray-words behaviour.

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
    "lbracket": 0xDB, "rbracket": 0xDD, "quote": 0xDE, "backtick": 0xC0,
    "capslock": 0x14, "printscreen": 0x2C,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
})
EXTENDED_KEYS = {"delete", "insert", "home", "end", "pageup", "pagedown",
                 "left", "up", "right", "down", "win", "printscreen"}

# Multi-word and punctuation key names: spoken phrase -> (extra modifiers, key). Symbols that need
# Shift are Shift + the key that carries them on a US layout (the Australian layout is the same).
# Vosk often hears "backspace" as "back space", so both work.
SYMBOL_KEYS: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {
    ("back", "space"): ((), "backspace"), ("space", "bar"): ((), "space"),
    ("caps", "lock"): ((), "capslock"), ("print", "screen"): ((), "printscreen"),
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
              | {"press", "times", "function", "page", "hundred", "click", "scroll"}
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


def build_command_grammar(mode: str = "any") -> _G:
    """The grammar as word-order rules, one per state.

    mode "any"  : every command anywhere (state-blind).
    mode "grid" : what can be said while the mouse grid is open.
    mode "awake": what can be said when awake and NOT in the grid. Clicks, page, scroll, press and
                  "mouse grid" start an utterance; the grid-only words (1-9, back, mark, cancel,
                  move mouse) are legal only after "mouse grid" in the same breath.
    It mirrors ALLOWED / next_state() below, and a test keeps the two in step.
    """
    units19 = [w for w, v in UNITS.items() if 1 <= v <= 9]
    digit_words = [w for w, v in UNITS.items() if v < 10]
    tens_part = _seq(_words(TENS), _opt(_words(units19)))
    number = _alt(_words(UNITS), tens_part,
                  _seq(_words(units19), _W("hundred"), _opt(_alt(_words(UNITS), tens_part))))
    count = _seq(number, _opt(_W("times")))
    mods = _words(MODIFIERS)
    key = _alt(_words(set(LETTER_WORDS) | set(SPOKEN_KEYS) | set(digit_words)),
               _seq(_W("page"), _words(["up", "down"])),
               _seq(_W("function"), _words(units19 + ["ten", "eleven", "twelve"])),
               *[_phrase(" ".join(k)) for k in SYMBOL_KEYS])
    key_item = _alt(_seq(_opt(_plus(mods)), key), _plus(mods))
    press = _seq(_W("press"), _plus(_seq(key_item, _opt(count))))
    page = _seq(_W("page"), _words(["up", "down"]), _opt(count))
    scroll = _seq(_W("scroll"), _words(["up", "down", "left", "right"]), _opt(count))
    clicks = _alt(*[_phrase(p) for p in ("left click", "right click", "double click")],
                  _words(["click", "left", "right", "double"]))
    grid_only = _alt(_phrase("move mouse"), _words(["move", "mark", "back", "cancel"] + list(NUMBER_WORDS)))
    stop, mouse_grid = _phrase("stop listening"), _phrase("mouse grid")
    common = [page, scroll, press, clicks, mouse_grid, stop]
    if mode == "any":
        return _plus(_alt(_phrase("start listening"), *common, grid_only))
    if mode == "grid":
        return _plus(_alt(*common, grid_only))
    if mode == "awake":
        in_grid = _alt(*common, grid_only)              # after "mouse grid" anything may follow
        return _plus(_alt(page, scroll, press, clicks, stop,
                          _seq(mouse_grid, _opt(_plus(in_grid)))))
    raise ValueError(mode)


_CLICKS = ["left click", "right click", "double click", "click"]
_COMMON_EXAMPLES = ["mouse grid", "page down", "page up", "scroll down", "scroll up",
                    "page down five", "scroll down ten times", "press tab", "press enter",
                    "press control c", "press down twenty", "press back space", "press question mark",
                    "press left arrow", "stop listening"] + _CLICKS
BASE_EXAMPLES = _COMMON_EXAMPLES + ["move mouse", "mark", "back", "cancel", "start listening"] + list(NUMBER_WORDS)
GRID_BASE_EXAMPLES = [e for e in BASE_EXAMPLES if e != "start listening"]
AWAKE_BASE_EXAMPLES = list(_COMMON_EXAMPLES)


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


def _parse_press(words: list[str], i: int, strict: bool = False):
    """Parse everything after 'press'. Returns (list[Chord], next_i)."""
    n = len(words)
    chords: list[Chord] = []
    mods: list[str] = []
    countable = False           # last chord was a non-digit key a number can repeat
    while i < n:
        w = words[i]
        if w == "[unk]":
            if strict:
                break
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


def parse_commands(text, min_word_conf: float = 0.0, strict: bool = False):
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

# Which canonical commands have any effect in each state (keys are the canonical strings produced
# by parse_commands; "press"/"scroll" stand for any KeyPress/Scroll object and the digits are the
# grid cells). The controller consults this so "what is appropriate right now" lives in one place.
# AWAKE and GRID share the same two-tier *grammar* in the speech thread (a single breath can cross
# the boundary, e.g. "mouse grid five"), but they are listed separately here because these sets are
# read in execution order, after the state has actually advanced.
ALLOWED: dict[str, set] = {
    SLEEPING: {"start"},
    AWAKE: {"stop", "grid", "left", "right", "double", "press", "scroll"},
    # No "press": key presses (and page up/down) are ignored while the grid is open.
    GRID: {"stop", "grid", "back", "mark", "cancel", "move", "left", "right", "double",
           "scroll", *[str(n) for n in range(1, 10)]},
}


def command_token(cmd) -> str:
    """The ALLOWED key for a parsed command (KeyPress/Scroll collapse to 'press'/'scroll')."""
    if isinstance(cmd, KeyPress):
        return "press"
    if isinstance(cmd, Scroll):
        return "scroll"
    return cmd


def next_state(state: str, token: str) -> str:
    """State after an (allowed) command; mirrors what Controller.handle does."""
    if token == "stop":
        return SLEEPING
    if state == SLEEPING:
        return AWAKE if token == "start" else state
    if state == AWAKE:
        return GRID if token == "grid" else state
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


def validate(text, state: str, min_word_conf: float = 0.0):
    """Commands for `text` (a string or Vosk's word list) if it is a complete, well-ordered
    utterance in `state`; None if anything is stray, incomplete or out of place."""
    cmds = parse_commands(text, min_word_conf=min_word_conf, strict=True)
    return cmds if cmds and sequence_valid(cmds, state) else None


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

    def _click_here(self, cmd: str) -> None:
        """Click at the current cursor position (used while awake, with no grid open)."""
        button = "left" if cmd == "double" else cmd
        self.mouse.click(button, double=(cmd == "double"))
        print(f"{cmd} click at cursor")

    def handle(self, cmd) -> None:
        # One gate decides whether a command is appropriate right now (see ALLOWED); anything else
        # is dropped here instead of silently by whichever branch happened to run. This is evaluated
        # in execution order, so a single utterance can advance the state mid-breath: "mouse grid
        # five" opens the grid (allowed while AWAKE) and only then uses the digit (allowed in GRID).
        token = command_token(cmd)
        if token not in ALLOWED[self.state]:
            if token == "press" and self.state == GRID:
                print("key presses are ignored while the mouse grid is open")
            return

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

        if self.state == AWAKE:
            if cmd == "stop":
                self._set(SLEEPING)
            elif cmd == "grid":
                self.nav.reset()
                self.mark = None
                self._set(GRID)
                self._show()
            elif cmd in ("left", "right", "double"):
                self._click_here(cmd)       # click wherever the cursor already is, no grid needed
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
        # Last heard phrase + confidence summary (filled in by set_heard; invisible while empty).
        self.heard = tk.Label(self.frame, font=("Consolas", 9), fg="white", padx=6)
        self.heard.pack(side="left")
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
        self.heard.config(bg=colour)
        self.mover.config(bg=colour)
        self.frame.config(bg=colour)
        self._place()

    def set_heard(self, text: str) -> None:
        """Show the last recognised phrase and its confidences (called from the UI poll loop)."""
        if self.heard.cget("text") != text:
            self.heard.config(text=text)
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
    """Mic -> Vosk with one recogniser per state (wake-only / awake / grid), then a hard grammar
    check: an utterance is acted on only if it is complete and well-ordered for the current state
    ("page delta" is rejected; a lower-ranked "page down" alternative is used if --nbest has one)."""

    def __init__(self, model_path, device, min_conf, get_state, out_queue, open_vocab=False,
                 word_conf=0.0, nbest=0, log_path=None, lenient=False, flat_grammar=False):
        super().__init__(daemon=True)
        self.model_path, self.device, self.min_conf = model_path, device, min_conf
        self.open_vocab = open_vocab
        self.word_conf = word_conf    # per-word floor: drop single words the model isn't sure of
        self.nbest = nbest            # 0 = single result; N>0 = ask for N alternative hypotheses
        self.log_path = log_path      # if set, append each recognition (JSONL) here for analysis
        self.lenient = lenient        # True = old behaviour: skip stray words instead of rejecting
        self.flat_grammar = flat_grammar   # True = old flat word list instead of the BNF sentences
        self.level = 0.0         # latest mic loudness, 0..1, read by the UI for the meter
        self.last_heard = ""     # last recognised phrase + confidence summary, read by the UI
        self.get_state, self.out = get_state, out_queue
        self.audio: queue.Queue[bytes] = queue.Queue()

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
                       for c in parse_commands(src, min_word_conf=self.word_conf))
        return validate(src, state, self.word_conf) is not None

    def _commands(self, text: str, words: list, state: str):
        """The commands to run for one hypothesis, or None to ignore it."""
        src = words or text
        if self.lenient:
            return parse_commands(src, min_word_conf=self.word_conf) or None
        return validate(src, state, self.word_conf)

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
        cconfs = [float(w.get("conf", 1.0)) for w in cwords]
        if cconfs:
            self.last_heard = f"{ctext}  \u00b7  avg {sum(cconfs)/len(cconfs):.2f}  min {min(cconfs):.2f}"
        else:
            self.last_heard = ctext
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

    def run(self) -> None:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)
        model = Model(self.model_path)

        def make(grammar):
            r = (KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar)) if grammar
                 else KaldiRecognizer(model, SAMPLE_RATE))     # no grammar = open vocabulary
            r.SetWords(True)
            if self.nbest > 0:
                r.SetMaxAlternatives(self.nbest)   # n-best hypotheses (changes the JSON shape)
            return r

        t0 = time.time()
        if self.open_vocab:
            awake_g = grid_g = None
        elif self.flat_grammar:
            awake_g = grid_g = COMMAND_GRAMMAR
        else:
            awake_g, grid_g = AWAKE_SENTENCES, GRID_SENTENCES
        recs = {SLEEPING: make(WAKE_GRAMMAR), AWAKE: make(awake_g), GRID: make(grid_g)}
        kind = "open vocabulary" if self.open_vocab else ("flat word list" if self.flat_grammar
                                                          else f"{len(awake_g)}/{len(grid_g)} sentences")
        print(f"Recognisers ready in {time.time() - t0:.1f}s (grammar: {kind})")
        last_state = SLEEPING

        def cb(indata, frames, t, status):
            data = bytes(indata)
            self.level = level_from_pcm(data)
            self.audio.put(data)

        log = None
        if self.log_path:
            try:
                log = open(self.log_path, "a", encoding="utf-8")
                print(f"Logging recognitions to {self.log_path}")
            except OSError as e:
                print(f"warning: cannot write log file {self.log_path}: {e}")
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=800, device=self.device,
                                   dtype="int16", channels=1, callback=cb):
                print("Microphone open. Say \"start listening\".")
                while True:
                    data = self.audio.get()
                    state = self.get_state()
                    asleep = state == SLEEPING
                    if state != last_state:               # state flipped: drop stale audio
                        recs[state].Reset()
                        last_state = state
                    rec = recs[state]
                    if rec.AcceptWaveform(data):
                        hyps = self._hypotheses(json.loads(rec.Result()))
                        text, _, words = hyps[0]
                        if not text:
                            continue
                        # With --nbest, prefer the highest-ranked alternative that is a valid
                        # utterance in this state (so "page delta" loses to "page down").
                        chosen = self._choose(hyps, state) if len(hyps) > 1 else 0
                        ctext, _, cwords = hyps[chosen]
                        cmds = self._commands(ctext, cwords, state)
                        if log is not None:               # record every recognition, even weak ones
                            self._write_log(log, state, asleep, hyps, chosen, valid=cmds)
                        # Weak overall confidence is ignored as before; no per-word data (some
                        # result shapes have none) cannot be judged, so the grammar check decides.
                        if cwords and not self._confident(cwords):
                            continue
                        self._report(hyps, chosen, accepted=bool(cmds))
                        for cmd in cmds or ():
                            self.out.put(cmd)
        finally:
            if log is not None:
                log.close()


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

    import tkinter as tk
    make_dpi_aware()
    model_path = ensure_model(args.model)
    log_path = None if args.no_log else os.path.abspath(args.log)

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
                          args.open_vocab, args.word_conf, args.nbest, log_path, args.lenient, args.flat_grammar)
    speech.start()

    def meter_poll():
        pill.set_level(speech.level)
        pill.set_heard(speech.last_heard)
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
