"""The Gemini voter of a 3amigos panel: one answer through a chain of backend hops.

Hops, in order, all inside one deadline: agy with the preferred model, the fallback (Vertex or
an API key) with the preferred model, agy with the second model, the fallback with the second
model. The first answer that passes validate() ends the chain. There is no outer retry: the
chain is the retry, and each hop runs at most once.

A hop gets 60 % of the time left while a later hop is still possible, else all of it. Only a
usage limit on the fallback (HTTP 429 or 402) stops the chain at once. An auth failure on the
fallback drops both fallback hops; a usage limit on agy drops both agy hops.

The API key and the access token live only in a request header set here; they never reach a
command line, the log or any file under <out>.
"""
import errno
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

AGY_PROMPT_LIMIT = 200_000  # bytes, UTF-8: longer prompts do not fit agy's argument
AGY_MODELS_CAP = 15
TOKEN_CAP = 15
SHARE = 0.6  # of the time left, for a hop that still has a later hop behind it
AGY_TAIL = "Do not read files. Do not browse the web."
VERTEX_TOKEN_CMDS = (["auth", "application-default", "print-access-token"],
                     ["auth", "print-access-token"])
QUOTA_TEXTS = ("resource_exhausted", "exhausted your capacity", "quota", "usage limit", "rate limit")
NOTE_AGY_LIMIT = "agy usage limit"
NOTE_FB_AUTH = "fallback auth failed"


def find_bin(name):
    """Same lookup as panel.find_bin: PATH first, then ~/.<name>/bin and ~/.local/bin."""
    for cand in (shutil.which(name), os.path.expanduser(f"~/.{name}/bin/{name}"),
                 os.path.expanduser(f"~/.local/bin/{name}")):
        if cand and os.path.exists(cand):
            return cand
    return None


class Log:
    """Appends lines to <out>/gemini.log. Written only from the calling thread, never a secret."""

    def __init__(self, path):
        self.path = path
        with open(path, "w"):
            pass

    def __call__(self, text):
        with open(self.path, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def run_capped(cmd, timeout, cwd=None):
    """Runs cmd in its own process group. Returns (rc, stdout, stderr) or None when killed at timeout."""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=max(timeout, 0.1))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:  # the group already exited
            pass
        try:
            proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:  # a descendant outside the group still holds a pipe
            proc.stdout.close()
            proc.stderr.close()
            proc.wait()
        return None
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


# ---------------------------------------------------------------- agy


def agy_models(agy, timeout, log):
    """(ids, why) from `agy models`: one '<id>\\t<display name>' line per model. why is 'deadline'
    past its cap, 'exit <n>' on a failure, else ''."""
    try:
        res = run_capped([agy, "models"], min(AGY_MODELS_CAP, timeout))
    except OSError as exc:
        log(f"agy models: launch error {type(exc).__name__}")
        return [], "missing-binary"
    if res is None or res[0] != 0:
        why = "deadline" if res is None else f"exit {res[0]}"
        log(f"agy models: {why}")
        return [], why
    ids = [line.split("\t", 1)[0].strip() for line in res[1].splitlines() if "\t" in line]
    log(f"agy models: {len(ids)} listed")  # no value from agy's output in the log
    return [i for i in ids if i], ""


def agy_id(ids, model, effort):
    """The listed id for model at effort ('gemini-4-argon-high'); None when not listed. Never guessed."""
    want = f"{model}-{effort}"
    if want in ids:
        return want
    for i in ids:
        if i.startswith(model) and i.endswith(f"-{effort}"):
            return i
    return None


def envelope(stdout):
    """The agy JSON envelope from stdout (whole text, else the last line that parses)."""
    for text in [stdout.strip()] + list(reversed(stdout.strip().splitlines())):
        try:
            obj = json.loads(text)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return {}


def agy_error(stderr):
    """The status and reason of the 'AGY_ERROR: {...}' line on stderr, upper-cased; '' when absent."""
    for line in stderr.splitlines():
        if "AGY_ERROR:" in line:
            try:
                obj = json.loads(line.split("AGY_ERROR:", 1)[1].strip())
            except ValueError:
                return "UNPARSED"
            if isinstance(obj, dict):
                return f"{obj.get('status', '')} {obj.get('reason', '')}".upper()
    return ""


def agy_why(rc, env, stderr, log):
    """Classifies a failed agy call: (why, logged_out). An unknown model counts as a skipped hop and
    the chain goes on; not logged in makes agy unusable for this vote. Both keep 'exit <n>'."""
    err = agy_error(stderr)
    text = " ".join([err, str(env.get("error", "")), str(env.get("finished_reason", "")), stderr]).lower()
    # The log gets fixed pattern names only, never a value taken from agy's output.
    if "deadline_exceeded" in text or "print_timeout" in text:
        log("agy: print timeout")
        return "deadline", False
    if any(q in text for q in QUOTA_TEXTS):
        log("agy: usage limit")
        return "usage-limit", False
    if "invalid model selection" in text:
        log("agy: invalid model selection, the model is not in agy, hop counted as skipped")
    elif "eligibility check failed" in text:
        log("agy: not logged in (Eligibility check failed), agy hops dropped")
        return f"exit {rc}", True
    else:
        log(f"agy: failed, exit {rc}")
    return f"exit {rc}", False


def agy_hop(st, model_id, budget):
    """One agy call in the voter's empty work dir. Returns (obj, why)."""
    secs = max(1, int(budget))
    cmd = [st["agy"], "-p", st["agy_prompt"], "--model", model_id, "--sandbox",
           "--print-timeout", f"{secs}s", "--output-format", "json"]
    try:
        res = run_capped(cmd, budget, cwd=st["work"])
    except OSError as exc:
        if exc.errno == errno.E2BIG:  # the prompt is over this platform's argument limit
            st["log"]("agy: prompt over the argument limit (E2BIG), agy hops dropped")
            st["agy_ok"] = False
            return None, "no-backend"
        st["log"](f"agy: launch error {type(exc).__name__}")
        return None, "missing-binary"
    if res is None:
        return None, "deadline"
    rc, out, err = res
    env = envelope(out)
    if rc == 0 and env.get("status") == "SUCCESS":
        return st["validate"](str(env.get("response") or ""))
    why, logged_out = agy_why(rc, env, err, st["log"])
    if logged_out:
        st["agy_ok"] = False  # no note: only a usage limit is reported to the caller
        st["agy_out"] = True
    return None, why


# ---------------------------------------------------------------- REST fallback


def read_key(cfg, project_root):
    """The API key: the variable named by key_env, else that one line of key_dotenv, else None."""
    name = cfg.get("key_env") or "GEMINI_API_KEY"
    if os.environ.get(name):
        return os.environ[name]
    path = cfg.get("key_dotenv")
    if not path:
        return None
    if not os.path.isabs(path) and project_root:
        path = os.path.join(project_root, path)
    pat = re.compile(r"\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*)$")
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                m = pat.match(line.rstrip("\n"))
                if m:
                    return m.group(1).strip().strip("'\"") or None
    except OSError:
        return None
    return None


def vertex_token(end):
    """(token, why) before the hop end: ADC first, then the gcloud user login. Over its cap is 'deadline'."""
    gcloud = shutil.which("gcloud")
    if not gcloud:
        return None, "auth"
    for args in VERTEX_TOKEN_CMDS:
        left = end - time.monotonic()
        if left <= 0:
            return None, "deadline"
        try:
            res = run_capped([gcloud] + args, min(TOKEN_CAP, left))
        except OSError:
            return None, "auth"
        if res is None:
            return None, "deadline"
        if res[0] == 0 and res[1].strip():
            return res[1].strip(), ""
    return None, "auth"


def credential(st, end):
    """(header name, value, why) for the configured fallback; the token is fetched once per run."""
    if st["fallback"] == "key":
        key = read_key(st["cfg"], st["project_root"])
        return ("x-goog-api-key", key, "") if key else (None, None, "auth")
    if not st.get("token"):
        st["token"], why = vertex_token(end)
        if why:
            return None, None, why
    return "Authorization", f"Bearer {st['token']}", ""


def rest_url(st, model):
    base = os.environ.get("AMIGOS_GEMINI_API_BASE", "").rstrip("/")
    if st["fallback"] == "key":
        return f"{base or 'https://generativelanguage.googleapis.com'}/v1beta/models/{model}:generateContent"
    vertex = st["cfg"].get("vertex") or {}
    loc = vertex.get("location") or "global"
    host = "https://aiplatform.googleapis.com" if loc == "global" else f"https://aiplatform.{loc}.rep.googleapis.com"
    return (f"{base or host}/v1/projects/{vertex.get('project')}/locations/{loc}"
            f"/publishers/google/models/{model}:generateContent")


def rest_body(prompt, effort):
    return json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"thinkingConfig": {"thinkingLevel": effort.upper()}}}).encode()


def post(req, timeout, holder):
    """Daemon-thread body: fills holder with (code, body bytes) or ('error', exception class name)."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            holder["res"] = (resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        holder["res"] = (exc.code, b"")
    except urllib.error.URLError as exc:  # a connect timeout arrives wrapped in URLError
        holder["res"] = ("error", "timeout" if isinstance(exc.reason, TimeoutError) else "URLError")
    except Exception as exc:  # timeout, refused connection, bad URL: no secret in the class name
        holder["res"] = ("error", type(exc).__name__)


def answer_text(body):
    """The joined candidates[0].content.parts[].text; None when the body has no such shape."""
    try:
        parts = json.loads(body)["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def http_why(code):
    if code in (429, 402):
        return "usage-limit"
    if code == 401:
        return "auth"
    if code in (403, 404):
        return "no-access"
    return f"http {code}"


def rest_hop(st, model, budget):
    """One generateContent call. The token call and the HTTP call share one budget; the HTTP call
    runs in a daemon thread that is abandoned at the hop end."""
    end = time.monotonic() + budget
    header, value, why = credential(st, end)
    if why:
        return None, why
    left = end - time.monotonic()
    if left <= 0:
        return None, "deadline"
    req = urllib.request.Request(rest_url(st, model), data=rest_body(st["prompt"], st["effort"]),
                                 headers={"Content-Type": "application/json", header: value}, method="POST")
    holder = {}
    worker = threading.Thread(target=post, args=(req, left, holder), daemon=True)
    worker.start()
    worker.join(max(0, end - time.monotonic()))
    res = holder.get("res")
    if res is None:
        return None, "deadline"
    code, body = res
    if code == "error":
        st["log"](f"{st['fallback']}: {body}")
        return None, "deadline" if "timeout" in body.lower() else "network"
    if code != 200:
        return None, http_why(code)
    text = answer_text(body)
    return (None, "bad-json") if text is None else st["validate"](text)


# ---------------------------------------------------------------- the chain


def hops(st):
    """The four hops in order: (backend kind, model)."""
    return [("agy", st["model"]), ("fallback", st["model"]),
            ("agy", st["model2"]), ("fallback", st["model2"])]


def eligible(st, hop):
    kind, model = hop
    if kind == "agy":
        return st["agy_ok"] and bool(agy_id(st["agy_ids"], model, st["effort"]))
    return st["fb_ok"]


def budget_for(st, i, left):
    later = any(eligible(st, h) for h in hops(st)[i + 1:])
    return left * SHARE if later else left


def run_hop(st, hop, budget):
    """Runs one hop. Returns (obj, why, backend name)."""
    kind, model = hop
    if kind == "agy":
        obj, why = agy_hop(st, agy_id(st["agy_ids"], model, st["effort"]), budget)
        return obj, why, "agy"
    obj, why = rest_hop(st, model, budget)
    return obj, why, st["fallback"]


def after_failure(st, kind, why):
    """Updates the chain state after a failed hop. Returns True when the chain must stop."""
    if kind == "fallback" and why == "usage-limit":
        return True
    if kind == "fallback" and why == "auth":
        st["fb_ok"], st["fb_auth"] = False, True
    if kind == "agy" and why == "usage-limit":
        st["agy_ok"], st["agy_limit"] = False, True
    return False


def walk(st, end):
    """Walks the hops. Returns (obj, why, backend, model); obj None when no hop answered."""
    why, last = "", ""
    for i, hop in enumerate(hops(st)):
        if not eligible(st, hop):
            continue
        left = end - time.monotonic()
        if left <= 0:
            return None, "deadline", "", ""
        budget = budget_for(st, i, left)
        obj, why, backend = run_hop(st, hop, budget)
        st["log"](f"hop {i + 1} {backend} {hop[1]} budget {budget:.0f}s -> {why or 'ok'}")
        if obj is not None and not why:
            return obj, "", backend, hop[1]
        if after_failure(st, hop[0], why):
            return None, why, "", ""
        last = "agy" if hop[0] == "agy" and st["agy_out"] else ""
    return None, why, last, ""  # backend agy only after agy "Eligibility check failed" (AR9)


def setup(prompt_path, out_dir, gemini_cfg, validate, no_agy, project_root):
    """The chain state: config, flags and what agy and the fallback can still do."""
    with open(prompt_path, errors="replace") as fh:
        prompt = fh.read()
    fallback = gemini_cfg.get("fallback") or "none"
    vertex_ok = fallback != "vertex" or bool((gemini_cfg.get("vertex") or {}).get("project"))
    agy_prompt = prompt.rstrip() + "\n\n" + AGY_TAIL
    return {
        "cfg": gemini_cfg, "validate": validate, "project_root": project_root,
        "log": Log(os.path.join(out_dir, "gemini.log")), "prompt": prompt, "agy_prompt": agy_prompt,
        "model": gemini_cfg.get("model") or "gemini-4-carbon",
        "model2": gemini_cfg.get("model_fallback") or "gemini-4-argon",
        "effort": gemini_cfg.get("effort") or "high", "fallback": fallback,
        "agy_wanted": bool(gemini_cfg.get("agy", True)) and not no_agy,
        "agy_small": len(agy_prompt.encode("utf-8")) <= AGY_PROMPT_LIMIT,
        "fb_ok": fallback in ("vertex", "key") and vertex_ok,
        "agy": None, "agy_ids": [], "agy_ok": False, "fb_auth": False, "agy_limit": False,
        "agy_out": False, "models_why": "",
    }


def open_agy(st, out_dir, end):
    """Finds agy and lists its models when the agy hops are wanted. Returns False when its binary is missing."""
    if not st["agy_wanted"]:
        return True
    if not st["agy_small"]:
        st["log"]("agy: prompt over the argument limit, agy hops skipped")
        return True
    st["agy"] = find_bin("agy")
    if not st["agy"]:
        st["log"]("agy: binary not found")
        return False
    st["work"] = work_dir(out_dir)
    st["agy_ids"], st["models_why"] = agy_models(st["agy"], end - time.monotonic(), st["log"])
    st["agy_ok"] = True
    return True


def work_dir(out_dir):
    """An empty directory of the voter's own, so its cwd shows no other voter's files."""
    work = os.path.join(out_dir, "work-gemini")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    return work


def status(st, obj, why, backend, model, out_dir):
    """The status line; writes <out>/gemini.json on ok, as for Codex answers."""
    line = {"voter": "gemini", "status": "missing", "why": why, "file": "",
            "backend": backend if obj is None else "", "model": "",
            "note": NOTE_AGY_LIMIT if st["agy_limit"] else ""}
    if obj is None:
        if st["fb_auth"] and why != "usage-limit":
            line["why"] = "auth"
        return line
    path = os.path.join(out_dir, "gemini.json")
    with open(path, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    if st["fb_auth"] and not line["note"]:
        line["note"] = NOTE_FB_AUTH
    line.update(status="ok", why="", file=path, backend=backend, model=model)
    return line


def no_hop_why(st, binary_found):
    """('', '') when some hop is possible, else (why, backend): the failed `agy models` call
    (backend agy), 'missing-binary' or 'no-backend'."""
    if any(eligible(st, h) for h in hops(st)):
        return "", ""
    if st["models_why"]:
        return st["models_why"], "agy"
    return ("missing-binary" if not binary_found else "no-backend"), ""


def run_gemini(prompt_path, out_dir, deadline_s, gemini_cfg, validate, no_agy=False, project_root=None):
    """One Gemini answer through the backend chain; returns the status line dict."""
    end = time.monotonic() + deadline_s
    try:
        os.remove(os.path.join(out_dir, "gemini.json"))
    except FileNotFoundError:
        pass
    st = setup(prompt_path, out_dir, gemini_cfg, validate, no_agy, project_root)
    found = open_agy(st, out_dir, end)
    why, backend = no_hop_why(st, found)
    if why:
        st["log"](f"no hop possible: {why}")
        return status(st, None, why, backend, "", out_dir)
    obj, why, backend, model = walk(st, end)
    return status(st, obj, why, backend, model, out_dir)
