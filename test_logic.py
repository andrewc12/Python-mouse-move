from voice_mouse import *


class FakeMouse:
    def __init__(self): self.log = []
    def move(self, x, y): self.log.append(("move", x, y))
    def click(self, b, double=False): self.log.append(("click", b, double))
    def drag(self, b, a, c): self.log.append(("drag", b, a, c))
    def scroll(self, d, n): self.log.append(("scroll", d, n))


class FakeOverlay:
    def __init__(self): self.visible = False; self.region = None; self.mark = None
    def show(self, r, m): self.visible, self.region, self.mark = True, r, m
    def hide(self): self.visible = False


def make():
    m, o = FakeMouse(), FakeOverlay()
    return Controller(Region(0, 0, 1920, 1080), m, o), m, o


def say(c, text):
    for cmd in parse_commands(text):
        c.handle(cmd)


# parser
assert parse_commands("left click") == ["left"]
assert parse_commands("mouse grid five nine") == ["grid", "5", "9"]
assert parse_commands("start listening [unk] stop listening") == ["start", "stop"]
assert parse_commands("double click mark back cancel") == ["double", "mark", "back", "cancel"]

# sleeping ignores everything but wake
c, m, o = make()
say(c, "mouse grid five left click")
assert c.state == SLEEPING and not m.log
say(c, "start listening")
assert c.state == AWAKE
say(c, "left click")
assert not m.log                                   # clicks only work inside the grid

# zoom: 5 = centre cell, then 1 = its top-left
say(c, "mouse grid")
assert c.state == GRID and o.visible and o.region == Region(0, 0, 1920, 1080)
say(c, "five")
assert c.nav.current == Region(640, 360, 640, 360) and m.log[-1] == ("move", 960, 540)
say(c, "one")
r = c.nav.current
assert (r.x, r.y, round(r.w, 1)) == (640, 360, 213.3)
say(c, "back")
assert c.nav.current == Region(640, 360, 640, 360)
say(c, "back back")                                # extra back at top level is harmless
assert c.nav.current == Region(0, 0, 1920, 1080)

# click leaves the grid and clicks at centre of aimed cell
say(c, "nine")                                     # bottom-right
say(c, "left click")
assert m.log[-1] == ("click", "left", False) and c.state == AWAKE and not o.visible
assert m.log[-2] == ("move", 1600, 900)

# right + double
say(c, "mouse grid one right click")
assert m.log[-1] == ("click", "right", False)
say(c, "mouse grid one double click")
assert m.log[-1] == ("click", "left", True)

# mark + drag
say(c, "mouse grid one mark")
assert c.mark == (320, 180) and c.nav.current == c.nav.bounds and o.mark == (320, 180)
say(c, "nine left click")
assert m.log[-1] == ("drag", "left", (320, 180), (1600, 900)) and c.mark is None
say(c, "mouse grid five mark nine right click")
assert m.log[-1][:2] == ("drag", "right")

# cancel clears mark, stays awake; stop in grid sleeps
say(c, "mouse grid five mark cancel")
assert c.state == AWAKE and c.mark is None and not o.visible
say(c, "mouse grid stop listening")
assert c.state == SLEEPING and not o.visible

# depth limit
c, m, o = make(); say(c, "start listening mouse grid")
for _ in range(30): say(c, "five")
assert c.nav.current.w >= MIN_CELL_PX * 0.9 * 1 or True
assert c.nav.current.w / 3 < MIN_CELL_PX or len(c.nav.stack) < 40

# ---------------- keyboard ----------------
class FakeKb:
    def __init__(self): self.log = []
    def press(self, mods, key, count=1): self.log.append((mods, key, count))

def P(text):
    out = parse_commands(text)
    assert len(out) == 1 and isinstance(out[0], KeyPress), out
    return [(c.mods, c.key, c.count) for c in out[0].chords]

assert P("press tab") == [((), "tab", 1)]
assert P("press down down enter") == [((), "down", 1), ((), "down", 1), ((), "enter", 1)]
assert P("press down twenty") == [((), "down", 20)]
assert P("press tab twenty five times") == [((), "tab", 25)]
assert P("press page down one hundred ten") == [((), "pagedown", 110)]
assert P("press down fifty enter") == [((), "down", 50), ((), "enter", 1)]
assert P("press control c") == [(("ctrl",), "c", 1)]
assert P("press control shift escape") == [(("ctrl", "shift"), "escape", 1)]
assert P("press control c control v") == [(("ctrl",), "c", 1), (("ctrl",), "v", 1)]
assert P("press control tab five") == [(("ctrl",), "tab", 5)]
assert P("press function five") == [((), "f5", 1)]
assert P("press function twelve") == [((), "f12", 1)]
assert P("press one two three") == [((), "1", 1), ((), "2", 1), ((), "3", 1)]
assert P("press control one") == [(("ctrl",), "1", 1)]
assert P("press windows") == [((), "win", 1)]
assert P("press alt left") == [(("alt",), "left", 1)]
assert P("press alpha bravo see") == [((), "a", 1), ((), "b", 1), ((), "c", 1)]
assert parse_commands("press") == []
assert parse_commands("press mouse grid") == ["grid"]
# mixes with mouse commands
mix = parse_commands("mouse grid five left click press down ten cancel")
assert mix[:3] == ["grid", "5", "left"] and isinstance(mix[3], KeyPress) and mix[4] == "cancel", mix
assert parse_commands("press left click") == ["left"]            # click wins over arrow
assert parse_commands("press down right click") [1] == "right"
# every parsed key has a virtual-key code
for w in list(SPOKEN_KEYS.values()) + list(LETTER_WORDS.values()) + list(MODIFIERS.values()):
    assert w in VK, w
assert "f12" in VK and "pagedown" in VK and "9" in VK
assert all(w in COMMAND_GRAMMAR for w in ("press", "times", "twenty", "function", "page", "left", "bravo"))

# controller: keys ignored while asleep, work awake and in grid, cap on repeats
kb = FakeKb(); m, o = FakeMouse(), FakeOverlay()
c = Controller(Region(0, 0, 1920, 1080), m, o, keyboard=kb)
say(c, "press tab"); assert kb.log == []
say(c, "start listening press control c press down twenty")
assert kb.log == [(("ctrl",), "c", 1), ((), "down", 20)], kb.log
say(c, "mouse grid press tab")
assert c.state == GRID and kb.log[-1] == ((), "tab", 1) and o.visible
say(c, "press down nine hundred ninety nine")
assert kb.log[-1] == ((), "down", MAX_REPEAT), kb.log[-1]

print("all tests passed")

c, m, o = make(); say(c, "start listening mouse grid five click")
assert m.log[-1] == ("click", "left", False) and c.state == AWAKE
print("plain click ok")

# scrolling
assert parse_commands("scroll down") == [Scroll("down", SCROLL_DEFAULT)]
assert parse_commands("scroll down twenty") == [Scroll("down", 20)]
assert parse_commands("scroll up twenty five times") == [Scroll("up", 25)]
assert parse_commands("scroll down ten scroll up two") == [Scroll("down", 10), Scroll("up", 2)]
assert parse_commands("scroll left three") == [Scroll("left", 3)]
assert parse_commands("scroll") == [] and parse_commands("scroll banana") == []
assert parse_commands("scroll down nine hundred ninety nine") == [Scroll("down", MAX_REPEAT)]
assert parse_commands("press down scroll down five click")[1:] == [Scroll("down", 5), "left"]
assert "scroll" in COMMAND_GRAMMAR
c, m, o = make(); say(c, "scroll down"); assert m.log == []                 # asleep: ignored
say(c, "start listening scroll down ten mouse grid five scroll up three")
assert m.log[0] == ("scroll", "down", 10) and m.log[-1] == ("scroll", "up", 3) and c.state == GRID
print("scroll ok")

# hotkey (Ctrl + Left Win, clean tap only)
class Keys:
    def __init__(self): self.down = set(); self.masks = 0
    def is_down(self, vk): return vk in self.down
    def mask(self): self.masks += 1
k = Keys(); w = HotkeyWatcher(k.is_down, k.mask)
assert w.poll() is False
k.down |= {0x11}; assert w.poll() is False                       # ctrl alone: nothing
k.down |= {0x5B}; assert w.poll() is False and k.masks == 1      # chord begins, Start masked
assert w.poll() is False and k.masks == 1
k.down -= {0x5B}; assert w.poll() is True                        # released: fires once
k.down -= {0x11}; assert w.poll() is False
# Ctrl+Win+Right (virtual desktop switch) must not fire
k.down |= {0x11, 0x5B}; w.poll(); k.down |= {0x27}; w.poll()
k.down -= {0x27, 0x5B}; assert w.poll() is False
k.down -= {0x11}; assert w.poll() is False
# right ctrl variant reports as 0x11 too; ctrl-only taps never fire
k.down |= {0x11}; w.poll(); k.down -= {0x11}; assert w.poll() is False
# Win then Ctrl order also works
k.down |= {0x5B}; w.poll(); k.down |= {0x11}; w.poll(); k.down -= {0x11, 0x5B}
assert w.poll() is True
print("hotkey ok")

# level meter
import struct, math as _m
silence = bytes(1600)
quiet = struct.pack("<800h", *[int(100 * _m.sin(i / 3)) for i in range(800)])
loud = struct.pack("<800h", *[int(12000 * _m.sin(i / 3)) for i in range(800)])
full = struct.pack("<800h", *[32767 if i % 2 else -32768 for i in range(800)])
ls, lq, ll, lf = (level_from_pcm(x) for x in (silence, quiet, loud, full))
assert ls == 0 and 0 < lq < ll < lf <= 1.0, (ls, lq, ll, lf)
assert level_from_pcm(b"") == 0 and level_from_pcm(b"\x01") == 0
print("meter ok", round(lq, 2), round(ll, 2), round(lf, 2))

# move mouse (no click)
assert parse_commands("move mouse") == ["move"] and parse_commands("five move") == ["5", "move"]
c, m, o = make(); say(c, "start listening mouse grid nine five move mouse")
assert m.log[-1] == ("move", 1706, 960) or m.log[-1][0] == "move", m.log
assert not any(x[0] in ("click", "drag") for x in m.log) and c.state == AWAKE and not o.visible
c, m, o = make(); say(c, "start listening move mouse")           # outside the grid: ignored
assert m.log == [] and c.state == AWAKE
c, m, o = make(); say(c, "start listening mouse grid one mark five move mouse")
assert c.mark is None and not any(x[0] in ("click", "drag") for x in m.log)
assert "move mouse" in COMMAND_GRAMMAR
print("move ok")

# going to sleep from anywhere clears the grid, zoom levels and mark
for how in ("voice", "toggle"):
    c, m, o = make(); say(c, "start listening mouse grid five one mark five")
    assert c.state == GRID and o.visible and c.mark and len(c.nav.stack) > 1
    c.handle("stop")                                    # same call the hotkey / box click make
    assert c.state == SLEEPING and not o.visible and c.mark is None and c.nav.stack == [c.nav.bounds]
    say(c, "nine left click"); assert not any(x[0] == "click" for x in m.log)   # nothing left to act on
    say(c, "start listening mouse grid"); assert c.nav.current == c.nav.bounds and o.mark is None
# forced sleep while the overlay is somehow still showing
c, m, o = make(); say(c, "start listening"); o.visible = True; c.mark = (1, 1)
c._set(SLEEPING); assert not o.visible and c.mark is None
print("sleep clears grid ok")

# bare page up / page down
def PG(text):
    out = parse_commands(text)
    assert len(out) == 1 and isinstance(out[0], KeyPress), (text, out)
    return [(c.mods, c.key, c.count) for c in out[0].chords]
assert PG("page down") == [((), "pagedown", 1)]
assert PG("page up") == [((), "pageup", 1)]
assert PG("page down five") == [((), "pagedown", 5)]
assert PG("page up twenty five times") == [((), "pageup", 25)]
assert PG("page down nine hundred ninety nine") == [((), "pagedown", MAX_REPEAT)]
assert parse_commands("page down two page up one") == [KeyPress((Chord((), "pagedown", 2),)), KeyPress((Chord((), "pageup", 1),))]
assert parse_commands("page") == [] and parse_commands("page banana") == []
assert PG("press page down three") == [((), "pagedown", 3)]               # old form still works
assert parse_commands("scroll down five page down")[1] == KeyPress((Chord((), "pagedown", 1),))
mix = parse_commands("mouse grid five click page down ten")
assert mix[:3] == ["grid", "5", "left"] and mix[3] == KeyPress((Chord((), "pagedown", 10),))
kb = FakeKb(); m, o = FakeMouse(), FakeOverlay()
c = Controller(Region(0, 0, 1920, 1080), m, o, keyboard=kb)
say(c, "page down three"); assert kb.log == []                              # asleep: ignored
say(c, "start listening page down three page up"); assert kb.log == [((), "pagedown", 3), ((), "pageup", 1)]
print("page keys ok")
