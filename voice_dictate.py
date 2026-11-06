"""
voice_dictate.py - hands-free dictation for Windows, in the style of Windows voice typing (Win+H),
but fully offline and tuned for an older PC (4 CPU cores, small GPU, lots of RAM).

What it does
------------
Talk and the words appear in whatever window has keyboard focus, almost as you say them. While you
are still speaking, a fast "draft" model keeps guessing and the text on screen is corrected in
place (backspace the wrong tail, type the better one), exactly like Windows voice typing. When you
pause, a more accurate "final" model re-reads the whole phrase and fixes it up, with punctuation
and capital letters, in the same way.

    microphone -> voice-activity detection (VAD) -> utterance segmenter
                      |-- every ~0.3 s ----> DRAFT  model (small, fast)  -> type / correct on screen
                      '-- at a pause -------> FINAL  model (bigger)      -> final correction, commit

Default engines (both run offline through sherpa-onnx, no GPU needed):
  draft  sherpa-onnx-streaming-zipformer-en-2023-06-26   a true streaming recogniser: fast enough to
                                                          re-read the whole phrase every 0.3 s on a
                                                          few CPU cores. Lower case, no punctuation.
  final  sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8      NVIDIA Parakeet TDT 0.6B, English; accurate,
                                                          adds punctuation and capital letters.
Whisper (faster-whisper) is still available for either role by giving a Whisper name, e.g.
--final-model small.en. The two models run on separate threads, each with its own share of the CPU
cores, so a slow final never stalls the live draft of the next phrase. The RAM is what lets two
models sit loaded at once. The first run downloads each model (about 300 MB and 460 MB) into ./models.

Voice commands (say each one as its own phrase, i.e. pause before and after)
  "new line"            presses Enter
  "new paragraph"       presses Enter twice
  "scratch that"        deletes the last phrase you dictated ("delete that" is the same)
  "stop listening"      pauses dictation  ("stop dictation" is the same)
The words only act as commands when they are the whole phrase; inside a sentence they are typed.

Turning it on and off
  Ctrl+Alt+D (change with --hotkey), or click the status box in the corner. Its arrow button moves
  the box round the screen corners. A high beep = dictating, low beep = paused.
  Start with --start-active to begin dictating as soon as the models have loaded.

Things worth knowing
  * Text is only ever corrected within the phrase(s) still being decided. Once a phrase is final it
    is never touched again, except by "scratch that". If you click or switch to another window while
    a phrase is still being corrected, the program stops editing the old window (so it can never
    backspace over the wrong text) and starts fresh in the new one.
  * Typing uses SendInput with Unicode characters, so any character works and it is fast. Windows
    blocks a normal program from typing into windows that run as administrator; start with --admin
    to reach those.
  * The first run downloads the models into ./models; after that it is offline.

Speed / accuracy knobs. A model name picks the engine: names starting "sherpa-onnx-streaming" are
streaming recognisers, "sherpa-onnx-nemo" are Parakeet-style offline ones (both downloaded from the
sherpa-onnx "asr-models" release), anything else is a faster-whisper model name.
  --draft-model             e.g. sherpa-onnx-streaming-zipformer-en-20M-2023-02-17 (smallest, fastest),
                            sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06 (54 MB), or tiny.en
  --final-model             e.g. sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8, or small.en / distil-small.en
                            / medium.en / large-v3-turbo (Whisper)
  --no-draft                only type when you pause (least CPU)
  --pause-ms 600            how long a pause ends a phrase (lower = snappier, more splits)
  --device cuda             use the NVIDIA GPU instead of the CPU. A GT 1030 has 2 GB and no fast
                            half-precision, so use small models only; it also needs the CUDA 12
                            runtime libraries and a CUDA build of the engine (see requirements.txt).
                            Try --benchmark first: on this class of machine the CPU is often as quick.
  --benchmark               records 6 seconds, times the chosen models, and exits
  --prompt "Kubernetes, Perth, Dr Nguyen"
                            words / names to bias a Whisper final model towards (ignored by the others)

Run:  python voice_dictate.py --start-active
      python voice_dictate.py --list-devices
      pythonw voice_dictate.py          (no console window)
"""
from __future__ import annotations

import argparse
import collections
import math
import os
import queue
import re
import sys
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass

SAMPLE_RATE = 16000
FRAME_MS = 30                                   # webrtcvad takes 10, 20 or 30 ms frames
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2

# --------------------------------------------------------------------------
# Status box and Windows helpers (the same look and behaviour as voice_mouse.py, copied here so this
# file runs on its own)
# --------------------------------------------------------------------------
SLEEPING, AWAKE, GRID = "sleeping", "awake", "grid"
PRIORITY_CLASSES = {"normal": 0x00000020, "above": 0x00008000, "high": 0x00000080}


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float


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


def primary_screen() -> Region:
    import ctypes
    u = ctypes.windll.user32
    return Region(0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))


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


class StatusPill:
    COLORS = {SLEEPING: ("#444444", "Sleeping", "say \"start listening\""),
              AWAKE: ("#1e8e3e", "Listening", "\"mouse grid\" or \"press ...\""),
              GRID: ("#c5221f", "Grid", "say 1-9, back, mark, cancel")}
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


PAUSED, LISTENING, LOADING = SLEEPING, AWAKE, GRID   # the pill's three states, in dictation terms


# --------------------------------------------------------------------------
# Pure logic (no Windows / audio / model dependencies, so it can be unit tested)
# --------------------------------------------------------------------------

# ---- cleaning what the model says -------------------------------------------------------------
# Whisper invents these on silence, breaths and keyboard noise.
HALLUCINATIONS = {"you", "thanks for watching", "thank you for watching", "please subscribe",
                  "subtitles by the amara org community"}


def _words(text: str) -> list[str]:
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
    if " ".join(_words(t)) in HALLUCINATIONS:
        return ""
    return squash_repeats(t)


def clean_draft(text: str) -> str:
    """A draft is cleaned the same way, and loses a trailing '.' / ',' / '...' : the model puts one
    on every guess, and it would otherwise be typed and backspaced again on each update."""
    return re.sub(r"[\s.,\u2026]+$", "", clean_transcript(text))


# ---- voice commands ---------------------------------------------------------------------------
COMMANDS: dict[tuple[str, ...], str] = {
    ("new", "line"): "newline", ("newline",): "newline", ("new", "paragraph"): "paragraph",
    ("scratch", "that"): "scratch", ("delete", "that"): "scratch",
    ("stop", "listening"): "stop", ("stop", "dictation"): "stop",
}


def parse_command(text: str):
    """The command a whole phrase stands for ('newline', 'paragraph', 'scratch', 'stop'), or None."""
    return COMMANDS.get(tuple(_words(text)))


def is_command_prefix(text: str) -> bool:
    """Could this (possibly unfinished) phrase still turn out to be a command? Drafts that might be
    are held back rather than typed and then deleted."""
    w = tuple(_words(text))
    return bool(w) and any(k[:len(w)] == w for k in COMMANDS)


# ---- keyboard events ---------------------------------------------------------------------------
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
        part.text = "" if is_command_prefix(text) else clean_draft(text)
        self._update()

    def final(self, uid: int, text: str) -> None:
        self._sync_focus()
        part = self._find(uid)
        if not part or uid <= self.ignore_upto:
            return
        cleaned = clean_transcript(text)
        part.kind = parse_command(cleaned) or "text"
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


# ---- the global hotkey --------------------------------------------------------------------------
HOTKEY_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "space": 0x20}
HOTKEY_VK.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
HOTKEY_VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})


def parse_hotkey(text: str) -> list[int]:
    """'ctrl+alt+d' -> [0x11, 0x12, 0x44]"""
    try:
        keys = [HOTKEY_VK[p.strip().lower()] for p in text.split("+") if p.strip()]
    except KeyError as e:
        raise ValueError(f"unknown key in hotkey: {e.args[0]!r}") from None
    if len(keys) < 2:
        raise ValueError("a hotkey needs at least two keys, e.g. ctrl+alt+d")
    return keys


class ChordWatcher:
    """True once each time every key of the chord has just become held (poll it from the UI loop)."""

    def __init__(self, is_down, vks):
        self.is_down, self.vks, self.held = is_down, list(vks), False

    def poll(self) -> bool:
        down = all(self.is_down(vk) for vk in self.vks)
        fired, self.held = down and not self.held, down
        return fired


# --------------------------------------------------------------------------
# Windows specifics
# --------------------------------------------------------------------------
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
                      "administrator; start with --admin)")


def foreground_window() -> int:
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    return u.GetForegroundWindow() or 0


def make_chord_watcher(vks) -> ChordWatcher:
    import ctypes
    u = ctypes.windll.user32
    return ChordWatcher(lambda vk: bool(u.GetAsyncKeyState(vk) & 0x8000), vks)


class DictationPill(StatusPill):
    """The voice_mouse status box with dictation wording (state keys are reused: see PAUSED etc.)."""

    def __init__(self, root, screen, corner: str, hotkey_label: str):
        super().__init__(root, screen, corner=corner)
        self.COLORS = {PAUSED: ("#444444", "Paused", f"{hotkey_label} or click to dictate"),
                       LISTENING: ("#1e8e3e", "Dictating", "just talk"),
                       LOADING: ("#1a5fb4", "Loading", "speech models (first run downloads them)")}
        self.set(LOADING)


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

    def __call__(self, pcm: bytes) -> str:
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
    """Streaming recogniser as the DRAFT stage. Each call re-reads the whole phrase so far from a
    fresh stream: that is only affordable because the model is so much faster than real time, and it
    keeps this a drop-in replacement for the Whisper draft. Output is lower-cased: the final pass
    supplies the capitals and punctuation."""

    def __init__(self, name: str, threads: int, device: str = "cpu", model_dir: str | None = None):
        self.name, self.threads, self.device, self.model_dir = name, threads, device, model_dir
        self.model = None

    def load(self) -> "SherpaStreaming":
        import sherpa_onnx
        f = find_model_files(ensure_sherpa_model(self.name, self.model_dir or "models"))
        self.model = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=f["tokens"], encoder=f["encoder"], decoder=f["decoder"], joiner=f["joiner"],
            num_threads=self.threads, sample_rate=SAMPLE_RATE, feature_dim=80,
            decoding_method="greedy_search", provider="cuda" if self.device == "cuda" else "cpu")
        return self

    def __call__(self, pcm: bytes) -> str:
        import numpy as np
        rec = self.model
        stream = rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, _pcm_to_float(pcm))
        stream.accept_waveform(SAMPLE_RATE, np.zeros(int(0.4 * SAMPLE_RATE), dtype=np.float32))  # flush the tail
        stream.input_finished()
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        return clean_transcript(_result_text(rec.get_result(stream)).lower())


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

    def __call__(self, pcm: bytes) -> str:
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


class Notice:
    """A short message for the status box, written by any thread, shown by the UI loop."""

    def __init__(self):
        self.text, self.seq = "", 0

    def say(self, text: str) -> None:
        print(text)
        self.text = text
        self.seq += 1


class Listener(threading.Thread):
    """Microphone -> 30 ms frames -> level meter + Pipeline. Survives unplug / replug."""
    STALL_SECONDS, RETRY_SECONDS = 2.0, 1.0

    def __init__(self, device, pipeline, notice: Notice):
        super().__init__(daemon=True, name="listener")
        self.device, self.pipeline, self.notice = device, pipeline, notice
        self.level = 0.0
        self.frames: queue.Queue[bytes] = queue.Queue()
        self._partial = bytearray()
        self._last_audio = time.monotonic()

    def _callback(self, indata, frames, t, status) -> None:
        self._last_audio = time.monotonic()
        self._partial += bytes(indata)
        while len(self._partial) >= FRAME_BYTES:
            self.frames.put(bytes(self._partial[:FRAME_BYTES]))
            del self._partial[:FRAME_BYTES]

    @staticmethod
    def _refresh(sd) -> None:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass

    def _open(self, sd):
        last = None
        while True:
            try:
                stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAME_BYTES // 2,
                                           device=self.device, dtype="int16", channels=1,
                                           callback=self._callback)
                stream.start()
                self._last_audio = time.monotonic()
                return stream
            except Exception as e:
                if str(e) != last:
                    last = str(e)
                    self.notice.say(f"\u26a0 no microphone ({last}); waiting for it ...")
                time.sleep(self.RETRY_SECONDS)
                self._refresh(sd)

    def run(self) -> None:
        import sounddevice as sd
        stream = self._open(sd)
        self.notice.say("Microphone open.")
        while True:
            try:
                frame = self.frames.get(timeout=0.5)
            except queue.Empty:
                try:
                    lost = not stream.active
                except Exception:
                    lost = True
                if lost or time.monotonic() - self._last_audio > self.STALL_SECONDS:
                    self.level = 0.0
                    self.pipeline.set_active(False)
                    for how in ("abort", "close"):
                        try:
                            getattr(stream, how)()
                        except Exception:
                            pass
                    self.notice.say("\u26a0 microphone lost; reconnecting ...")
                    self._refresh(sd)
                    stream = self._open(sd)
                    self.notice.say("microphone back (press the hotkey to dictate)")
                continue
            self.level = level_from_pcm(frame)
            try:
                self.pipeline.feed(frame)
            except Exception:
                traceback.print_exc()


def benchmark(args) -> None:
    import sounddevice as sd
    print("Say a sentence or two for 6 seconds ...")
    rec = sd.rec(6 * SAMPLE_RATE, samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=args.mic)
    sd.wait()
    pcm = rec.tobytes()
    cores = os.cpu_count() or 4
    for label, name in (("draft", args.draft_model), ("final", args.final_model)):
        threads = args.draft_threads if label == "draft" else args.final_threads
        threads = threads or max(1, cores // 2)
        beam = 1 if label == "draft" else args.beam
        t = time.time()
        tr = make_transcriber(name, threads, beam, args, args.prompt if label == "final" else None).load()
        print(f"{label} model {name}: loaded in {time.time() - t:.1f}s ({threads} threads, {args.device})")
        for run in (1, 2):                              # the first run includes warm-up
            t = time.time()
            text = tr(pcm)
            print(f"   run {run}: {time.time() - t:.2f}s for 6.0s of audio -> {text!r}")


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Offline voice dictation for Windows")
    ap.add_argument("--draft-model", default=DEFAULT_DRAFT, help=f"fast live model (default {DEFAULT_DRAFT})")
    ap.add_argument("--final-model", default=DEFAULT_FINAL, help=f"accurate model run at each pause (default {DEFAULT_FINAL})")
    ap.add_argument("--no-draft", action="store_true", help="no live typing: only type each phrase when you pause")
    ap.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    ap.add_argument("--compute-type", default=None, help="Whisper only: CTranslate2 compute type (default int8)")
    ap.add_argument("--draft-threads", type=int, default=0, help="CPU threads for the draft model (default: half the cores)")
    ap.add_argument("--final-threads", type=int, default=0, help="CPU threads for the final model (default: the rest)")
    ap.add_argument("--beam", type=int, default=3, help="Whisper only: beam size of the final model (default 3; 1 = fastest)")
    ap.add_argument("--language", default="en", help="Whisper only: language code, or 'auto' (multilingual models only)")
    ap.add_argument("--prompt", help="Whisper only: names / jargon to bias the final model towards")
    ap.add_argument("--model-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
    ap.add_argument("--mic", type=int, help="input device index (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--vad-level", type=int, choices=(0, 1, 2, 3), default=2,
                    help="voice-activity strictness: 3 ignores more noise, 0 hears more (default 2)")
    ap.add_argument("--pause-ms", type=int, default=600, help="silence that ends a phrase (default 600)")
    ap.add_argument("--draft-interval", type=float, default=0.3, help="seconds between draft updates (default 0.3)")
    ap.add_argument("--idle-timeout", type=float, default=60.0,
                    help="seconds of silence after which dictation pauses by itself (default 60; 0 = never)")
    ap.add_argument("--hotkey", default="ctrl+alt+d", help="toggle chord (default ctrl+alt+d)")
    ap.add_argument("--no-hotkey", action="store_true")
    ap.add_argument("--start-active", action="store_true", help="start dictating as soon as the models are loaded")
    ap.add_argument("--always-on", action="store_true",
                    help="test mode: start dictating as soon as the models load and ignore the hotkey")
    ap.add_argument("--corner", choices=StatusPill.CORNERS, default="bottom-right")
    ap.add_argument("--no-keep-on-top", action="store_true")
    ap.add_argument("--priority", choices=sorted(PRIORITY_CLASSES), default="above",
                    help="Windows process priority (default above)")
    ap.add_argument("--admin", action="store_true", help="restart elevated so typing also reaches administrator windows")
    ap.add_argument("--hide-console", action="store_true")
    ap.add_argument("--benchmark", action="store_true", help="record 6 s, time the chosen models, exit")
    ap.add_argument("--verbose", action="store_true", help="print each decode with its timing")
    args = ap.parse_args()
    if args.language == "auto":
        args.language = None
    if args.always_on:
        args.start_active = args.no_hotkey = True
        args.idle_timeout = 0

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    try:
        import numpy, sounddevice  # noqa: F401
        names = [args.final_model] + ([] if args.no_draft and not args.benchmark else [args.draft_model])
        if any(engine_kind(n) == "whisper" for n in names):
            import faster_whisper  # noqa: F401
        if any(engine_kind(n) != "whisper" for n in names):
            import sherpa_onnx  # noqa: F401
    except ImportError as e:
        sys.exit(f"Missing package ({e.name}). Install the requirements with:\n"
                 f"    {os.path.basename(sys.executable)} -m pip install -r requirements.txt")
    if args.benchmark:
        benchmark(args)
        return
    if sys.platform != "win32":
        sys.exit("This tool types into Windows; run it on Windows.")
    try:
        chord = parse_hotkey(args.hotkey)
    except ValueError as e:
        sys.exit(str(e))

    if args.priority != "normal":
        print(f"Process priority: {args.priority}" if set_priority(args.priority)
              else f"Could not set {args.priority} priority; carrying on at normal.")
    if args.admin and not is_admin():
        print("Restarting as administrator (accept the Windows prompt) ...")
        if relaunch_as_admin():
            return
        print("Could not get administrator rights; carrying on without them.")
    if args.hide_console:
        hide_console()

    import tkinter as tk
    import winsound
    make_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    screen = primary_screen()
    pill = DictationPill(root, screen, args.corner, args.hotkey.replace("+", "+").title().replace("Ctrl", "Ctrl"))
    notice = Notice()

    # ---- models (loaded in the background; the box says "Loading" until both are ready)
    cores = os.cpu_count() or 4
    if args.no_draft:
        draft_threads, final_threads = 0, args.final_threads or cores
    else:
        draft_threads = args.draft_threads or max(1, cores // 2)
        final_threads = args.final_threads or max(1, cores - draft_threads)
    final_tr = make_transcriber(args.final_model, final_threads, args.beam, args, args.prompt)
    draft_tr = None if args.no_draft else make_transcriber(args.draft_model, draft_threads, 1, args)
    ready = threading.Event()

    def load_models():
        try:
            t0 = time.time()
            loaders = [threading.Thread(target=m.load) for m in (draft_tr, final_tr) if m]
            for th in loaders:
                th.start()
            for th in loaders:
                th.join()
            if not all(m.model for m in (draft_tr, final_tr) if m):
                raise RuntimeError("a model failed to load")
            notice.say(f"models ready in {time.time() - t0:.1f}s")
            ready.set()
        except Exception as e:
            notice.say(f"model load failed: {e}")
            traceback.print_exc()

    print(f"Loading models: draft={args.draft_model if draft_tr else 'off'}, final={args.final_model}. "
          "The first run downloads them (about 750 MB), which can take several minutes.")
    threading.Thread(target=load_models, daemon=True, name="loader").start()

    # ---- the speech pipeline
    out: queue.Queue = queue.Queue()

    def run_draft(job):
        uid, pcm = job
        t = time.time()
        text = draft_tr(pcm)
        if args.verbose:
            print(f"draft {uid}: {time.time() - t:.2f}s for {len(pcm) / 32000:.1f}s -> {text!r}")
        out.put(("draft", uid, text))

    def run_final(job):
        uid, pcm = job
        t = time.time()
        try:
            text = final_tr(pcm)
        except Exception:
            traceback.print_exc()
            text = ""                                     # never leave a phrase undecided
        if args.verbose:
            print(f"final {uid}: {time.time() - t:.2f}s for {len(pcm) / 32000:.1f}s -> {text!r}")
        out.put(("final", uid, text))

    draft_worker = LatestWorker(run_draft) if draft_tr else None
    final_worker = FifoWorker(run_final)
    final_worker.start()
    if draft_worker:
        draft_worker.start()
    pipeline = Pipeline(
        make_vad(args.vad_level),
        (lambda uid, pcm: draft_worker.submit((uid, pcm))) if draft_worker else None,
        lambda uid, pcm: final_worker.submit((uid, pcm)), out,
        Segmenter(end_silence_ms=args.pause_ms), draft_every_s=args.draft_interval,
        discard_draft=(draft_worker.discard if draft_worker else (lambda uid: None)),
        idle_s=args.idle_timeout)
    listener = Listener(args.mic, pipeline, notice)
    listener.start()

    # ---- the text side
    state = {"loading": True}

    def set_listening(on: bool, source: str = "") -> None:
        if state["loading"]:
            if source:
                notice.say("still loading the speech models - wait for the box to say Paused/Dictating")
            return
        pipeline.set_active(on)
        pill.set(LISTENING if on else PAUSED)
        if source:
            print(f"{source}: " + ("dictating" if on else "paused"))
            threading.Thread(target=winsound.Beep, args=(1000 if on else 500, 90), daemon=True).start()

    dictator = Dictator(WinTyper(), foreground_window, on_stop=lambda: set_listening(False, "voice"),
                        notice=notice.say)
    pill.on_click = lambda: set_listening(not pipeline.active, "click")

    def poll():
        try:
            while True:
                ev = out.get_nowait()
                if ev[0] == "idle":
                    if pipeline.active:
                        notice.say(f"no speech for {args.idle_timeout:g}s - paused")
                        set_listening(False, "idle")
                    continue
                try:
                    {"start": dictator.begin, "cancel": dictator.cancel,
                     "draft": dictator.draft, "final": dictator.final}[ev[0]](*ev[1:])
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        if state["loading"] and ready.is_set():
            state["loading"] = False
            set_listening(args.start_active)
            if args.start_active:
                print("Dictating: click in a text box and talk." + ("" if args.no_hotkey else f" {args.hotkey} pauses."))
            else:
                pill.set(PAUSED)
                print(f"Ready. Press {args.hotkey} or click the box to start dictating.")
        root.after(15, poll)

    def meter_poll():
        pill.set_level(listener.level)
        pill.set_heard(notice.text, notice.seq)
        root.after(40, meter_poll)

    root.after(15, poll)
    root.after(40, meter_poll)
    if not args.no_keep_on_top:
        def keep_on_top():
            pill.raise_()
            root.after(250, keep_on_top)
        root.after(250, keep_on_top)
    if not args.no_hotkey:
        watcher = make_chord_watcher(chord)

        def hotkey_poll():
            try:
                if watcher.poll():
                    set_listening(not pipeline.active, "hotkey")
            except Exception as e:
                print(f"hotkey error: {e}")
            root.after(20, hotkey_poll)
        root.after(20, hotkey_poll)
        print(f"Hotkey: {args.hotkey} toggles dictation.")
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
