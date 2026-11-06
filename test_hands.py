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


def make_hands():
    r = Rec()
    return H.Hands(r, r, r, r, r), r


class Running:
    """A real hands server on a loopback port with a token file, shut down afterwards."""
    def __init__(self, token="t" * 64):
        self.hands, self.rec = make_hands()
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
        run.hands.op_click = lambda msg: (orig(msg), slow.wait(1))
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
def test_hands_file_imports_only_the_standard_library():
    path = os.path.join(os.path.dirname(os.path.abspath(H.__file__)), "voice_mouse_hands.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods = set()
    for node in ast.walk(tree):                              # every import, including ones inside functions
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.add(node.module.split(".")[0])
    outside = {m for m in mods if m not in sys.stdlib_module_names}
    assert not outside, f"the elevated file must stay standard-library only, but imports {outside}"
    assert not {"vosk", "sherpa_onnx", "numpy", "sounddevice", "voice_mouse"} & mods


def test_hands_file_is_small():
    path = os.path.join(os.path.dirname(os.path.abspath(H.__file__)), "voice_mouse_hands.py")
    assert sum(1 for _ in open(path, encoding="utf-8")) < 700       # keep it reviewable


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
