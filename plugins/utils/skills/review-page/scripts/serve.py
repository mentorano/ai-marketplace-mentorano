#!/usr/bin/env python3
"""Serve the owner review page on 127.0.0.1 and keep the owner's comments.

Usage: serve.py <review folder> [--port N] [--lan]     (no --port, or 0: a free port)

Serves the folder read-only. POST /comments with {"id", "verdict", "text"} appends
{"ts", "id", "verdict", "text"} to <folder>/comments.jsonl; GET /comments returns every row.
`verdict` is one of ok, change, question; `id` must be a section of sections.json; a text over
MAX_TEXT characters is refused (413), never cut.
--lan: also reachable from the owner's phone on the same local network. The server listens on
every interface; a request from another machine needs the random key of this start, given once
in the LAN link (?k=<key>) and kept in a cookie after that. No network found → loopback only.
On start it writes <folder>/server.json ({"url", "lan_url" (null without --lan or a network),
"port", "pid", "started"}), prints `READY <url>` and, with a LAN address, `LAN <lan url>`.
Standard library only; the file name stays serve.py, so a process check that looks for it
(captain's R14) still finds it.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import sys
import threading
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from review_common import COMMENTS, SECTIONS, SERVER, VERDICTS, BadInput, load_sections, read_comments

HOST = "127.0.0.1"
ANY = "0.0.0.0"
COOKIE = "review_key"
MAX_TEXT = 20_000
# room for MAX_TEXT characters at their longest JSON form (\uXXXX\uXXXX, 12 bytes) plus the rest
MAX_BODY = 12 * MAX_TEXT + 10_000


class Handler(SimpleHTTPRequestHandler):
    lock = threading.Lock()

    def __init__(self, *args, folder: Path, quiet: bool, **kwargs):
        self.folder = Path(folder).resolve()
        self.quiet = quiet
        super().__init__(*args, directory=str(folder), **kwargs)

    def log_message(self, format, *args):
        if not self.quiet:
            super().log_message(format, *args)

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _own_origins(self) -> set[str]:
        port = self.server.server_address[1]
        hosts = [HOST, "localhost"] + ([self.server.lan_ip] if self.server.lan_ip else [])
        return {f"http://{host}:{port}" for host in hosts}

    def _local_request(self) -> bool:
        """The Host is this server, a browser's Origin, when sent, is this page, and a client
        from another machine (--lan) holds the key of this start."""
        host = self.headers.get("Host", "")
        if f"http://{host}" not in self._own_origins():
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self._own_origins():
            return False
        return self.client_address[0] in self.server.local_clients or self._has_key()

    def _has_key(self) -> bool:
        """The key from the link (?k=, then remembered in a cookie) or from that cookie."""
        if not self.server.token:
            return False
        token = self.server.token.encode()
        # compared as bytes: compare_digest refuses a str that is not ASCII (?k=%D0%AF)
        given = parse_qs(urlsplit(self.path).query).get("k", [""])[0]
        if given and hmac.compare_digest(given.encode(), token):
            self._set_cookie = True
            return True
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == cookie_name(self.server) and hmac.compare_digest(value.encode(), token):
                return True
        return False

    def translate_path(self, path: str) -> str:
        """The static path, refused (a name that does not exist) when it resolves outside the
        folder, e.g. through a symlink."""
        local = super().translate_path(path)
        real = Path(local).resolve()
        if real != self.folder and self.folder not in real.parents:
            return str(self.folder / ".outside-refused" / "missing")  # → 404
        return local

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        if getattr(self, "_set_cookie", False):
            self.send_header("Set-Cookie", f"{cookie_name(self.server)}={self.server.token}; "
                                           "Path=/; HttpOnly; SameSite=Strict")
            self._set_cookie = False
        super().end_headers()

    def do_GET(self):
        if not self._local_request():
            return self._json(403, {"error": "local requests only"})
        if self.path.split("?")[0] == "/comments":
            rows = [{k: v for k, v in row.items() if k != "line"} for row in read_comments(self.folder)]
            return self._json(200, rows)
        return super().do_GET()

    def do_HEAD(self):
        if not self._local_request():
            return self._json(403, {"error": "local requests only"})
        return super().do_HEAD()

    def do_POST(self):
        if not self._local_request():
            return self._json(403, {"error": "local requests only"})
        if self.path.split("?")[0] != "/comments":
            return self._json(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad Content-Length"})
        if size <= 0 or size > MAX_BODY:
            return self._json(413 if size > MAX_BODY else 400, {"error": "body size"})
        try:
            data = json.loads(self.rfile.read(size).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "bad json"})
        if not isinstance(data, dict):
            return self._json(400, {"error": "an object is needed"})
        sid, verdict, text = data.get("id"), data.get("verdict"), data.get("text", "")
        if not isinstance(text, str):
            return self._json(400, {"error": "text must be a string"})
        text = text.strip()
        if len(text) > MAX_TEXT:  # refused, not cut: the page keeps the owner's text in its box
            return self._json(413, {"error": f"text over {MAX_TEXT} characters"})
        if verdict not in VERDICTS:
            return self._json(400, {"error": f"verdict must be one of {', '.join(VERDICTS)}"})
        if not isinstance(sid, str) or sid not in self._section_ids():
            return self._json(400, {"error": "unknown section id"})
        row = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "id": sid,
               "verdict": verdict, "text": text}
        line = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock, open(self.folder / COMMENTS, "ab+") as log:
            # a last line cut by a crash gets its own end first, so it never swallows this row
            if log.seek(0, os.SEEK_END) > 0:
                log.seek(-1, os.SEEK_END)
                if log.read(1) != b"\n":
                    line = b"\n" + line
            log.write(line)  # append mode: the write goes to the end whatever was read
        return self._json(200, row)

    def _section_ids(self) -> set[str]:
        # read at every POST: a rebuilt page needs no restart
        try:
            return {s["id"] for s in load_sections(self.folder / SECTIONS)["sections"]}
        except BadInput:
            return set()


def cookie_name(server) -> str:
    # a browser shares cookies across ports of one host: one name per server keeps two pages apart
    return f"{COOKIE}_{server.server_address[1]}"


def usable(ip: str) -> bool:
    return not ip.startswith(("127.", "169.254.")) and ip != ANY


def find_lan_ip() -> str | None:
    """This machine's address on its local network: the source address the system picks toward
    a private address (a UDP connect sends no packet); with no route for that (a network with no
    default route), an IPv4 address of this host's name. None when there is no such network."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            ip = probe.getsockname()[0]
            if usable(ip):
                return ip
        except OSError:
            pass
    try:
        names = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    return next((info[4][0] for info in names if usable(info[4][0])), None)


def make_server(folder: Path, port: int = 0, quiet: bool = False, lan_ip: str | None = None,
                bind: str | None = None) -> ThreadingHTTPServer:
    """Loopback only by default. With `lan_ip`, it listens on every interface (or on `bind`)
    and a client that is not loopback needs `server.token`."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise BadInput(f"{folder}: no such folder")
    handler = partial(Handler, folder=folder, quiet=quiet)
    server = ThreadingHTTPServer((bind or (ANY if lan_ip else HOST), port), handler)
    server.lan_ip = lan_ip
    server.token = secrets.token_urlsafe(16) if lan_ip else None
    server.local_clients = {HOST}
    return server


def lan_url(server: ThreadingHTTPServer) -> str | None:
    if not server.lan_ip:
        return None
    return f"http://{server.lan_ip}:{server.server_address[1]}/index.html?k={server.token}"


def main(argv: list[str]) -> int:
    args = list(argv)
    port = 0
    lan = "--lan" in args
    if lan:
        args.remove("--lan")
    if "--port" in args:
        at = args.index("--port")
        try:
            port = int(args[at + 1])
        except (IndexError, ValueError):
            print("--port needs a number", file=sys.stderr)
            return 2
        del args[at:at + 2]
    if len(args) != 1 or args[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    folder = Path(args[0]).resolve()
    lan_ip = find_lan_ip() if lan else None
    if lan and not lan_ip:
        print("NO LAN: no local network address found; serving on 127.0.0.1 only", file=sys.stderr)
    try:
        load_sections(folder / SECTIONS)
        server = make_server(folder, port, lan_ip=lan_ip)
    except BadInput as error:
        print(error, file=sys.stderr)
        return 2
    except OSError as error:
        print(f"cannot bind port {port}: {error}", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{server.server_address[1]}/index.html"
    info = {"url": url, "lan_url": lan_url(server), "port": server.server_address[1],
            "pid": os.getpid(), "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / SERVER).write_text(json.dumps(info, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"READY {url}", flush=True)
    if info["lan_url"]:
        print(f"LAN {info['lan_url']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
