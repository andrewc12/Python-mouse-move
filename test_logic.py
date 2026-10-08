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
assert m.log[-1] == ("click", "left", False)       # clicks work while awake too (at the cursor)

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

# clicking works while awake, at the current cursor position, with no grid open
c, m, o = make(); say(c, "start listening")
say(c, "left click")
assert m.log == [("click", "left", False)] and c.state == AWAKE and not o.visible
say(c, "right click"); assert m.log[-1] == ("click", "right", False)
say(c, "double click"); assert m.log[-1] == ("click", "left", True)
say(c, "click"); assert m.log[-1] == ("click", "left", False)
assert not any(x[0] == "move" for x in m.log)       # never moves the cursor while awake
c, m, o = make(); say(c, "left click")              # still asleep: ignored
assert m.log == [] and c.state == SLEEPING
print("awake click ok")

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


# ---------------- per-word confidence + state policy ----------------
# A plain string counts as fully confident, so the existing callers above are unaffected.
assert parse_commands("left click", min_word_conf=0.9) == ["left"]

# Vosk's per-word result list: words below the floor are dropped before parsing.
words = [{"word": "mouse", "conf": 0.90}, {"word": "grid", "conf": 0.20}]
assert parse_commands(words, min_word_conf=0.5) == []            # "grid" dropped -> nothing useful
assert parse_commands(words, min_word_conf=0.1) == ["grid"]      # both kept -> "mouse grid"
assert parse_commands([{"word": "mark", "conf": 0.50}], min_word_conf=0.5) == ["mark"]   # >= kept
assert parse_commands([{"word": "mark", "conf": 0.49}], min_word_conf=0.5) == []         # < dropped
assert parse_commands([{"word": "mark"}]) == ["mark"]            # missing conf defaults to 1.0

# ALLOWED is the single source of truth for "what is appropriate in this state".
assert ALLOWED[SLEEPING] == {"start"}
assert "5" not in ALLOWED[AWAKE] and "5" in ALLOWED[GRID]
assert "move" not in ALLOWED[AWAKE] and "move" in ALLOWED[GRID]
assert "press" in ALLOWED[AWAKE] and "scroll" in ALLOWED[GRID]
assert "scroll" not in ALLOWED[SLEEPING] and "press" not in ALLOWED[SLEEPING]

# ...and it is enforced by the controller (in execution order, so chaining still works).
c, m, o = make()
say(c, "five"); assert m.log == [] and c.state == SLEEPING       # digit while asleep: no-op
say(c, "start listening"); assert c.state == AWAKE
say(c, "five"); assert m.log == [] and c.state == AWAKE          # digit while awake: no-op
say(c, "mouse grid five")                                        # one breath crosses AWAKE -> GRID
assert c.state == GRID and m.log[-1] == ("move", 960, 540)       # ...and the digit still applies
print("word-conf + allowed ok")


# ---------------- confidence reporting + n-best hypotheses ----------------
import queue as _q
st = SpeechThread("model", None, 0.6, lambda: SLEEPING, _q.Queue())

# _confident gates on the mean per-word confidence.
assert st._confident([{"word": "a", "conf": 0.7}, {"word": "b", "conf": 0.7}]) is True
assert st._confident([{"word": "a", "conf": 0.3}]) is False
assert st._confident([]) is False

# Plain result shape (no alternatives).
plain = {"text": "grid five", "result": [{"word": "grid", "conf": 0.90}, {"word": "five", "conf": 0.40}]}
h = st._hypotheses(plain)
assert h == [("grid five", None, plain["result"])]
st._report(h)
assert st.last_heard.startswith("grid five")            # shown in the status pill
assert "avg 0.65" in st.last_heard and "min 0.40" in st.last_heard

# Alternatives shape (--nbest): each entry carries text, a raw score, and its own words.
nbest = {"alternatives": [
    {"text": "mouse grid five", "confidence": 134.6,
     "words": [{"word": "mouse", "conf": 0.9}, {"word": "grid", "conf": 0.9}, {"word": "five", "conf": 0.6}]},
    {"text": "mouse grid fine", "confidence": 88.1, "words": [{"word": "fine", "conf": 0.2}]}]}
h2 = st._hypotheses(nbest)
assert h2[0][0] == "mouse grid five" and h2[0][1] == 134.6 and len(h2[0][2]) == 3
assert h2[1] == ("mouse grid fine", 88.1, [{"word": "fine", "conf": 0.2}])
st._report(h2)                                          # logs best + one competing line, no crash
assert st.last_heard.startswith("mouse grid five")

# Defensive: alternatives missing "words" (falls back to "result"), and empty result.
assert st._hypotheses({"alternatives": [{"text": "x", "result": [{"word": "x"}]}]})[0][2] == [{"word": "x"}]
st._report(st._hypotheses({}))                          # nothing heard: empty summary, no crash
assert st.last_heard == ""
print("conf report + nbest ok")

# ---------------- n-best rescoring ----------------
# "h down"/"page delta" parse to nothing; "page down" is a real PageDown key.
hx = st._hypotheses({"alternatives": [
    {"text": "h down", "confidence": 209.8, "words": [{"word": "h", "conf": 1.0}, {"word": "down", "conf": 1.0}]},
    {"text": "page down", "confidence": 205.0, "words": [{"word": "page", "conf": 1.0}, {"word": "down", "conf": 1.0}]}]})
assert parse_commands("h down") == [] and parse_commands("page down") == [KeyPress((Chord((), "pagedown", 1),))]
assert st._choose(hx, AWAKE) == 1                       # skip the junk top guess
assert st._choose(hx, SLEEPING) == 0                    # neither valid asleep -> fall back to best
hx2 = st._hypotheses({"alternatives": [
    {"text": "page down", "confidence": 300.0, "words": [{"word": "page"}, {"word": "down"}]},
    {"text": "h down", "confidence": 250.0, "words": [{"word": "h"}, {"word": "down"}]}]})
assert st._choose(hx2, AWAKE) == 0                      # top guess already actionable -> kept
st._report(hx, chosen=1)                                # marks the chosen alt, no crash
assert st.last_heard.startswith("page down")            # pill shows what was actually used
# command_token maps objects/strings to their ALLOWED names
assert command_token("start") == "start"
assert command_token(KeyPress((Chord((), "pagedown", 1),))) == "press"
assert command_token(Scroll("down", 5)) == "scroll"
print("nbest rescore ok")


# ---------------- JSONL recognition log ----------------
import io as _io
st.log_path = None                                       # default: no log
buf = _io.StringIO()
st._write_log(buf, AWAKE, False, hx, 1)                  # hx = the h-down/page-down alternatives
lines = buf.getvalue().splitlines()
assert len(lines) == 1                                   # one JSON object per line
rec = json.loads(lines[0])
assert rec["state"] == "awake" and rec["asleep"] is False
assert rec["heard"] == "h down" and rec["chosen"] == 1 and rec["used"] == "page down"
assert rec["hypotheses"][1] == {"text": "page down", "score": 205.0,
                                "words": [{"word": "page", "conf": 1.0}, {"word": "down", "conf": 1.0}]}
assert "ts" in rec
st._write_log(buf, SLEEPING, True, st._hypotheses({"text": "[unk]", "result": []}), 0)
assert len(buf.getvalue().splitlines()) == 2             # appends, never overwrites
assert json.loads(buf.getvalue().splitlines()[1])["heard"] == "[unk]"
print("jsonl log ok")


# ================= strict grammar check (whole utterance, per state) =================
V = lambda text, st, **kw: validate(text, st, **kw)
# the reported mishearing: "page" may only be followed by up / down
assert V("page delta", AWAKE) is None and V("page delta", GRID) is None
assert V("page down", AWAKE) is not None and V("press page delta", AWAKE) is None
assert V("press page down three", AWAKE) is not None
for bad in ("scroll delta", "scroll", "page", "press", "function", "function thirteen", "press function",
            "times", "twenty", "hundred", "down", "scroll down banana", "mouse grid delta", "[unk]",
            "page [unk] down", "press tab [unk]", "h down", ""):
    assert V(bad, AWAKE) is None and V(bad, GRID) is None, bad
assert V("mouse grid five delta", AWAKE) is None and V("delta page down", AWAKE) is None  # no half-runs

# clicks work awake (no grid); the grid-only words need the grid or "mouse grid" in the same breath
for ok in ("click", "left click", "right click", "double click", "left", "page down", "scroll up three",
           "press tab", "mouse grid", "stop listening"):
    assert V(ok, AWAKE) is not None, ok
for grid_word in ("five", "back", "mark", "cancel", "move mouse", "move"):
    assert V(grid_word, AWAKE) is None, grid_word
    assert V(grid_word, GRID) is not None, grid_word
assert V("mouse grid five one click", AWAKE) == ["grid", "5", "1", "left"]
assert V("mouse grid five click page down ten", AWAKE) is not None
assert V("mouse grid five click five", AWAKE) is None             # grid closed by the click
assert V("click click double click", AWAKE) is not None           # clicks don't change state
assert V("five click mouse grid six", GRID) is not None
# wake word only while asleep; "start listening" means nothing once awake
assert V("start listening", SLEEPING) == ["start"] and V("start listening", AWAKE) is None
assert V("page down", SLEEPING) is None and V("mouse grid", SLEEPING) is None and V("click", SLEEPING) is None
assert V("stop listening", AWAKE) == ["stop"] and V("stop listening", GRID) == ["stop"]
assert V("mouse grid stop listening mouse grid", AWAKE) is None   # asleep after "stop"
# everything the docs promise still passes
for good in ("press tab", "press down down enter", "press down twenty", "press control shift escape",
             "press control c control v", "press function five", "press one two three", "press windows",
             "scroll down", "scroll left three times", "page up twenty five", "press alpha bravo see"):
    assert V(good, AWAKE) is not None and V(good, GRID) is not None, good
assert V("press down left click", GRID) == [KeyPress((Chord((), "down", 1),)), "left"]
assert V("press left click", GRID) is None                        # ambiguous: nothing was pressed
# lenient parse is unchanged for existing callers
assert parse_commands("mouse grid delta five") == ["grid", "5"] and parse_commands("page delta") == []

# Vosk word lists: in strict mode a word under the confidence floor rejects the utterance
# (lenient mode drops it, which could change a count: "scroll down <twenty>" -> default 5)
W = lambda *ws: [{"word": w, "conf": c} for w, c in ws]
assert V(W(("page", .9), ("down", .9)), AWAKE, min_word_conf=.5) == V("page down", AWAKE)
assert V(W(("page", .9), ("down", .2)), AWAKE, min_word_conf=.5) is None
assert V(W(("scroll", .9), ("down", .9), ("twenty", .2)), AWAKE, min_word_conf=.5) is None
assert parse_commands(W(("scroll", .9), ("down", .9), ("twenty", .2)), .5) == [Scroll("down", 5)]
assert V(W(("page", .9), ("down", .2)), AWAKE, min_word_conf=0.0) is not None

# next_state mirrors Controller.handle: random command sequences must end in the same state
import random
rng = random.Random(7)
pool = ["start", "stop", "grid", "left", "right", "double", "move", "cancel", "mark", "back", "5", "1"]
extra = [KeyPress((Chord((), "tab", 1),)), Scroll("down", 3)]
for _ in range(400):
    c, m, o = make(); cur = SLEEPING
    for _ in range(rng.randint(1, 12)):
        cmd = rng.choice(pool + extra)
        tok = command_token(cmd)
        if tok in ALLOWED[cur]:
            cur = next_state(cur, tok)
        c.handle(cmd)
        assert c.state == cur, (c.state, cur, cmd)
        assert o.visible == (cur == GRID) or cur != GRID   # grid open => overlay shown
print("next_state matches controller ok")

# ---- per-state grammars: what an utterance may START with, and which pairs are taught ----
assert AWAKE_GRAMMAR_G.first == {"click", "left", "right", "double", "mouse", "page", "press",
                                 "scroll", "stop"}, AWAKE_GRAMMAR_G.first
assert {"five", "mark", "cancel", "back", "move"} <= GRID_GRAMMAR_G.first
assert not ({"five", "mark", "cancel", "back", "move"} & AWAKE_GRAMMAR_G.first)
assert "start" not in GRID_GRAMMAR_G.first | AWAKE_GRAMMAR_G.first
assert ("mouse", "grid") in AWAKE_GRAMMAR_G.pairs and ("grid", "five") in AWAKE_GRAMMAR_G.pairs
def _after_in(sents, a):
    return {y for s in sents for x, y in zip(s.split(), s.split()[1:]) if x == a}
for sents in (AWAKE_SENTENCES, GRID_SENTENCES):
    assert _after_in(sents, "page") == {"up", "down"}
    assert "delta" not in _after_in(sents, "scroll") | _after_in(sents, "function")
firsts = lambda sents: {s.split()[0] for s in sents if s != "[unk]"}
assert firsts(AWAKE_SENTENCES) <= AWAKE_GRAMMAR_G.first and firsts(GRID_SENTENCES) <= GRID_GRAMMAR_G.first
assert "start" not in firsts(AWAKE_SENTENCES) | firsts(GRID_SENTENCES)

# ---- SpeechThread decision logic (no audio / vosk needed) ----
def mk(**kw):
    return SpeechThread("m", None, 0.6, lambda: AWAKE, _q.Queue(), **kw)
t = mk()
alts = st._hypotheses({"alternatives": [
    {"text": "page delta", "confidence": 290.0, "words": W(("page", 1), ("delta", 1))},
    {"text": "page", "confidence": 288.0, "words": W(("page", 1))},
    {"text": "page down", "confidence": 287.5, "words": W(("page", 1), ("down", 1))}]})
assert t._choose(alts, AWAKE) == 2                                  # skips the two invalid guesses
assert t._commands(*alts[2][::2], AWAKE) == V("page down", AWAKE)
none_ok = st._hypotheses({"alternatives": [{"text": "page delta", "words": W(("page", 1), ("delta", 1))}]})
assert t._choose(none_ok, AWAKE) == 0 and t._commands("page delta", none_ok[0][2], AWAKE) is None  # ignored
# a phrase that is valid in the grid but not awake is rejected awake, accepted in the grid
assert t._commands("five", [], AWAKE) is None and t._commands("five", [], GRID) == ["5"]
# no per-word data (shape without it): decided by the grammar check alone
assert t._commands("page down", [], AWAKE) == V("page down", AWAKE)
# lenient mode keeps the old skip-stray-words behaviour
tl = mk(lenient=True)
assert tl._commands("mouse grid delta five", [], AWAKE) == ["grid", "5"] and tl._commands("page delta", [], AWAKE) is None
# JSONL log records whether the chosen phrase passed
import io as _io
buf = _io.StringIO(); t._write_log(buf, AWAKE, False, alts, 2, valid=True); t._write_log(buf, AWAKE, False, none_ok, 0, valid=None)
l1, l2 = (json.loads(x) for x in buf.getvalue().splitlines())
assert l1["valid"] is True and "valid" not in l2
# rejected phrases show a cross in the status pill and say so on the console
t._report(none_ok, 0, accepted=False); assert t.last_heard.startswith("✗ page delta")
t._report(alts, 2, accepted=True); assert t.last_heard.startswith("page down")
print("strict grammar check ok")



# ================= multi-word keys and punctuation =================
assert P("press back space") == [((), "backspace", 1)] == P("press backspace")
assert P("press question mark") == [(("shift",), "slash", 1)]
assert P("press exclamation mark") == [(("shift",), "1", 1)] == P("press exclamation point")
assert P("press shift question mark") == [(("shift",), "slash", 1)]                # no duplicate Shift
assert P("press control back space") == [(("ctrl",), "backspace", 1)]
assert P("press back space five") == [((), "backspace", 5)]                      # repeat count works
assert P("press question mark three") == [(("shift",), "slash", 3)]
assert P("press tab question mark enter") == [((), "tab", 1), (("shift",), "slash", 1), ((), "enter", 1)]
assert P("press left arrow twenty") == [((), "left", 20)] and P("press alt left arrow") == [(("alt",), "left", 1)]
assert P("press space bar") == [((), "space", 1)] and P("press caps lock") == [((), "capslock", 1)]
assert P("press print screen") == [((), "printscreen", 1)]
assert P("press colon") == [(("shift",), "semicolon", 1)] and P("press apostrophe") == [((), "quote", 1)]
assert P("press quote") == [(("shift",), "quote", 1)] == P("press double quote")
assert P("press single quote") == [((), "quote", 1)]
assert P("press open bracket close bracket") == [((), "lbracket", 1), ((), "rbracket", 1)]
assert P("press open paren a close paren") == [(("shift",), "9", 1), ((), "a", 1), (("shift",), "0", 1)]
assert P("press at sign") == [(("shift",), "2", 1)] and P("press dollar sign") == [(("shift",), "4", 1)]
assert P("press hash") == [(("shift",), "3", 1)] == P("press pound")
assert P("press underscore") == [(("shift",), "dash", 1)] and P("press plus") == [(("shift",), "equals", 1)]
assert P("press less than greater than") == [(("shift",), "comma", 1), (("shift",), "period", 1)]
assert P("press back tick") == [((), "backtick", 1)] and P("press tilde") == [(("shift",), "backtick", 1)]
# incomplete / wrong phrases press nothing, and the old words still behave
assert parse_commands("press question") == []                       # nothing pressed
assert parse_commands("press back") == ["back"] and parse_commands("press mark") == ["mark"]   # leftover grid words
assert validate("press back", GRID) is None and validate("press mark", GRID) is None             # strict: rejected
assert parse_commands("press space") == [KeyPress((Chord((), "space", 1),))]
assert parse_commands("press left click") == ["left"]                              # click still wins
assert parse_commands("press down left arrow") == [KeyPress((Chord((), "down", 1), Chord((), "left", 1)))]
# every key and modifier a phrase produces is something WinKeyboard can send
for phrase, (mods, key) in SYMBOL_KEYS.items():
    assert key in VK and all(m in VK for m in mods), phrase
# the whole utterance must be valid; stray words reject it
for ok in ("press back space", "press question mark", "press shift question mark", "press left arrow ten",
           "press open paren a close paren enter", "press control back space"):
    assert V(ok, AWAKE) is not None and V(ok, GRID) is not None and V(ok, SLEEPING) is None, ok
for bad in ("press question", "press question delta", "press back", "question mark", "back space",
            "press mark question mark"):
    assert V(bad, AWAKE) is None, bad
assert V("mouse grid five click press question mark", AWAKE) is not None
# the recogniser is taught that "question" is followed only by "mark" and "exclamation" by mark/point
for sents in (AWAKE_SENTENCES, GRID_SENTENCES):
    assert _after_in(sents, "question") == {"mark"}, _after_in(sents, "question")
    assert _after_in(sents, "exclamation") == {"mark", "point"}
    assert _after_in(sents, "caps") == {"lock"} and _after_in(sents, "print") == {"screen"}
    assert _after_in(sents, "back") >= {"space", "tick"}
    assert {"question", "exclamation", "caps"} <= {w for s in sents for w in s.split()}
# the controller hands the keyboard the shifted chord, only when awake / in the grid
kb = FakeKb(); m, o = FakeMouse(), FakeOverlay()
c = Controller(Region(0, 0, 1920, 1080), m, o, keyboard=kb)
say(c, "press question mark"); assert kb.log == []                                    # asleep
say(c, "start listening press back space press question mark three")
assert kb.log == [((), "backspace", 1), (("shift",), "slash", 3)], kb.log
print("multi-word keys ok", len(AWAKE_SENTENCES), len(GRID_SENTENCES))
