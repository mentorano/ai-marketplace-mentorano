#!/usr/bin/env python3
"""Tests for the Gemini voter's backend chain in plugins/3amigos/skills/3amigos/scripts/panel.py.

panel.py runs for real with `--voters gemini`. Stub `agy` and `gcloud` binaries come first on
PATH, and a local HTTP stub stands in for both REST paths (Vertex and the API key) through
AMIGOS_GEMINI_API_BASE. Every stub call and every HTTP request is recorded with a timestamp in
one events file outside <out>, so a test can assert which hops ran and in which order. HOME is
a temp dir that holds the user config; the run's cwd is a temp dir that is not a git repo.
Nothing reaches the network beyond 127.0.0.1; no real agy, gcloud or Google endpoint is called.

Hops (spec GV3): 1 agy + preferred model, 2 fallback + preferred, 3 agy + second model,
4 fallback + second.

Run:  python3 tests/test_3amigos_gemini.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "plugins" / "3amigos" / "skills" / "3amigos" / "scripts" / "panel.py"

GOOD = {"ideas": ["a", "b", "c"]}
CARBON, ARGON = "gemini-4-carbon", "gemini-4-argon"
TOKEN, KEY, OTHER_SECRET = "FAKE-TOKEN-abc", "FAKE-KEY-123", "FAKE-OTHER-999"
MARGIN = 3.0  # seconds a run may take past its --deadline (process start, kill, exit)
PROMPT_TAIL = "Do not read files."

# Shared head of both stubs: the state dir is baked in, every call is recorded before it acts.
STUB_HEAD = r'''#!__PY__
import json, os, subprocess, sys, time
S = "__STATE__"
def rec(**kw):
    kw["t"] = time.time()
    with open(os.path.join(S, "events.jsonl"), "a") as f:
        f.write(json.dumps(kw) + "\n")
def hang(name):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # same process group
    with open(os.path.join(S, name + "-hang.pids"), "a") as f:
        f.write("%d %d\n" % (os.getpid(), child.pid))
    time.sleep(30)
    sys.exit(0)
argv = sys.argv[1:]
'''

# The agy stub, shapes as in the spec's "Verified on 2026-11-18". agy.json:
# {"models": [agy ids], "models_mode": ok|hang|fail,
#  "modes": {model prefix: ok|short|limit|fail|hang|ptimeout|notlogged|unknown}}
AGY = STUB_HEAD + r'''rec(who="agy", argv=argv, cwd=os.getcwd())
conf = json.load(open(os.path.join(S, "agy.json")))
if argv[:1] == ["models"]:
    if conf["models_mode"] == "hang":
        hang("agy")
    if conf["models_mode"] == "fail":
        sys.stderr.write("error: could not fetch the model list\n")
        sys.exit(2)
    print("Fetching available models...")
    for m in conf["models"]:
        print(m + "\t" + m.replace("-", " ").title())
    sys.exit(0)
model = argv[argv.index("--model") + 1]
mode = next((v for k, v in conf["modes"].items() if model.startswith(k)), "ok")
QUOTA = "You have exhausted your capacity on this model."
def envelope(status, response="", error="", reason="stop"):
    print(json.dumps({"conversation_id": "conv-1", "status": status, "response": response,
                      "error": error, "finished_reason": reason}))
def agy_error(short, status, reason):
    sys.stderr.write("AGY_ERROR: " + json.dumps({"short_error": short, "status": status,
                                                 "retryable": False, "reason": reason}) + "\n")
if model not in conf["models"] or mode == "unknown":
    sys.stderr.write("error: invalid model selection (--model \"%s\"): model %s is not recognized as a known model\n"
                     % (model, model))
    sys.exit(1)
if mode == "hang":  # ignores --print-timeout, so only panel.py's kill ends it
    hang("agy")
if mode == "ok":
    envelope("SUCCESS", "Here you go:\n```json\n{\"ideas\": [\"a\", \"b\", \"c\"]}\n```\n")
    sys.exit(0)
if mode == "short":
    envelope("SUCCESS", "```json\n{\"ideas\": [\"a\"]}\n```\n")
    sys.exit(0)
if mode == "limit":  # GM1: exit code and texts not observed yet
    envelope("ERROR", error=QUOTA, reason="error")
    agy_error(QUOTA, "RESOURCE_EXHAUSTED", "quota_exhausted")
    sys.exit(1)
if mode == "ptimeout":
    envelope("ERROR", error="print timeout reached", reason="print_timeout")
    agy_error("print timeout reached", "DEADLINE_EXCEEDED", "print_timeout")
    sys.exit(3)
if mode == "notlogged":
    sys.stderr.write("Eligibility check failed: sign in to continue\n")
    sys.exit(1)
envelope("ERROR", error="internal error", reason="error")  # fail
agy_error("internal error", "INTERNAL", "internal")
sys.stderr.write("STDERR-MARKER-123 raw agy output\n")  # must never reach gemini.log
sys.exit(5)
'''

# The gcloud stub. gcloud.json: {"adc": ok|slow|fail|hang, "user": ok|slow|fail|hang}; slow answers after 3 s
GCLOUD = STUB_HEAD + r'''rec(who="gcloud", argv=argv)
conf = json.load(open(os.path.join(S, "gcloud.json")))
mode = conf["adc" if "application-default" in argv else "user"]
if mode == "hang":
    hang("gcloud")
if mode == "slow":
    time.sleep(3)
if mode == "fail":
    sys.stderr.write("ERROR: Reauthentication failed. cannot prompt during non-interactive execution.\n")
    sys.exit(1)
print("__TOKEN__")
'''

HTTP_STATUS = {401: "UNAUTHENTICATED", 402: "PAYMENT_REQUIRED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
               429: "RESOURCE_EXHAUSTED", 500: "INTERNAL"}
MODEL_IN_PATH = re.compile(r"models/([^/:]+):generateContent")


class GeminiStub(ThreadingHTTPServer):
    """Both REST paths. modes: {model: ok|short|nojson|notjson|hang|close|401|402|403|404|429|500}."""
    daemon_threads = True
    block_on_close = False

    def __init__(self, events: Path):
        super().__init__(("127.0.0.1", 0), Handler)
        self.events, self.modes, self.lock, self.release = events, {}, threading.Lock(), threading.Event()

    def record(self, entry):
        entry["t"] = time.time()
        with self.lock, open(self.events, "a") as f:
            f.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw.decode("utf-8", "replace")
        m = MODEL_IN_PATH.search(self.path)
        model = m.group(1) if m else ""
        self.server.record({"who": "http", "path": self.path, "body": body,
                            "headers": {k.lower(): v for k, v in self.headers.items()}})
        mode = self.server.modes.get(model, "ok")
        if mode == "hang":  # accept, then never answer
            self.server.release.wait(30)
            return
        if mode == "close":  # drop the connection at once, no status line
            self.close_connection = True
            return
        if mode == "notjson":
            return self.reply(200, "<html>this is not json</html>")
        if mode.isdigit():
            code = int(mode)
            return self.reply(code, json.dumps({"error": {"code": code, "message": "stub error",
                                                          "status": HTTP_STATUS[code]}}))
        texts = {"ok": ['Here you go:\n```json\n{"ideas": ["a", ', '"b", "c"]}\n```\n'],  # joined across parts
                 "short": ['{"ideas": ["a"]}'], "nojson": ["I cannot answer that in JSON."]}[mode]
        parts = [{"text": t} for t in texts]
        parts[0]["thoughtSignature"] = "U0lHTkFUVVJF" * 40  # the real API puts one on a part
        self.reply(200, json.dumps({"candidates": [{"content": {"role": "model", "parts": parts},
                                                    "finishReason": "STOP"}]}))

    def reply(self, code, text):
        data = text.encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass


class GeminiChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state, self.bin, self.home, self.cwd = (self.tmp / n for n in ("state", "bin", "home", "cwd"))
        for d in (self.state, self.bin, self.home, self.cwd):
            d.mkdir()
        self.out = self.tmp / "out"
        self.events_path = self.state / "events.jsonl"
        for name, src in (("agy", AGY), ("gcloud", GCLOUD)):
            stub = self.bin / name
            # the running interpreter, not a slow `env python3` shim, so the stubs start fast
            stub.write_text(src.replace("__PY__", sys.executable, 1).replace("__STATE__", str(self.state))
                            .replace("__TOKEN__", TOKEN))
            stub.chmod(0o755)
        self.agy([ARGON + "-high", ARGON + "-medium"])  # today's agy: no Carbon
        self.gcloud()
        self.config()
        (self.tmp / "task.md").write_text("Propose ideas.")
        (self.tmp / "data.md").write_text("data")
        self.server = GeminiStub(self.events_path)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        for pid in self.hang_pids("agy") + self.hang_pids("gcloud"):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- stubs and config -------------------------------------------------------------------

    def agy(self, models, models_mode="ok", **modes):
        """modes: model prefix -> mode, e.g. agy([...], **{CARBON: "hang"})."""
        (self.state / "agy.json").write_text(json.dumps({"models": models, "models_mode": models_mode,
                                                         "modes": modes}))

    def gcloud(self, adc="ok", user="ok"):
        (self.state / "gcloud.json").write_text(json.dumps({"adc": adc, "user": user}))

    def http(self, **modes):
        self.server.modes = modes

    def config(self, **gemini):
        cfg = {"agy": True, "model": CARBON, "model_fallback": ARGON, "effort": "high", "fallback": "vertex",
               "vertex": {"project": "example-project", "location": "global"},
               "key_env": "GEMINI_API_KEY", "key_dotenv": None}
        cfg.update(gemini)
        path = self.home / ".claude" / "3amigos" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "gemini": cfg}))

    # --- running and reading back ------------------------------------------------------------

    def run_panel(self, *extra, deadline=20, env=None):
        """deadline=None leaves --deadline out, to test the default."""
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("GOOGLE_", "GEMINI_", "CLOUDSDK_", "AMIGOS_")) and not k.lower().endswith("_proxy")}
        clean.update(PATH=f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", HOME=str(self.home),
                     AMIGOS_GEMINI_API_BASE=f"http://127.0.0.1:{self.server.server_address[1]}",
                     NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        clean.update(env or {})
        self.started = time.time()
        start = time.monotonic()
        self.proc = subprocess.run(
            [sys.executable, str(PANEL), "--task", str(self.tmp / "task.md"), "--input", str(self.tmp / "data.md"),
             "--out", str(self.out), "--voters", "gemini", "--require", "ideas=3",
             *(["--deadline", str(deadline)] if deadline is not None else []), *extra],
            cwd=self.cwd, capture_output=True, text=True, env=clean, timeout=(deadline or 30) + 30)
        self.elapsed = time.monotonic() - start
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        lines = [json.loads(s) for s in self.proc.stdout.splitlines() if s.strip()]
        return next(r for r in lines if r.get("voter") == "gemini")

    def events(self, who=None):
        if not self.events_path.exists():
            return []
        rows = sorted(map(json.loads, self.events_path.read_text().splitlines()), key=lambda e: e["t"])
        return [e for e in rows if who is None or e["who"] == who]

    def agy_prompt_calls(self):
        return [e["argv"] for e in self.events("agy") if "-p" in e["argv"]]

    def hops(self):
        """The hops that ran, in order: (backend, model)."""
        hops = []
        for e in self.events():
            if e["who"] == "agy" and "-p" in e["argv"]:
                hops.append(("agy", e["argv"][e["argv"].index("--model") + 1].rsplit("-", 1)[0]))
            elif e["who"] == "http":
                backend = "vertex" if e["path"].startswith("/v1/projects/") else "key"
                hops.append((backend, MODEL_IN_PATH.search(e["path"]).group(1)))
        return hops

    def hang_pids(self, name):
        path = self.state / f"{name}-hang.pids"
        return [int(x) for x in path.read_text().split()] if path.exists() else []

    def assert_ok(self, line, backend, model, note=""):
        self.assertEqual(line["status"], "ok", line)
        self.assertEqual(line["backend"], backend, line)
        self.assertEqual(line["model"], model, line)  # the API model name, never the agy id (AR9)
        self.assertEqual(line["note"], note, line)
        self.assertEqual(json.loads((self.out / "gemini.json").read_text()), GOOD)

    def assert_missing(self, line, why):
        self.assertEqual(line["status"], "missing", line)
        self.assertEqual(line["why"], why, line)
        self.assertFalse((self.out / "gemini.json").exists())

    def assert_killed(self, name):
        """Every hung stub that started, and the child in its process group, is gone (checked before
        tearDown). The count is not pinned: a later hop may start the same command again."""
        pids = self.hang_pids(name)
        self.assertTrue(pids and len(pids) % 2 == 0, pids)  # one (stub, child) pair per started call
        end, alive = time.monotonic() + 3, pids
        while alive and time.monotonic() < end:
            alive = [p for p in pids if _alive(p)]
            time.sleep(0.1)
        self.assertEqual(alive, [], f"{name} or its process group survived the run")

    def print_timeout(self, call=0):
        argv = self.agy_prompt_calls()[call]
        value = argv[argv.index("--print-timeout") + 1]
        self.assertRegex(value, r"^\d+s$")
        return int(value[:-1])

    def assert_within_deadline(self, deadline):
        self.assertLess(self.elapsed, deadline + MARGIN)

    def assert_secret_nowhere(self, secret):
        for f in self.out.rglob("*"):
            if f.is_file():
                self.assertNotIn(secret.encode(), f.read_bytes(), f)
        self.assertNotIn(secret, self.proc.stdout)
        self.assertNotIn(secret, self.proc.stderr)
        for e in self.events("agy") + self.events("gcloud"):
            self.assertNotIn(secret, json.dumps(e["argv"]))

    # --- the hop table -----------------------------------------------------------------------

    def test_hop1_agy_answers_and_the_answer_comes_from_response_not_the_envelope(self):
        self.agy([CARBON + "-high", ARGON + "-high"])
        line = self.run_panel()
        self.assert_ok(line, "agy", CARBON)  # the envelope itself has no "ideas": --require would fail on it
        self.assertEqual(self.hops(), [("agy", CARBON)])
        argv = self.agy_prompt_calls()[0]
        self.assertEqual(argv[argv.index("--model") + 1], CARBON + "-high")
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertLessEqual(self.print_timeout(), 20)
        prompt = argv[argv.index("-p") + 1]
        self.assertIn("Propose ideas.", prompt)
        self.assertTrue(prompt.rstrip().endswith(PROMPT_TAIL), prompt[-200:])
        self.assertNotIn("browse the web", prompt)

    def test_preferred_model_not_in_agy_models_goes_to_hop2_without_an_agy_call(self):
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON)  # also: text joined across parts, thoughtSignature ignored
        self.assertEqual(self.hops(), [("vertex", CARBON)])
        self.assertEqual(self.agy_prompt_calls(), [])

    def test_hop2_404_goes_to_hop3_agy_with_the_second_model(self):
        self.http(**{CARBON: "404"})
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])

    def test_hop2_403_is_the_same_as_404(self):
        self.http(**{CARBON: "403"})
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])

    def test_fallback_402_stops_the_chain_like_429(self):
        self.http(**{CARBON: "402"})  # agy Argon and REST Argon would both answer if reached
        line = self.run_panel()
        self.assert_missing(line, "usage-limit")
        self.assertEqual(self.hops(), [("vertex", CARBON)])

    def test_answer_that_fails_require_moves_to_the_next_hop(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "short"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON)])

    def test_no_agy_and_hop2_404_goes_to_hop4_with_the_second_model(self):
        self.http(**{CARBON: "404"})
        line = self.run_panel("--no-agy")
        self.assert_ok(line, "vertex", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])

    def test_each_hop_runs_at_most_once_in_table_order(self):  # no outer retry
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "fail", ARGON: "fail"})
        self.http(**{CARBON: "404", ARGON: "404"})
        line = self.run_panel()
        self.assertEqual(line["status"], "missing", line)
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON), ("agy", ARGON), ("vertex", ARGON)])
        self.assertNotIn("STDERR-MARKER-123", (self.out / "gemini.log").read_text())  # only classified whys

    # --- time: the 60 % rule and the kills ---------------------------------------------------

    def test_hung_hop2_leaves_time_for_hop3_inside_the_deadline(self):
        self.http(**{CARBON: "hang"})
        line = self.run_panel(deadline=6)
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])
        self.assert_within_deadline(6)

    def test_hung_hop1_without_fallback_leaves_time_for_hop3(self):
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "hang"})
        line = self.run_panel(deadline=6)
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("agy", ARGON)])
        self.assert_within_deadline(6)

    def test_http_that_accepts_and_never_answers_ends_the_hop_with_deadline(self):
        self.http(**{CARBON: "hang", ARGON: "hang"})
        line = self.run_panel("--no-agy", deadline=6)
        self.assert_missing(line, "deadline")
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])  # hop 2 ended inside its budget
        self.assert_within_deadline(6)

    def test_hung_gcloud_ends_the_hop_with_deadline(self):
        self.gcloud(adc="hang", user="hang")
        line = self.run_panel("--no-agy", deadline=6)
        self.assert_missing(line, "deadline")
        self.assertEqual(self.hops(), [])
        self.assert_within_deadline(6)
        self.assert_killed("gcloud")

    def test_gcloud_and_http_share_one_hop_budget(self):
        # hop 2: the token takes 3 s, then the HTTP call never answers; hop 2's budget is 60 % of 10 s
        self.gcloud(adc="slow")
        self.http(**{CARBON: "hang"})
        line = self.run_panel(deadline=10)
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])
        hop3 = self.events("agy")[-1]["t"] - self.started
        self.assertLess(hop3, 0.6 * 10 + 3.0, "hop 2 ran past its budget")  # a full-budget hop 2 would end at 10 s
        self.assert_within_deadline(10)

    def test_hung_agy_is_killed_and_the_fallback_answers_inside_the_deadline(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "hang"})
        line = self.run_panel(deadline=6)
        self.assert_ok(line, "vertex", CARBON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON)])
        self.assert_within_deadline(6)
        self.assert_killed("agy")

    def test_agy_print_timeout_is_deadline(self):
        self.config(fallback="none")
        self.agy([ARGON + "-high"], **{ARGON: "ptimeout"})
        line = self.run_panel()
        self.assert_missing(line, "deadline")

    def test_hop_with_a_later_hop_possible_gets_60_percent_and_the_same_print_timeout(self):
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"])  # hop 3 possible
        line = self.run_panel(deadline=20)
        self.assert_ok(line, "agy", CARBON)
        self.assertGreaterEqual(self.print_timeout(), 9)  # 60 % of the time left of 20 s, with room for load
        self.assertLessEqual(self.print_timeout(), 12)

    def test_last_eligible_hop_gets_all_the_time_left(self):
        self.config(fallback="none")
        self.agy([CARBON + "-high"])  # no Argon in agy, no fallback: hop 1 is the last eligible hop
        line = self.run_panel(deadline=20)
        self.assert_ok(line, "agy", CARBON)
        self.assertGreaterEqual(self.print_timeout(), 15)  # 60 % would be at most 12
        self.assertLessEqual(self.print_timeout(), 20)

    def test_deadline_default_of_600_s_sets_the_hop_budget(self):
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"])
        line = self.run_panel(deadline=None)
        self.assert_ok(line, "agy", CARBON)
        budget = self.print_timeout()
        # 60 % of 600 s, less the agy models call; a 300 s default gives 180, a 900 s default 540
        self.assertGreaterEqual(budget, 330, "the default --deadline is not 600 s")
        self.assertLessEqual(budget, 360, "the default --deadline is not 600 s")

    def test_agy_models_hang_with_no_other_hop_is_deadline(self):  # AR10
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"], models_mode="hang")
        line = self.run_panel(deadline=4)
        self.assert_missing(line, "deadline")
        self.assertEqual(line["backend"], "agy", line)
        self.assert_within_deadline(4)
        self.assert_killed("agy")

    def test_agy_models_failing_with_no_other_hop_is_exit_code(self):  # AR10
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"], models_mode="fail")
        line = self.run_panel()
        self.assert_missing(line, "exit 2")
        self.assertEqual(line["backend"], "agy", line)

    # --- the agy id --------------------------------------------------------------------------

    def test_agy_id_is_picked_by_the_effort_suffix(self):
        self.config(effort="medium")
        self.agy([CARBON + "-high", CARBON + "-medium", ARGON + "-high", ARGON + "-medium"])
        line = self.run_panel()
        self.assert_ok(line, "agy", CARBON)
        argv = self.agy_prompt_calls()[0]
        self.assertEqual(argv[argv.index("--model") + 1], CARBON + "-medium")

    def test_agy_id_is_never_guessed(self):
        listed = [CARBON + "-high", ARGON + "-high", ARGON + "-medium"]  # no "-low" id
        self.config(effort="low")
        self.agy(listed)
        line = self.run_panel()
        self.assertEqual(line["status"], "ok", line)
        for argv in self.agy_prompt_calls():
            self.assertIn(argv[argv.index("--model") + 1], listed)

    def test_agy_unknown_model_moves_to_the_fallback(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "unknown"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON)])

    def test_agy_unknown_model_counts_as_a_skipped_hop(self):
        self.agy([ARGON + "-high"], **{ARGON: "unknown"})  # listed, but -p rejects the id
        self.http(**{CARBON: "404"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", ARGON)  # hop 3 skipped, so hop 4 runs
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON), ("vertex", ARGON)])

    def test_agy_not_logged_in_drops_both_agy_hops_without_a_note(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "notlogged"})  # agy Argon would answer
        self.http(**{CARBON: "404"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", ARGON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON), ("vertex", ARGON)])

    def test_agy_not_logged_in_on_the_last_hop_is_not_auth(self):
        self.config(fallback="none")
        self.agy([ARGON + "-high"], **{ARGON: "notlogged"})
        line = self.run_panel()
        self.assert_missing(line, "exit 1")  # AR9: the agy exit code, not auth
        self.assertEqual(line["backend"], "agy", line)
        self.assertEqual(line["note"], "", line)

    def test_prompt_over_200_kb_skips_both_agy_hops(self):
        (self.tmp / "data.md").write_text("x" * 210_000)
        self.agy([CARBON + "-high", ARGON + "-high"])
        self.http(**{CARBON: "404"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", ARGON)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])
        self.assertEqual(self.agy_prompt_calls(), [])

    # --- no hop at all -----------------------------------------------------------------------

    def test_missing_agy_binary_and_no_other_hop_is_missing_binary(self):
        self.config(fallback="none")
        (self.bin / "agy").unlink()
        line = self.run_panel()
        self.assert_missing(line, "missing-binary")

    def test_no_possible_hop_is_no_backend_with_empty_backend_and_model(self):
        self.config(agy=False, fallback="none")
        line = self.run_panel()
        self.assert_missing(line, "no-backend")
        self.assertEqual((line["backend"], line["model"]), ("", ""))
        self.assertEqual(self.hops(), [])

    def test_fallback_none_and_no_agy_is_no_backend(self):
        self.config(fallback="none")
        line = self.run_panel("--no-agy", deadline=20)
        self.assert_missing(line, "no-backend")
        self.assertEqual((line["backend"], line["model"]), ("", ""))
        self.assertEqual(self.events(), [])  # ends at once: no stub call, not even `agy models`
        self.assertLess(self.elapsed, 8.0)  # a hop budget at --deadline 20 would be 12 s

    def test_fallback_none_runs_only_the_agy_hops(self):
        self.config(fallback="none")
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "fail"})
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.hops(), [("agy", CARBON), ("agy", ARGON)])
        self.assertEqual(self.events("gcloud"), [])

    def test_no_agy_runs_only_the_rest_hops(self):
        self.agy([CARBON + "-high", ARGON + "-high"])  # agy would answer at once if called
        self.http(**{CARBON: "404", ARGON: "404"})
        line = self.run_panel("--no-agy")
        self.assertEqual(line["status"], "missing", line)
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])
        self.assertEqual(self.agy_prompt_calls(), [])

    # --- usage limits ------------------------------------------------------------------------

    def test_agy_usage_limit_goes_to_the_fallback_with_the_note(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "limit"})
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON, note="agy usage limit")
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON)])

    def test_agy_usage_limit_note_is_set_whatever_answered(self):
        self.agy([CARBON + "-high", ARGON + "-high"], **{CARBON: "limit"})  # agy Argon would answer
        self.http(**{CARBON: "404", ARGON: "404"})
        line = self.run_panel()
        self.assert_missing(line, "no-access")
        self.assertEqual(line["note"], "agy usage limit")
        self.assertEqual(self.hops(), [("agy", CARBON), ("vertex", CARBON), ("vertex", ARGON)])  # hop 3 dropped

    def test_fallback_429_stops_the_chain_with_usage_limit(self):
        self.http(**{CARBON: "429"})  # agy Argon and REST Argon would both answer if reached
        line = self.run_panel()
        self.assert_missing(line, "usage-limit")
        self.assertEqual(self.hops(), [("vertex", CARBON)])

    # --- auth failures on the fallback (GM8) ---------------------------------------------------

    def test_fallback_401_goes_to_hop3_ok_with_the_auth_note(self):
        self.http(**{CARBON: "401"})
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON, note="fallback auth failed")
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])

    def test_fallback_401_with_agy_off_is_missing_auth(self):
        self.config(agy=False)
        self.http(**{CARBON: "401"})  # REST Argon would answer: hop 4 must be dropped
        line = self.run_panel()
        self.assert_missing(line, "auth")
        self.assertEqual(self.hops(), [("vertex", CARBON)])

    def test_fallback_401_with_agy_failing_is_missing_auth(self):
        self.agy([ARGON + "-high"], **{ARGON: "fail"})
        self.http(**{CARBON: "401"})  # REST Argon would answer: hop 4 must be dropped
        line = self.run_panel()
        self.assert_missing(line, "auth")
        self.assertEqual(self.hops(), [("vertex", CARBON), ("agy", ARGON)])

    def test_no_gcloud_token_is_an_auth_failure(self):
        self.gcloud(adc="fail", user="fail")
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON, note="fallback auth failed")
        self.assertEqual(self.hops(), [("agy", ARGON)])

    def test_adc_token_first_then_the_gcloud_user_token(self):
        self.gcloud(adc="fail", user="ok")
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON)
        calls = [e["argv"] for e in self.events("gcloud")]
        self.assertEqual(calls[:2], [["auth", "application-default", "print-access-token"],
                                     ["auth", "print-access-token"]])
        self.assertEqual(self.events("http")[0]["headers"]["authorization"], f"Bearer {TOKEN}")

    # --- the REST request and the last hop's why -------------------------------------------------

    def test_vertex_request_path_body_and_thinking_level_follow_the_config(self):
        self.config(effort="medium")
        line = self.run_panel()
        self.assert_ok(line, "vertex", CARBON)
        req = self.events("http")[0]
        self.assertEqual(req["path"], "/v1/projects/example-project/locations/global/publishers/google/models/"
                                      f"{CARBON}:generateContent")
        self.assertEqual(req["headers"]["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(req["body"]["contents"][0]["role"], "user")
        self.assertIn("Propose ideas.", req["body"]["contents"][0]["parts"][0]["text"])
        self.assertEqual(req["body"]["generationConfig"]["thinkingConfig"]["thinkingLevel"], "MEDIUM")
        self.assertNotIn("thinking_budget", json.dumps(req["body"]))
        self.assertNotIn("thinkingBudget", json.dumps(req["body"]))

    def test_404_on_the_last_hop_is_no_access(self):
        self.http(**{CARBON: "404", ARGON: "404"})
        line = self.run_panel("--no-agy")
        self.assert_missing(line, "no-access")

    def test_other_rest_code_on_the_last_hop_is_http_code(self):
        self.http(**{CARBON: "404", ARGON: "500"})
        line = self.run_panel("--no-agy")
        self.assert_missing(line, "http 500")

    def test_agy_failure_on_the_last_hop_is_exit_code(self):
        self.config(fallback="none")
        self.agy([ARGON + "-high"], **{ARGON: "fail"})
        line = self.run_panel()
        self.assert_missing(line, "exit 5")

    def test_rest_connection_dropped_on_the_last_hop_is_network(self):
        self.http(**{CARBON: "close", ARGON: "close"})
        line = self.run_panel("--no-agy")
        self.assert_missing(line, "network")
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])

    def test_rest_connection_refused_on_the_last_hop_is_network(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()  # nothing listens there now
        line = self.run_panel("--no-agy", env={"AMIGOS_GEMINI_API_BASE": f"http://127.0.0.1:{port}"})
        self.assert_missing(line, "network")

    def test_rest_answer_without_a_json_object_is_bad_json(self):
        self.http(**{CARBON: "nojson", ARGON: "nojson"})
        line = self.run_panel("--no-agy")
        self.assert_missing(line, "bad-json")

    def test_rest_body_that_is_not_json_fails_the_hop_and_the_chain_goes_on(self):
        self.http(**{CARBON: "notjson", ARGON: "notjson"})
        line = self.run_panel("--no-agy")
        self.assertEqual(line["status"], "missing", line)  # the why is not pinned by the spec
        self.assertEqual(self.hops(), [("vertex", CARBON), ("vertex", ARGON)])

    # --- secrets ---------------------------------------------------------------------------------

    def test_token_never_reaches_a_file_output_or_process_argument(self):
        self.http(**{CARBON: "404"})  # gcloud, REST and agy -p all run
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.events("http")[0]["headers"]["authorization"], f"Bearer {TOKEN}")
        self.assert_secret_nowhere(TOKEN)

    def test_key_never_reaches_a_file_output_or_process_argument(self):
        self.config(fallback="key")
        self.http(**{CARBON: "404"})
        line = self.run_panel(env={"GEMINI_API_KEY": KEY})
        self.assert_ok(line, "agy", ARGON)
        req = self.events("http")[0]
        self.assertEqual(req["path"], f"/v1beta/models/{CARBON}:generateContent")
        self.assertEqual(req["headers"]["x-goog-api-key"], KEY)
        self.assert_secret_nowhere(KEY)

    def test_key_from_dotenv_works_and_its_other_lines_reach_nothing(self):
        dotenv = self.tmp / "secrets.env"
        dotenv.write_text(f"OTHER_SECRET={OTHER_SECRET}\nGEMINI_API_KEY={KEY}\n")
        self.config(fallback="key", key_dotenv=str(dotenv))
        self.http(**{CARBON: "404"})
        line = self.run_panel()
        self.assert_ok(line, "agy", ARGON)
        self.assertEqual(self.events("http")[0]["headers"]["x-goog-api-key"], KEY)
        self.assert_secret_nowhere(KEY)
        self.assert_secret_nowhere(OTHER_SECRET)
        self.assertNotIn(OTHER_SECRET, self.events_path.read_text())  # nor in any request header or body

    def test_environment_key_wins_over_key_dotenv(self):
        dotenv = self.tmp / "secrets.env"
        dotenv.write_text(f"GEMINI_API_KEY={KEY}\n")
        self.config(fallback="key", key_dotenv=str(dotenv))
        line = self.run_panel(env={"GEMINI_API_KEY": "FAKE-KEY-ENV-777"})
        self.assert_ok(line, "key", CARBON)
        self.assertEqual(self.events("http")[0]["headers"]["x-goog-api-key"], "FAKE-KEY-ENV-777")

    def test_without_key_dotenv_no_file_is_read_and_the_key_path_fails_with_auth(self):
        for d in (self.cwd, self.home):
            (d / ".env").write_text(f"GEMINI_API_KEY={KEY}\n")
        self.config(fallback="key")
        line = self.run_panel("--no-agy")
        self.assert_missing(line, "auth")
        self.assertEqual(self.hops(), [])


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
