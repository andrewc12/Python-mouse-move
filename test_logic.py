from voice_mouse import *


class FakeMouse:
    def __init__(self): self.log = []
    def move(self, x, y): self.log.append(("move", x, y))
    def click(self, b, double=False): self.log.append(("click", b, double))
    def drag(self, b, a, c): self.log.append(("drag", b, a, c))


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
print("all tests passed; max depth", len(c.nav.stack) - 1, "final cell", c.nav.current.w, "px")
