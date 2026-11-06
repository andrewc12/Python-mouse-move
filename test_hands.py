"""Tests for the hands process (voice_mouse_hands.py) and the client that talks to it.
No Windows needed: the Win* classes are replaced by fakes, and the socket part uses real loopback.

Run all:   python3 test_hands.py          Run some:   python3 test_hands.py socket token
"""
import ast
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback

import voice_mouse_hands as H
import voice_mouse_ui as UI
import voice_mouse as VM


# ---------------------------------------------------------------- fakes and helpers
class Rec:
    """One fake for mouse, keyboard, window, media and typer: remembers every call."""
    def __init__(self):
        self.log = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a: self.log.append((name, *a))


def make_hands(ui=None):
    r = Rec()
    return H.Hands(r, r, r, r, r, ui=ui), r


class FakeOverlay:
    def __init__(self, o): self.o, self.log = o, []
    def show(self, r, mark): self.log.append(("show", r, mark))
    def hide(self): self.log.append(("hide",))
    def raise_(self): self.log.append(("raise",))


class FakePill:
    def __init__(self, o): self.o, self.log, self.state, self.on_click = o, [], None, lambda: None
    def set(self, state): self.state = state; self.log.append(("set", state))
    def set_level(self, v): self.log.append(("level", v))
    def set_heard(self, t, seq=0): self.log.append(("heard", t, seq))
    def raise_(self): self.log.append(("raise",))


class Pumped:
    """A UiHost made of fakes, with its own thread standing in for Tk's main loop."""
    def __init__(self):
        self.ui = H.UiHost(make_overlay=FakeOverlay, make_pill=FakePill)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            self.ui.pump()
            time.sleep(0.002)

    def close(self):
        self.stop.set()
        self.thread.join(2)


class Running:
    """A real hands server on a loopback port with a token file, shut down afterwards."""
    def __init__(self, token="t" * 64, ui=False):
        self.pump = Pumped() if ui else None
        self.hands, self.rec = make_hands(self.pump.ui if ui else None)
        self.dir = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.dir.name, "hands.json")
        self.token = token
        self.srv = H.make_server(self.hands, token, 0, log=lambda *_: None)
        H.write_token_file(self.file, self.srv.server_address[1], token)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.pump:
            self.pump.close()
        self.srv.shutdown()
        self.srv.server_close()
        self.dir.cleanup()


def refused(hands, msg):
    out = hands.handle(msg)
    assert out["ok"] is False and out["error"], (msg, out)
    return out["error"]


# ---------------------------------------------------------------- validation
def test_every_operation_reaches_its_backend():
    h, r = make_hands()
    for msg in ({"op": "ping"},
                {"op": "move", "x": 5, "y": -7},
                {"op": "click", "button": "right", "double": True},
                {"op": "drag", "button": "left", "start": [1, 2], "end": [3.0, 4]},
                {"op": "scroll", "direction": "down", "amount": 5},
                {"op": "press", "mods": ["ctrl", "shift"], "key": "t", "count": 2},
                {"op": "press", "key": "enter"},
                {"op": "hold", "mods": ["ctrl"]}, {"op": "release", "mods": ["ctrl"]},
                {"op": "edit", "backspaces": 2, "text": "héllo\n"},
                {"op": "window", "action": "maximize"},
                {"op": "media", "action": "fast_forward"}):
        assert h.handle(msg) == {"ok": True}, msg
    assert r.log == [
        ("move", 5, -7), ("click", "right", True), ("drag", "left", (1, 2), (3, 4)),
        ("scroll", "down", 5), ("press", ["ctrl", "shift"], "t", 2), ("press", [], "enter", 1),
        ("hold", ["ctrl"]), ("release", ["ctrl"]), ("edit", 2, "héllo\n"),
        ("act", "maximize"), ("send", "fast_forward")], r.log


def test_bad_requests_are_refused_and_do_nothing():
    h, r = make_hands()
    bad = [
        "click", [], {}, {"op": 5}, {"op": "nope"}, {"op": "__init__"}, {"op": "_x"}, {"op": "handle"},
        {"op": "click", "button": "middle"}, {"op": "click", "button": "left", "double": "yes"},
        {"op": "move", "x": "1", "y": 2}, {"op": "move", "x": True, "y": 2}, {"op": "move", "x": 10 ** 9, "y": 0},
        {"op": "move", "x": 1}, {"op": "drag", "button": "left", "start": [1], "end": [2, 3]},
        {"op": "scroll", "direction": "sideways", "amount": 3}, {"op": "scroll", "direction": "up", "amount": 0},
        {"op": "scroll", "direction": "up", "amount": H.MAX_COUNT + 1},
        {"op": "press", "key": "f13"}, {"op": "press", "key": "a", "mods": ["super"]},
        {"op": "press", "key": "a", "mods": "ctrl"}, {"op": "press", "key": "a", "count": H.MAX_COUNT + 1},
        {"op": "press", "key": "a", "count": 1.5}, {"op": "press", "key": ["a"]},
        {"op": "hold", "mods": ["enter"]},
        {"op": "edit", "text": "x" * (H.MAX_TEXT + 1)}, {"op": "edit", "text": 5},
        {"op": "edit", "backspaces": -1, "text": ""}, {"op": "edit", "backspaces": H.MAX_BACKSPACES + 1},
        {"op": "window", "action": "close"}, {"op": "media", "action": "eject"},
    ]
    for msg in bad:
        refused(h, msg)
    assert r.log == []                                  # nothing reached Windows


def test_a_failing_backend_is_reported_not_raised():
    class Boom(Rec):
        def click(self, *a):
            raise OSError("access denied")
    b = Boom()
    out = H.Hands(b, b, b, b, b).handle({"op": "click", "button": "left"})
    assert out["ok"] is False and "access denied" in out["error"]


def test_key_tables_cover_what_the_main_program_uses():
    assert VM.VK is H.VK and VM.key_events is H.key_events and VM.WinTyper is H.WinTyper
    assert set(VM.MODIFIERS.values()) <= set(H.MODIFIER_KEYS)
    for key in list(VM.SPOKEN_KEYS.values()) + [k for _, k in VM.SYMBOL_KEYS.values()]:
        assert key in H.VK, key
    for action in VM.MEDIA_ACTIONS.values():
        assert action in H.MEDIA_ACTIONS, action
    for action in VM.WINDOW_COMMANDS.values():
        assert action in H.WINDOW_ACTIONS, action


# ---------------------------------------------------------------- the socket
def talk(port, *lines, read=1):
    s = socket.create_connection(("127.0.0.1", port), 3)
    s.settimeout(3)
    for ln in lines:
        s.sendall(ln if isinstance(ln, bytes) else (json.dumps(ln) + "\n").encode())
    f = s.makefile("rb")
    out = [f.readline() for _ in range(read)]
    s.close()
    return out


def hello(token):
    return {"op": "hello", "token": token}


def test_socket_listens_on_loopback_only():
    with Running() as run:
        assert run.srv.server_address[0] == "127.0.0.1"


def test_socket_requires_the_token_first():
    with Running(token="s3cret") as run:
        port = run.srv.server_address[1]
        assert json.loads(talk(port, {"op": "click", "button": "left"})[0])["ok"] is False
        assert json.loads(talk(port, hello("wrong"))[0])["ok"] is False
        assert json.loads(talk(port, hello(""))[0])["ok"] is False
        assert json.loads(talk(port, {"op": "hello"})[0])["ok"] is False
        assert json.loads(talk(port, b"garbage\n")[0])["ok"] is False
        assert json.loads(talk(port, b'["hello"]\n')[0])["ok"] is False
        assert run.rec.log == []
        good = talk(port, hello("s3cret"), {"op": "click", "button": "left"}, read=2)
        assert [json.loads(g)["ok"] for g in good] == [True, True]
        assert run.rec.log == [("click", "left", False)]


def test_socket_refuses_oversized_and_non_json_messages():
    with Running() as run:
        port = run.srv.server_address[1]
        out = talk(port, hello(run.token), b"x" * (H.MAX_LINE + 10) + b"\n", read=2)
        assert json.loads(out[1])["ok"] is False
        out = talk(port, hello(run.token), b"not json\n", read=2)
        assert json.loads(out[1])["ok"] is False
        assert run.rec.log == []


def test_socket_serves_several_clients_in_turn():
    with Running() as run:
        port = run.srv.server_address[1]
        for _ in range(3):
            talk(port, hello(run.token), {"op": "media", "action": "stop"}, read=2)
        assert run.rec.log == [("send", "stop")] * 3


def test_token_file_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", "hands.json")
        H.write_token_file(path, 4242, "abc")
        info = H.read_token_file(path)
        assert info["port"] == 4242 and info["token"] == "abc"
        with open(path, "w") as f:
            f.write('{"port": "x"}')
        try:
            H.read_token_file(path)
        except ValueError:
            pass
        else:
            raise AssertionError("bad file accepted")


def test_idle_watch_stops_the_server_only_when_unused():
    class Srv:
        clients, last_client = 0, 0.0
    srv, stopped, now = Srv(), [], [0.0]

    def sleep(_):
        now[0] += 1.0
        if len(stopped) == 0 and now[0] == 5:
            srv.clients = 1                    # a client connects for a while
        if now[0] == 20:
            srv.clients, srv.last_client = 0, now[0]
        if now[0] > 100:
            raise AssertionError("never stopped")
    t = H.watch_idle(srv, 10.0, sleep=sleep, clock=lambda: now[0], stop=lambda: stopped.append(now[0]))
    t.join(3)
    assert stopped and stopped[0] > 30, stopped          # 10 s after the client left at t=20
    assert H.watch_idle(Srv(), 0).join(1) is None        # 0 = never: the thread ends at once


# ---------------------------------------------------------------- the client
def client_for(run, **kw):
    return VM.HandsClient(run.file, **kw)


def test_client_and_stand_ins_drive_the_hands():
    with Running() as run:
        c = client_for(run).open()
        VM.RemoteMouse(c).move(10.7, 20)
        VM.RemoteMouse(c).click("left", True)
        VM.RemoteMouse(c).drag("right", (1, 2), (3, 4))
        VM.RemoteMouse(c).scroll("up", 3)
        VM.RemoteKeyboard(c).press(("ctrl",), "c", 2)
        VM.RemoteKeyboard(c).hold(["shift"]); VM.RemoteKeyboard(c).release(["shift"])
        VM.RemoteWindow(c).act("minimize")
        VM.RemoteMedia(c).send("next")
        VM.RemoteTyper(c).edit(1, "hi")
        c.close()
        assert run.rec.log == [
            ("move", 10, 20), ("click", "left", True), ("drag", "right", (1, 2), (3, 4)), ("scroll", "up", 3),
            ("press", ["ctrl"], "c", 2), ("hold", ["shift"]), ("release", ["shift"]), ("act", "minimize"),
            ("send", "next"), ("edit", 1, "hi")], run.rec.log


def test_client_reports_refusals_and_wrong_tokens():
    with Running() as run:
        c = client_for(run).open()
        try:
            c.call("press", mods=[], key="f13", count=1)
        except VM.HandsError as e:
            assert "key" in str(e)
        else:
            raise AssertionError("refusal not raised")
        c.call("ping")                                        # still usable afterwards
        H.write_token_file(run.file, run.srv.server_address[1], "other")
        try:
            client_for(run).open()
        except VM.HandsError as e:
            assert "refused" in str(e)
        else:
            raise AssertionError("wrong token accepted")


def test_client_reconnects_when_the_connection_dropped():
    with Running() as run:
        c = client_for(run).open()
        c.sock.shutdown(socket.SHUT_RDWR)                     # the link died between requests
        c.call("move", x=1, y=2)
        assert run.rec.log == [("move", 1, 2)]


def test_client_does_not_resend_when_only_the_reply_was_lost():
    with Running() as run:
        c = client_for(run, timeout=0.3).open()
        slow = threading.Event()
        orig = run.hands.op_click
        run.hands.op_click = lambda msg: (orig(msg), slow.wait(1), None)[-1]
        try:
            c.call("click", button="left", double=False)
        except VM.HandsError as e:
            assert "lost contact" in str(e)
        else:
            raise AssertionError("expected a timeout")
        slow.set()
        time.sleep(0.2)
        assert run.rec.log.count(("click", "left", False)) == 1


def test_client_error_when_the_hands_are_gone():
    with tempfile.TemporaryDirectory() as d:
        c = VM.HandsClient(os.path.join(d, "missing.json"))
        try:
            c.call("ping")
        except VM.HandsError as e:
            assert "cannot reach" in str(e)
        else:
            raise AssertionError("no error")


def test_connect_hands_retries_then_explains():
    now, naps = [0.0], []

    def sleep(s):
        naps.append(s)
        now[0] += s

    class Late:
        tries = 0

        def __init__(self, path):
            Late.tries += 1

        def open(self):
            if Late.tries < 4:
                raise FileNotFoundError("not yet")
            return "connected"
    assert VM.connect_hands("f", wait=5, sleep=sleep, clock=lambda: now[0], client_factory=Late) == "connected"
    assert len(naps) == 3

    class Never:
        def __init__(self, path): pass
        def open(self): raise FileNotFoundError("nope")
    try:
        VM.connect_hands("f.json", wait=1, sleep=sleep, clock=lambda: now[0], client_factory=Never)
    except VM.HandsError as e:
        assert "f.json" in str(e) and "--admin-hands" in str(e)
    else:
        raise AssertionError("no error")


def test_remote_typer_splits_big_edits():
    class Fake:
        def __init__(self): self.calls = []
        def call(self, op, **kw): self.calls.append((op, kw))
    f = Fake()
    VM.RemoteTyper(f).edit(H.MAX_BACKSPACES + 3, "a" * (H.MAX_TEXT * 2 + 1))
    typed = "".join(kw["text"] for _, kw in f.calls)
    assert typed == "a" * (H.MAX_TEXT * 2 + 1) and sum(kw["backspaces"] for _, kw in f.calls) == H.MAX_BACKSPACES + 3
    assert all(len(kw["text"]) <= H.MAX_TEXT and kw["backspaces"] <= H.MAX_BACKSPACES for _, kw in f.calls)


# ---------------------------------------------------------------- the point of the split
def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods = set()
    for node in ast.walk(tree):                              # every import, including ones inside functions
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_elevated_files_import_only_the_standard_library():
    here = os.path.dirname(os.path.abspath(H.__file__))
    for name in ("voice_mouse_hands.py", "voice_mouse_ui.py"):
        mods = _imports(os.path.join(here, name)) - {"voice_mouse_ui"}      # the hands may import their drawing module
        outside = {m for m in mods if m not in sys.stdlib_module_names}
        assert not outside, f"{name} must stay standard-library only, but imports {outside}"
        assert not {"vosk", "sherpa_onnx", "numpy", "sounddevice", "voice_mouse"} & mods, name


def test_elevated_code_is_small():
    here = os.path.dirname(os.path.abspath(H.__file__))
    n = sum(sum(1 for _ in open(os.path.join(here, f), encoding="utf-8")) for f in ("voice_mouse_hands.py", "voice_mouse_ui.py"))
    assert n < 1300, n                                       # keep what runs with privileges reviewable


def test_supervisor_gives_its_child_the_running_hands():
    import subprocess
    seen = []
    real_run, argv = subprocess.run, sys.argv
    subprocess.run = lambda cmd, *a, **k: seen.append(cmd) or type("R", (), {"returncode": 0})()
    sys.argv = ["voice_mouse.py", "--admin-hands", "--no-media"]
    try:
        with io.StringIO() as buf:
            old, sys.stdout = sys.stdout, buf
            try:
                assert VM.supervise() == 0
            finally:
                sys.stdout = old
    finally:
        subprocess.run, sys.argv = real_run, argv
    cmd = seen[0]
    assert "--use-hands" in cmd and "--admin-hands" not in cmd and "--supervised-by" in cmd, cmd


def test_find_hands_exe_prefers_the_installed_copy():
    with tempfile.TemporaryDirectory() as pf, tempfile.TemporaryDirectory() as here:
        saved = os.environ.get("ProgramFiles")
        os.environ["ProgramFiles"] = pf
        try:
            assert VM.find_hands_exe(here) == os.path.join(pf, "VoiceMouse", "hands", "voice_mouse_hands.exe")   # none yet
            beside = os.path.join(here, "voice_mouse_hands.exe")
            open(beside, "w").close()
            assert VM.find_hands_exe(here) == beside
            os.makedirs(os.path.join(here, "hands"))
            folder = os.path.join(here, "hands", "voice_mouse_hands.exe")
            open(folder, "w").close()
            assert VM.find_hands_exe(here) == folder
            installed = os.path.join(pf, "VoiceMouse", "hands", "voice_mouse_hands.exe")
            os.makedirs(os.path.dirname(installed))
            open(installed, "w").close()
            assert VM.find_hands_exe(here) == installed                                  # signed copy wins
        finally:
            os.environ.pop("ProgramFiles", None) if saved is None else os.environ.__setitem__("ProgramFiles", saved)


def test_ui_access_check_is_safe_off_windows():
    assert H.has_ui_access() in (True, False)


def test_hands_command_line():
    cmd = VM.hands_command("C:/x/hands.json")
    assert cmd[-2:] == ["--token-file", "C:/x/hands.json"] and "--idle-exit" not in cmd     # runs until closed
    assert os.path.basename(cmd[-3]) == "voice_mouse_hands.py"
    assert VM.hands_command("f", 60)[-2:] == ["--idle-exit", "60"]                          # only when asked


def test_hands_log_file_gets_timestamped_lines_and_rotates():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", "hands.log")
        old = sys.stdout, sys.stderr
        try:
            H.open_log(path)
            print("one"); print("two", end=""); print(" three")
        finally:
            sys.stdout, sys.stderr = old
        lines = open(path, encoding="utf-8").read().splitlines()
        assert lines[-2].endswith(" one") and lines[-1].endswith("two three") and lines[-1][:2] == "20", lines
        with open(path, "a") as f:
            f.write("x" * 100)
        try:
            H.open_log(path, max_bytes=50)
        finally:
            sys.stdout, sys.stderr = old
        assert os.path.exists(path + ".old")


def test_default_models_folder_is_shared_and_nothing_is_bundled():
    saved = {k: os.environ.get(k) for k in ("VOICE_MOUSE_MODELS", "LOCALAPPDATA")}
    try:
        os.environ["VOICE_MOUSE_MODELS"] = os.path.join(tempfile.gettempdir(), "vm_models")
        assert VM.default_models_dir() == os.path.abspath(os.environ["VOICE_MOUSE_MODELS"])
        del os.environ["VOICE_MOUSE_MODELS"]
        os.environ["LOCALAPPDATA"] = "C:/Users/me/AppData/Local"
        assert VM.default_models_dir().replace("\\", "/").endswith("AppData/Local/voice_mouse/models")
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    here = os.path.dirname(os.path.abspath(__file__))
    for bat in ("build.bat",):
        text = open(os.path.join(here, bat), encoding="utf-8").read().lower()
        assert "include-data-dir" not in text, "models must not be packed into the exes"


def test_ensure_model_uses_the_shared_folder_and_never_downloads_when_present():
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, VM.MODEL_NAME)
        os.makedirs(target)
        assert VM.ensure_model(None, d) == target
        assert VM.ensure_model("explicit", d) == "explicit"


def test_download_models_fetches_each_model_once():
    got = []
    real_model, real_sherpa = VM.ensure_model, VM.ensure_sherpa_model
    VM.ensure_model = lambda p, d=None: got.append(("vosk", d)) or "v"
    VM.ensure_sherpa_model = lambda n, d: got.append((n, d)) or "s"
    try:
        VM.download_models("M", VM.DictationOptions(draft_model="small.en"))      # a Whisper draft: not fetched here
        assert got == [("vosk", "M"), (VM.DEFAULT_FINAL, "M")], got
        got.clear()
        VM.download_models("M", dictation=False)
        assert got == [("vosk", "M")]
    finally:
        VM.ensure_model, VM.ensure_sherpa_model = real_model, real_sherpa


# ---------------------------------------------------------------- drawing in the hands
def test_ui_ops_are_refused_without_a_ui():
    h, _ = make_hands()
    for op in ("ui_init", "overlay_show", "overlay_hide", "pill"):
        assert "no screen drawing" in refused(h, {"op": op})


def test_overlay_and_pill_ops_reach_the_ui():
    p = Pumped()
    try:
        h, _ = make_hands(p.ui)
        assert h.handle({"op": "ui_init", "corner": "top-left", "minor_grid": False, "inset": 2,
                         "adapt": True, "keep_on_top": True}) == {"ok": True}
        assert p.ui.overlay.o["corner"] == "top-left" and p.ui.overlay.o["inset"] == 2
        assert h.handle({"op": "overlay_show", "region": [0, 0, 1920, 1080], "mark": [5, 6]}) == {"ok": True}
        assert p.ui.overlay.log == [("show", UI.Region(0, 0, 1920, 1080), (5, 6))]
        h.handle({"op": "overlay_show", "region": [1, 2, 3.5, 4], "mark": None})
        assert p.ui.overlay.log[-1] == ("show", UI.Region(1, 2, 3.5, 4), None)
        h.handle({"op": "overlay_hide"})
        assert p.ui.overlay.log[-1] == ("hide",)
        out = h.handle({"op": "pill", "state": "grid", "level": 0.4, "heard": "mouse grid", "seq": 3})
        assert out == {"ok": True, "events": []}
        time.sleep(0.05)
        assert p.ui.pill.log == [("set", "grid"), ("level", 0.4), ("heard", "mouse grid", 3)], p.ui.pill.log
        p.ui.pill.on_click()                               # the user clicked the box
        assert h.handle({"op": "pill", "level": 0.1})["events"] == ["click"]
        assert h.handle({"op": "pill", "level": 0.1})["events"] == []          # delivered once
    finally:
        p.close()


def test_pill_updates_are_merged_when_the_ui_thread_is_busy():
    ui = H.UiHost(make_overlay=FakeOverlay, make_pill=FakePill)
    ui.overlay, ui.pill = FakeOverlay({}), FakePill({})
    for lvl in (0.1, 0.2, 0.9):
        ui.update_pill({"level": lvl})
    ui.update_pill({"state": "awake"})
    ui.pump()
    assert ui.pill.log == [("set", "awake"), ("level", 0.9)]               # one application of the latest values
    ui.pump()
    assert len(ui.pill.log) == 2


def test_ui_requests_are_validated():
    p = Pumped()
    try:
        h, _ = make_hands(p.ui)
        for msg in ({"op": "ui_init", "corner": "middle", "minor_grid": True, "inset": 1, "adapt": True, "keep_on_top": True},
                    {"op": "ui_init", "corner": "top-left", "minor_grid": "yes", "inset": 1, "adapt": True, "keep_on_top": True},
                    {"op": "ui_init", "corner": "top-left", "minor_grid": True, "inset": 99, "adapt": True, "keep_on_top": True},
                    {"op": "overlay_show", "region": [1, 2, 3]}, {"op": "overlay_show", "region": "all"},
                    {"op": "overlay_show", "region": [0, 0, 10 ** 9, 5]},
                    {"op": "overlay_show", "region": [0, 0, 5, 5], "mark": [1]},
                    {"op": "pill", "state": "angry"}, {"op": "pill", "level": 2}, {"op": "pill", "level": "x"},
                    {"op": "pill", "heard": 5}, {"op": "pill", "heard": "x" * (H.MAX_HEARD + 1)}):
            refused(h, msg)
        assert p.ui.overlay is None or p.ui.overlay.log == []
    finally:
        p.close()


def test_a_ui_that_never_answers_is_reported_not_hung():
    ui = H.UiHost(make_overlay=FakeOverlay, make_pill=FakePill)            # nobody calls pump()
    h, _ = make_hands(ui)
    t0 = time.monotonic()
    ui_submit = ui.submit
    ui.submit = lambda fn, timeout=0.2: ui_submit(fn, timeout)
    out = h.handle({"op": "overlay_hide"})
    assert out["ok"] is False and "UI thread" in out["error"] and time.monotonic() - t0 < 3


def test_hello_says_whether_the_hands_can_draw():
    with Running(ui=True) as run:
        assert VM.HandsClient(run.file).open().ui is True
    with Running(ui=False) as run:
        assert VM.HandsClient(run.file).open().ui is False


def test_remote_overlay_and_pill_end_to_end():
    with Running(ui=True) as run:
        c = VM.HandsClient(run.file).open()
        clicks = []
        overlay, pill = VM.start_remote_ui(c, "bottom-left", True, 1, True, True)
        pill.on_click = lambda: clicks.append(1)
        assert run.pump.ui.pill.o["corner"] == "bottom-left"
        overlay.show(UI.Region(0, 0, 100, 90), (3, 4))
        overlay.hide()
        assert run.pump.ui.overlay.log == [("show", UI.Region(0, 0, 100, 90), (3, 4)), ("hide",)]
        pill.set("awake")
        pill.set_level(0.5); pill.set_heard("left click", 1); pill.flush()
        time.sleep(0.05)
        assert ("set", "awake") in run.pump.ui.pill.log and ("heard", "left click", 1) in run.pump.ui.pill.log
        run.pump.ui.pill.on_click()
        pill.flush()
        assert clicks == [1]
        n = len(run.pump.ui.pill.log)
        pill.flush(); time.sleep(0.05)                       # same phrase again: only the level is resent
        assert [e for e in run.pump.ui.pill.log[n:] if e[0] == "heard"] == []


def test_ui_settings_are_sent_again_after_a_reconnect():
    with Running(ui=True) as run:
        c = VM.HandsClient(run.file).open()
        overlay, pill = VM.start_remote_ui(c, "top-right", False, 3, False, True)
        pill.set("grid")
        first = run.pump.ui.pill
        c.sock.shutdown(socket.SHUT_RDWR)                    # link drops (or the main program restarts)
        overlay.show(UI.Region(0, 0, 10, 10), None)
        assert run.pump.ui.pill is not first                 # ui_init was repeated by the reconnect hook
        assert run.pump.ui.pill.state == "grid" and run.pump.ui.overlay.o["inset"] == 3
        assert run.pump.ui.overlay.log[-1][0] == "show"


def test_remote_pill_reports_a_lost_link_without_raising():
    class Dead:
        def call(self, *a, **k): raise VM.HandsError("gone")
    pill = VM.RemotePill(Dead())
    pill.set("awake"); pill.flush()                          # must not raise: the status box is not worth a crash


def test_main_program_and_ui_module_share_the_same_region_and_states():
    assert VM.Region is UI.Region and VM.StatusPill is UI.StatusPill and VM.Overlay is UI.Overlay
    assert (VM.SLEEPING, VM.AWAKE, VM.GRID, VM.DICTATE) == UI.STATES
    assert tuple(UI.StatusPill.COLORS) == UI.STATES


def test_install_and_build_scripts_match_the_ui_access_design():
    here = os.path.dirname(os.path.abspath(__file__))
    read = lambda n: open(os.path.join(here, n), encoding="utf-8").read()
    build = read("build.bat")
    assert "--windows-uac-uiaccess" in build and "--standalone" in build and "tk-inter" in build
    assert "dist\\hands" in build and "include-data-dir" not in build
    ps = read("install_hands.ps1")
    for needle in ("ProgramFiles", "Set-AuthenticodeSignature", "TrustedPublisher",
                   "'Root'", "Startup", "ExecutionTimeLimit"):
        assert needle in ps, needle
    assert r"VoiceMouse\hands" in ps                              # where find_hands_exe() looks first
    assert VM.find_hands_exe(os.path.join(here, "nowhere")).endswith("voice_mouse_hands.exe")
    for bat in ("install_hands_signed.bat", "install_hands_task.bat"):
        text = read(bat)
        assert "install_hands.ps1" in text and "net session" in text, bat
    assert "-Signed" in read("install_hands_signed.bat") and "-Signed" not in read("install_hands_task.bat")


def _run_all(only=()):
    tests = [(n, f) for n, f in sorted(globals().items(), key=lambda kv: getattr(kv[1], "__code__", None) and kv[1].__code__.co_firstlineno or 0)
             if n.startswith("test_") and callable(f) and (not only or any(w in n for w in only))]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except Exception:
            failed.append(name)
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed or not tests else 0


if __name__ == "__main__":
    sys.exit(_run_all(sys.argv[1:]))
