"""Logic tests for voice_dictate (no Windows, Tk, Whisper or microphone needed).

Run all:        python3 test_dictate.py           (named results, exit code 1 on any failure)
Run some:       python3 test_dictate.py segment focus   (tests whose name contains any word)
With pytest:    python3 -m pytest test_dictate.py
"""
import queue
import sys
import threading
import traceback

from voice_dictate import *


# ---------------------------------------------------------------- fakes and helpers
class FakeTypist:
    """Applies edits to a text buffer, so tests assert what the user would actually see."""
    def __init__(self):
        self.text, self.log = "", []

    def edit(self, back, add):
        assert back <= len(self.text), (back, self.text)
        self.text = self.text[:len(self.text) - back] + add
        self.log.append((back, add))


def mk(**kw):
    t = FakeTypist()
    hwnd = [1]
    stops, notes = [], []
    d = Dictator(t, foreground=lambda: hwnd[0], on_stop=lambda: stops.append(1), notice=notes.append, **kw)
    return d, t, hwnd, stops, notes


def say(d, uid, draft=None, final=None):
    d.begin(uid)
    if draft is not None:
        d.draft(uid, draft)
    if final is not None:
        d.final(uid, final)


def frames(pattern):
    """'s' = speech frame, '.' = silence; each frame is one distinguishable byte."""
    return [(bytes([i % 250 + 1]), c == "s") for i, c in enumerate(pattern)]


def run_seg(seg, pattern):
    ev = []
    for frame, speech in frames(pattern):
        ev += seg.feed(frame, speech)
    return ev


# ---------------------------------------------------------------- tests
def test_key_events():
    assert key_events(0, "") == []
    assert key_events(2, "") == [(VK_BACK, 0, 0), (VK_BACK, 0, KEYUP)] * 2
    assert key_events(0, "a") == [(0, ord("a"), UNICODE), (0, ord("a"), UNICODE | KEYUP)]
    assert key_events(0, "\n") == [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYUP)]
    assert key_events(0, "\r\n") == key_events(0, "\n")
    ev = key_events(1, "é")
    assert ev[2] == (0, 0xE9, UNICODE) and len(ev) == 4
    emoji = key_events(0, "\U0001F600")                      # outside the BMP: two UTF-16 units
    assert [e[1] for e in emoji[::2]] == [0xD83D, 0xDE00] and len(emoji) == 4
    assert key_events(1, "hi")[:2] == [(VK_BACK, 0, 0), (VK_BACK, 0, KEYUP)]    # backspaces come first


def test_clean_transcript():
    assert clean_transcript("  Hello   world. ") == "Hello world."
    assert clean_transcript("") == "" and clean_transcript(None) == ""
    for noise in ("[BLANK_AUDIO]", "(music)", "[ Silence ]", "You", "you.", "Thanks for watching!",
                  "Thank you for watching.", "Please subscribe"):
        assert clean_transcript(noise) == "", noise
    assert clean_transcript("Thank you.") == "Thank you."          # a real sentence is kept
    assert clean_transcript("you know what") == "you know what"
    assert squash_repeats("the the the the the end") == "the the the end"
    assert clean_transcript("go go go go go go") == "go go go"
    assert clean_draft("Hello world.") == "Hello world" and clean_draft("Hello, ...") == "Hello"
    assert clean_draft("Really?") == "Really?" and clean_draft("[BLANK_AUDIO]") == ""


def test_commands():
    assert parse_command("New line.") == "newline" and parse_command("newline") == "newline"
    assert parse_command("New paragraph") == "paragraph"
    assert parse_command("Scratch that!") == "scratch" and parse_command("delete that") == "scratch"
    assert parse_command("Stop listening.") == "stop" and parse_command("stop dictation") == "stop"
    assert parse_command("on the new line") is None and parse_command("hello") is None
    assert parse_command("") is None
    for held in ("new", "New line", "scratch", "stop", "delete that"):
        assert is_command_prefix(held), held
    for typed in ("hello", "new line please", "stop sign", "", "new lines"):
        assert not is_command_prefix(typed), typed


def test_segmenter_start_end_and_preroll():
    seg = Segmenter()
    ev = run_seg(seg, "." * 20 + "s" * 10 + "." * 25)
    assert [e[0] for e in ev] == ["start", "end"] and ev[0] == ("start", 1)
    uid, pcm, reason = ev[1][1], ev[1][2], ev[1][3]
    # 10 pre-roll frames (7 silence + the 3 speech frames that triggered it) + 7 more speech
    # + 5 frames of trailing silence kept (150 ms) of the 20 that ended it
    assert uid == 1 and reason == "pause" and len(pcm) == 22, len(pcm)
    assert pcm[0] == frames("." * 20 + "s" * 10)[13][0][0]          # starts at the pre-roll, not earlier
    assert not seg.active


def test_segmenter_ignores_a_blip_and_cancels_short_speech():
    seg = Segmenter()
    assert run_seg(seg, "." * 5 + "s" + "." * 5 + "s" + "." * 20) == []          # never 3 of 5: no start
    ev = run_seg(Segmenter(), "sss" + "." * 25)                                   # starts, but only 90 ms
    assert [e[0] for e in ev] == ["start", "cancel"], ev


def test_segmenter_soft_and_max_cuts():
    seg = Segmenter(soft_after_s=1.0, soft_silence_ms=300, max_s=5.0)
    ev = run_seg(seg, "s" * 40 + "." * 10 + "s" * 10)                             # 1.2 s, then a short gap
    kinds = [(e[0], e[1]) for e in ev]
    assert kinds[:2] == [("start", 1), ("end", 1)] and ev[1][3] == "soft", ev[:3]
    assert kinds[2] == ("start", 2)                                                # the rest is a new phrase
    seg = Segmenter(max_s=5.0)
    ev = run_seg(seg, "s" * 200)
    assert [(e[0], e[1]) for e in ev] == [("start", 1), ("end", 1), ("start", 2)] and ev[1][3] == "max"
    assert seg.active and seg.uid == 2                                             # carried straight on


def test_segmenter_force_end():
    seg = Segmenter()
    run_seg(seg, "s" * 20)
    ev = seg.force_end()
    assert ev[0][0] == "end" and ev[0][3] == "flush" and not seg.active
    assert seg.force_end() == []


def _pipe(clock, **kw):
    drafts, finals, discards, out = [], [], [], queue.Queue()
    p = Pipeline(lambda f: f == b"S", lambda uid, pcm: drafts.append((uid, len(pcm))),
                 lambda uid, pcm: finals.append((uid, len(pcm))), out,
                 Segmenter(frame_ms=30), clock=clock, discard_draft=discards.append, **kw)
    return p, drafts, finals, discards, out


def test_pipeline_drafts_then_one_final():
    now = [0.0]
    p, drafts, finals, discards, out = _pipe(lambda: now[0])
    p.set_active(True)
    for f in [b"q"] * 3 + [b"S"] * 40 + [b"q"] * 25:
        now[0] += 0.03
        p.feed(f)
    assert out.get_nowait() == ("start", 1) and out.empty()
    assert len(drafts) >= 3 and all(u == 1 for u, _ in drafts)
    assert [n for _, n in drafts] == sorted(n for _, n in drafts)                  # growing audio
    assert drafts[0][1] >= 15                                                       # not before 0.45 s (15 one-byte frames)
    assert len(finals) == 1 and finals[0][0] == 1 and discards == [1]
    n = len(drafts)
    for f in [b"q"] * 10:
        now[0] += 0.03
        p.feed(f)
    assert len(drafts) == n                                                         # nothing after the end


def test_pipeline_cancel_pause_and_flush():
    now = [0.0]
    p, drafts, finals, discards, out = _pipe(lambda: now[0])
    for f in [b"S"] * 5:
        p.feed(f)
    assert out.empty()                                                              # inactive: ignored
    p.set_active(True)
    for f in [b"S"] * 3 + [b"q"] * 25:
        now[0] += 0.03
        p.feed(f)
    assert [out.get_nowait(), out.get_nowait()] == [("start", 1), ("cancel", 1)] and not finals
    for f in [b"S"] * 20:
        now[0] += 0.03
        p.feed(f)
    p.set_active(False)                                                             # pause mid-sentence
    assert len(finals) == 1 and finals[0][0] == 2 and not p.seg.active
    p.feed(b"S")
    assert len(finals) == 1


def test_pipeline_without_drafts():
    now = [0.0]
    p, _, finals, _, out = _pipe(lambda: now[0])
    p.submit_draft = None
    p.set_active(True)
    for f in [b"S"] * 30 + [b"q"] * 25:
        p.feed(f)
    assert len(finals) == 1


def test_pipeline_idle_timeout():
    now = [0.0]
    p, drafts, finals, discards, out = _pipe(lambda: now[0], idle_s=10.0)
    p.set_active(True)

    def run(frames, step=0.03):
        for f in frames:
            now[0] += step
            p.feed(f)

    def idles():
        n = 0
        while not out.empty():
            n += out.get_nowait() == ("idle",)
        return n
    run([b"q"] * 300)                                                              # 9 s of silence
    assert idles() == 0
    run([b"q"] * 100)                                                              # past 10 s
    assert idles() == 1
    run([b"q"] * 100)                                                              # one per quiet spell
    assert idles() == 0
    run([b"q"] * 250)
    assert idles() == 1                                                            # ... then again after 10 s more
    p.set_active(False)
    now[0] += 100
    p.set_active(True)
    run([b"q"] * 100)
    assert idles() == 0                                                            # resuming restarts the clock


def test_pipeline_idle_timeout_speech_resets_and_off_by_default():
    now = [0.0]
    p, *_rest, out = _pipe(lambda: now[0], idle_s=5.0)
    p.set_active(True)
    for _ in range(20):                                                            # a phrase every ~4 s
        for f in [b"S"] * 20 + [b"q"] * 100:
            now[0] += 0.03
            p.feed(f)
    assert not any(e == ("idle",) for e in list(out.queue))
    now2 = [0.0]
    p2, *_r, out2 = _pipe(lambda: now2[0])                                         # idle_s default 0 = never
    p2.set_active(True)
    for _ in range(5000):
        now2[0] += 0.03
        p2.feed(b"q")
    assert not any(e == ("idle",) for e in list(out2.queue))


def test_dictator_types_and_corrects_in_place():
    d, t, *_ = mk()
    d.begin(1)
    d.draft(1, "hello")
    assert t.text == "hello"
    d.draft(1, "hello wor")
    assert t.text == "hello wor" and t.log[-1] == (0, " wor")                       # only the new tail typed
    d.draft(1, "hello word.")                                                       # trailing '.' not typed
    assert t.text == "hello word" and t.log[-1] == (0, "d")
    d.draft(1, "hello world")
    assert t.log[-1] == (1, "ld")                                                   # minimal fix: 1 back, "ld"
    d.final(1, "Hello, world.")
    assert t.text == "Hello, world."
    assert d.parts == [] and d.shown == "" and d.history == ["Hello, world."]


def test_dictator_spacing_between_phrases():
    d, t, *_ = mk()
    say(d, 1, final="Hello world.")
    say(d, 2, draft="how are")
    assert t.text == "Hello world. how are"
    d.final(2, "How are you?")
    assert t.text == "Hello world. How are you?"
    say(d, 3, final=", fine")
    say(d, 4, final="thanks")
    assert t.text == "Hello world. How are you?, fine thanks"                       # no space before a comma
    d2, t2, *_ = mk()
    say(d2, 1, final="(")
    say(d2, 2, final="aside")
    assert t2.text == "(aside"


def test_dictator_late_final_fixes_earlier_phrase():
    d, t, *_ = mk()
    d.begin(1); d.draft(1, "first part")
    d.begin(2); d.draft(2, "second")
    assert t.text == "first part second"
    d.final(1, "First part.")                                                       # arrives after 2 started
    assert t.text == "First part. second" and d.history == ["First part."]
    d.final(2, "Second one.")
    assert t.text == "First part. Second one."


def test_dictator_final_waits_for_earlier_undecided_phrase():
    d, t, *_ = mk()
    d.begin(1); d.draft(1, "aaa")
    d.begin(2); d.draft(2, "bbb")
    d.final(2, "Bbb.")                                                              # 2 decided before 1
    assert t.text == "aaa Bbb." and d.history == []                                 # not settled behind 1
    d.final(1, "Aaa.")
    assert t.text == "Aaa. Bbb." and d.history == ["Aaa.", " Bbb."]


def test_dictator_ignores_stale_events():
    d, t, *_ = mk()
    say(d, 1, final="Done.")
    d.draft(1, "zzz")                                                               # draft after its final
    d.final(1, "again")
    d.draft(7, "never began")
    assert t.text == "Done."
    d.begin(2); d.draft(2, "abc"); d.cancel(2)
    assert t.text == "Done." and d.parts == []


def test_dictator_empty_final_and_noise():
    d, t, *_ = mk()
    d.begin(1); d.draft(1, "hmm")
    d.final(1, "[BLANK_AUDIO]")                                                     # model changed its mind
    assert t.text == "" and d.parts == [] and d.history == []
    say(d, 2, final="You")                                                          # hallucination
    assert t.text == ""


def test_dictator_new_line_and_paragraph():
    d, t, *_ = mk()
    say(d, 1, final="Dear Sam,")
    say(d, 2, draft="new", final="New line.")                                       # "new" is held, never typed
    assert t.text == "Dear Sam,\n" and all("new" not in a.lower() for _, a in t.log)
    say(d, 3, final="Thanks.")
    assert t.text == "Dear Sam,\nThanks."                                           # no space after a newline
    say(d, 4, final="new paragraph")
    say(d, 5, final="Bye")
    assert t.text == "Dear Sam,\nThanks.\n\nBye"
    say(d, 6, draft="new line please")                                              # not a command: typed
    assert t.text.endswith("Bye new line please")


def test_dictator_scratch_that():
    d, t, _, _, notes = mk()
    say(d, 1, final="One.")
    say(d, 2, final="Two.")
    say(d, 3, final="scratch that")
    assert t.text == "One." and notes[-1] == "scratched" and d.committed_last == "."
    say(d, 4, final="Three.")
    assert t.text == "One. Three."
    say(d, 5, final="delete that"); say(d, 6, final="delete that")
    assert t.text == "" and d.history == []
    say(d, 7, final="delete that")
    assert t.text == "" and notes[-1] == "nothing to scratch"
    say(d, 8, final="Fresh.")
    assert t.text == "Fresh."                                                        # no stray leading space


def test_dictator_scratch_with_a_later_phrase_already_showing():
    d, t, *_ = mk()
    say(d, 1, final="One.")
    say(d, 2, final="Two.")
    d.begin(3)
    d.begin(4); d.draft(4, "three")
    assert t.text == "One. Two. three"
    d.final(3, "scratch that")
    assert t.text == "One. three", t.text                                           # " Two." removed from the middle


def test_dictator_stop_listening():
    d, t, _, stops, _ = mk()
    say(d, 1, final="Hello.")
    say(d, 2, draft="stop", final="Stop listening.")
    assert stops == [1] and t.text == "Hello."


def test_dictator_focus_change_abandons_undecided_text():
    d, t, hwnd, _, notes = mk()
    say(d, 1, final="Settled.")
    d.begin(2); d.draft(2, "half a sen")
    assert t.text == "Settled. half a sen"
    hwnd[0] = 2                                                                      # user switched window
    n = len(t.log)
    d.draft(2, "half a sentence")                                                    # must NOT backspace into the old window
    d.final(2, "Half a sentence.")
    assert len(t.log) == n and notes[-1] == "window changed" and d.parts == [] and d.shown == ""
    say(d, 3, final="New window.")
    assert t.log[-1] == (0, "New window.")                                           # fresh start, no space, no backspaces
    say(d, 4, final="scratch that")
    assert t.log[-1] == (len("New window."), "")                                    # only reaches text typed in THIS window


def test_dictator_focus_change_clears_scratch_history():
    d, t, hwnd, *_ = mk()
    say(d, 1, final="Old window text.")
    hwnd[0] = 9
    n = len(t.log)
    say(d, 2, final="scratch that")
    assert len(t.log) == n and t.text == "Old window text."


def test_dictator_focus_change_with_nothing_typed_keeps_the_phrase():
    d, t, hwnd, *_ = mk()
    d.begin(1)                                                                       # speaking, nothing typed yet
    hwnd[0] = 5
    d.final(1, "Still arrives.")
    assert t.text == "Still arrives."


def test_engine_selection_and_defaults():
    assert engine_kind(DEFAULT_DRAFT) == "stream" and engine_kind(DEFAULT_FINAL) == "nemo"
    assert engine_kind("sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06") == "stream"
    for whisper in ("tiny.en", "small.en", "large-v3-turbo", "distil-small.en"):
        assert engine_kind(whisper) == "whisper", whisper
    import types
    args = types.SimpleNamespace(device="cpu", model_dir="m", compute_type=None, language="en")
    assert isinstance(make_transcriber(DEFAULT_DRAFT, 2, 1, args), SherpaStreaming)
    assert isinstance(make_transcriber(DEFAULT_FINAL, 2, 3, args), SherpaNemo)
    w = make_transcriber("small.en", 2, 3, args, "Perth")
    assert isinstance(w, WhisperTranscriber) and w.prompt == "Perth" and w.beam == 3


def test_find_model_files_prefers_int8():
    import os, tempfile
    with tempfile.TemporaryDirectory() as d:
        for f in ("encoder-epoch-99-avg-1-chunk-16-left-128.onnx", "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
                  "decoder-epoch-99-avg-1-chunk-16-left-128.onnx", "joiner-epoch-99-avg-1-chunk-16-left-128.onnx",
                  "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx", "tokens.txt", "README.md"):
            open(os.path.join(d, f), "w").close()
        got = find_model_files(d)
        assert got["encoder"].endswith(".int8.onnx") and got["joiner"].endswith(".int8.onnx")
        assert got["decoder"].endswith("left-128.onnx") and got["tokens"].endswith("tokens.txt")
        os.remove(os.path.join(d, "tokens.txt"))
        try:
            find_model_files(d)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing tokens.txt not reported")


def test_ensure_sherpa_model_uses_existing_folder():
    import os, tempfile
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "some-model"))
        assert ensure_sherpa_model("some-model", d) == os.path.join(d, "some-model")     # no download attempted


def test_sherpa_wrappers_with_fake_recognisers():
    import numpy as np
    pcm = (np.ones(1600, dtype=np.int16) * 1000).tobytes()

    class FakeStream:
        def __init__(self): self.fed, self.done, self.result = [], False, types.SimpleNamespace(text="Hello, world.")
        def accept_waveform(self, rate, samples): self.fed.append((rate, len(samples)))
        def input_finished(self): self.done = True

    import types

    class FakeOnline:
        def __init__(self, result): self.result, self.ready, self.decoded = result, 3, 0
        def create_stream(self): self.s = FakeStream(); return self.s
        def is_ready(self, s):
            self.ready -= 1
            return self.ready >= 0
        def decode_stream(self, s): self.decoded += 1
        def get_result(self, s): return self.result

    st = SherpaStreaming("n", 2)
    st.model = FakeOnline("HELLO WORLD")                                              # older builds return a str
    assert st(pcm, 1) == "hello world" and st.model.decoded == 3
    assert st.model.s.fed == [(SAMPLE_RATE, 1600)] and not st.model.s.done            # stream stays open
    st.model = FakeOnline(types.SimpleNamespace(text="Hi There"))                      # newer builds return an object
    assert st(pcm, 2) == "hi there"
    st.model = FakeOnline("[BLANK_AUDIO]")
    assert st(pcm, 3) == ""                                                            # noise tags still filtered

    class FakeOffline:
        def create_stream(self): return FakeStream()
        def decode_stream(self, s): pass
    nm = SherpaNemo("n", 2)
    nm.model = FakeOffline()
    assert nm(pcm) == "Hello, world."                                                  # case and punctuation kept


def test_streaming_draft_feeds_only_new_audio():
    """The draft's work per update must not grow with the phrase: each call feeds just the new audio."""
    import numpy as np, types

    class S:
        def __init__(self): self.samples = 0
        def accept_waveform(self, rate, x): self.samples += len(x)

    class Rec:
        def __init__(self): self.streams, self.decodes = [], 0
        def create_stream(self): self.streams.append(S()); return self.streams[-1]
        def is_ready(self, s): return False
        def decode_stream(self, s): self.decodes += 1
        def get_result(self, s): return types.SimpleNamespace(text="x")

    st = SherpaStreaming("n", 2)
    st.model = rec = Rec()
    fed_per_call = []
    for secs in np.arange(0.5, 14.0, 0.3):                                        # one long phrase, growing
        pcm = bytes(int(secs * 32000) // 2 * 2)
        before = sum(x.samples for x in rec.streams)
        st(pcm, 7)
        fed_per_call.append(sum(x.samples for x in rec.streams) - before)
    assert len(rec.streams) == 1                                                  # one stream for the phrase
    assert max(fed_per_call[1:]) <= 0.3 * SAMPLE_RATE + 2                         # ~0.3 s of audio per update
    assert abs(sum(fed_per_call) - 13.7 * SAMPLE_RATE) < SAMPLE_RATE * 0.35       # total = the audio, not its square
    st(bytes(32000), 8)                                                           # next phrase: fresh stream
    assert len(rec.streams) == 2 and rec.streams[1].samples == 16000
    st(bytes(16000), 8)                                                           # shorter than fed: start over
    assert len(rec.streams) == 3
    st(bytes(32000))                                                              # no id: never reuse a stream
    st(bytes(32000))
    assert len(rec.streams) == 5


def test_hotkey():
    assert parse_hotkey("ctrl+alt+d") == [0x11, 0x12, ord("D")]
    assert parse_hotkey("Ctrl + F9") == [0x11, 0x78] and parse_hotkey("win+space") == [0x5B, 0x20]
    for bad in ("ctrl+banana", "d", ""):
        try:
            parse_hotkey(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    down = set()
    w = ChordWatcher(lambda vk: vk in down, [0x11, 0x12, 0x44])
    assert w.poll() is False
    down |= {0x11, 0x12}; assert w.poll() is False
    down |= {0x44}; assert w.poll() is True
    assert w.poll() is False                                                         # held: fires once
    down -= {0x44}; assert w.poll() is False
    down |= {0x44}; assert w.poll() is True                                          # re-armed by releasing


def test_latest_worker_drops_stale_jobs():
    seen, gate, started = [], threading.Event(), threading.Event()

    def fn(job):
        seen.append(job[0])
        started.set()
        gate.wait(2)
    w = LatestWorker(fn)
    w.start()
    w.submit((1, b""))
    assert started.wait(2)
    w.submit((2, b"")); w.submit((3, b""))                                           # 2 is superseded by 3
    gate.set()
    for _ in range(200):
        if seen == [1, 3]:
            break
        threading.Event().wait(0.01)
    assert seen == [1, 3], seen
    done = threading.Event()
    w2 = LatestWorker(lambda j: done.set())
    w2.job = (5, b"")
    w2.discard(4); assert w2.job is not None
    w2.discard(5); assert w2.job is None


def test_fifo_worker_keeps_order():
    got, done = [], threading.Event()

    def fn(job):
        got.append(job)
        if len(got) == 5:
            done.set()
    w = FifoWorker(fn)
    w.start()
    for i in range(5):
        w.submit(i)
    assert done.wait(2) and got == [0, 1, 2, 3, 4]


def test_end_to_end_with_fake_models():
    """Frames -> Pipeline -> fake draft/final models -> Dictator -> text. Drafts type, final corrects."""
    now = [0.0]
    out = queue.Queue()
    words = "hello brave new world".split()

    def fake_draft(uid, pcm):                                  # more audio -> more words, one of them wrong
        n = min(len(words), len(pcm) // 12800)
        guess = words[:n]
        if n >= 2:
            guess[1] = "grave"
        out.put(("draft", uid, " ".join(guess)))

    def fake_final(uid, pcm):
        out.put(("final", uid, "Hello, brave new world."))

    p = Pipeline(lambda f: f[:1] == b"S", fake_draft, fake_final, out, Segmenter(), clock=lambda: now[0])
    d, t, *_ = mk()
    p.set_active(True)
    drafted_text = []
    for f in [b"q" * FRAME_BYTES] * 3 + [b"S" * FRAME_BYTES] * 60 + [b"q" * FRAME_BYTES] * 25:
        now[0] += 0.03
        p.feed(f)
        while not out.empty():
            ev = out.get_nowait()
            {"start": d.begin, "cancel": d.cancel, "draft": d.draft, "final": d.final}[ev[0]](*ev[1:])
            if ev[0] == "draft":
                drafted_text.append(t.text)
    assert any("grave" in s for s in drafted_text)                                   # the wrong draft really showed
    assert any(back > 0 for back, _ in t.log)                                        # ... and was backspaced away
    assert t.text == "Hello, brave new world." and d.history == ["Hello, brave new world."]


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
