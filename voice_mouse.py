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
           "cancel"                      -> leave the grid (and forget any mark)

Run:  python voice_mouse.py            (downloads the ~40 MB model on first run)
      python voice_mouse.py --list-devices
"""
from __future__ import annotations

import argparse
import json
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
    ("left", "click"): "left",
    ("right", "click"): "right",
    ("double", "click"): "double",
    ("mark",): "mark",
    ("back",): "back",
    ("cancel",): "cancel",
}

WAKE_GRAMMAR = ["start listening", "[unk]"]
COMMAND_GRAMMAR = (
    ["stop listening", "mouse grid", "left click", "right click", "double click",
     "mark", "back", "cancel", "start listening"]
    + list(NUMBER_WORDS) + ["[unk]"]
)


# --------------------------------------------------------------------------
# Pure logic (no Windows / audio dependencies, so it can be unit tested)
# --------------------------------------------------------------------------
def parse_commands(text: str) -> list[str]:
    """Turn recognised text into a list of commands: 'start', 'grid', '1'..'9', ..."""
    words = text.lower().split()
    out: list[str] = []
    i = 0
    while i < len(words):
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

    def __init__(self, bounds: Region, mouse, overlay, on_state=lambda s: None):
        self.nav = GridNavigator(bounds)
        self.mouse, self.overlay, self.on_state = mouse, overlay, on_state
        self.state = SLEEPING
        self.mark: tuple[int, int] | None = None

    def _set(self, state: str) -> None:
        self.state = state
        self.on_state(state)

    def _show(self) -> None:
        self.overlay.show(self.nav.current, self.mark)

    def _leave_grid(self, new_state: str = AWAKE) -> None:
        self.overlay.hide()
        self.mark = None
        self.nav.reset()
        self._set(new_state)

    def handle(self, cmd: str) -> None:
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
            if self.mark and cmd != "double":
                self.mouse.drag(cmd, self.mark, target)
            else:
                self.mouse.click("left" if cmd == "double" else cmd, double=(cmd == "double"))
            self._leave_grid(AWAKE)
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


def make_click_through(widget) -> None:
    """Layered + transparent + no-activate so the window never takes focus or clicks."""
    import ctypes
    u = ctypes.windll.user32
    widget.update_idletasks()
    hwnd = u.GetAncestor(widget.winfo_id(), 2)           # GA_ROOT
    GWL_EXSTYLE = -20
    style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
    u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                     style | 0x80000 | 0x20 | 0x80 | 0x08000000)


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
              AWAKE: ("#1e8e3e", "Listening - say \"mouse grid\""),
              GRID: ("#c5221f", "Grid - say 1-9, back, mark, cancel")}

    def __init__(self, root, screen: Region):
        import tkinter as tk
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.85)
        self.label = tk.Label(self.win, font=("Segoe UI", 10, "bold"), fg="white", padx=10, pady=4)
        self.label.pack()
        self.screen = screen
        self.set(SLEEPING)
        make_click_through(self.win)

    def set(self, state: str) -> None:
        colour, text = self.COLORS[state]
        self.label.config(text=text, bg=colour)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        self.win.geometry(f"+{int(self.screen.w - w - 16)}+{int(self.screen.h - h - 56)}")


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

    def __init__(self, model_path, device, min_conf, get_state, out_queue):
        super().__init__(daemon=True)
        self.model_path, self.device, self.min_conf = model_path, device, min_conf
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
            r = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar))
            r.SetWords(True)
            return r

        wake, command = make(WAKE_GRAMMAR), make(COMMAND_GRAMMAR)
        last_asleep = True

        def cb(indata, frames, t, status):
            self.audio.put(bytes(indata))

        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=2000, device=self.device,
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
    args = ap.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    if sys.platform != "win32":
        sys.exit("This tool controls the Windows mouse; run it on Windows.")

    import tkinter as tk
    make_dpi_aware()
    model_path = ensure_model(args.model)

    root = tk.Tk()
    root.withdraw()
    screen = primary_screen()
    pill = StatusPill(root, screen)
    overlay = Overlay(root, screen)
    ctl = Controller(screen, WinMouse(), overlay, on_state=pill.set)
    if args.start_awake:
        ctl.handle("start")

    cmds: queue.Queue[str] = queue.Queue()
    SpeechThread(model_path, args.device, args.min_conf, lambda: ctl.state, cmds).start()

    def poll():
        try:
            while True:
                cmd = cmds.get_nowait()
                ctl.handle(cmd)
        except queue.Empty:
            pass
        root.after(30, poll)

    root.after(30, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
