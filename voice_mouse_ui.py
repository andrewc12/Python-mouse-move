"""
voice_mouse_ui.py - the grid overlay and the status box, drawn with Tk (standard library only).

Used in two places: by voice_mouse.py itself, or - when the program is started with --use-hands - by
voice_mouse_hands.py, so the windows are drawn by the small helper that can hold the special
"UI access" privilege (see the notes in voice_mouse_hands.py). Nothing here touches speech or models.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

SLEEPING, AWAKE, GRID, DICTATE = "sleeping", "awake", "grid", "dictating"
STATES = (SLEEPING, AWAKE, GRID, DICTATE)


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
    (the on-screen keyboard, Magnifier, Task Manager when set to stay on top) cannot be covered by a
    normal program; a process that itself has UI access (a signed uiAccess manifest, installed under
    Program Files) creates its windows in that band and so can be above them. The lock screen and UAC
    prompts (the secure desktop) cannot be drawn over by anyone."""
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


CORNERS = ("bottom-right", "bottom-left", "top-left", "top-right")   # order the status box's button cycles


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

    CORNERS = CORNERS

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
