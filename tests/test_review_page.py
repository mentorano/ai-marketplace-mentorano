#!/usr/bin/env python3
"""Tests for the owner review page (utils:review-page): plugins/utils/skills/review-page/scripts/.

build.py turns sections.json into index.html, serve.py keeps the owner's comments in
comments.jsonl, comments.py prints them for the triage. The server runs on a free 127.0.0.1
port in a thread, in a temp folder; no network beyond 127.0.0.1.

Run:  python3 tests/test_review_page.py
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "utils" / "skills" / "review-page" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"review_page_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load("build")
serve = load("serve")
comments = load("comments")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def sections() -> dict:
    return {
        "title": "Review — the dialogs",
        "intro": "Two changes to review.",
        "sections": [
            {"id": "LH1", "title": "The reset dialog", "task": "ZD3",
             "text": ["New text <b>with a tag</b> and {{SECTIONS}}."], "look": "is the text clear",
             "links": [{"href": "http://127.0.0.1:5173/admin", "label": "live"}],
             "notes": ["No picture of the empty state."],
             "shots": [{"src": "LH1/dialog 390x844.png", "caption": "phone, dark"}],
             "code": "- old\n+ new"},
            {"id": "LH2", "title": "Privacy", "text": "One paragraph."},
        ],
    }


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "review"
        (self.dir / "LH1").mkdir(parents=True)
        (self.dir / "LH1" / "dialog 390x844.png").write_bytes(PNG)
        self.write(sections())

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data) -> None:
        (self.dir / "sections.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class BuildTest(Folder):
    def test_builds_an_escaped_page_with_every_section(self):
        code, text = build.build(self.dir)
        self.assertEqual(code, 0, text)
        self.assertTrue(text.startswith("BUILT "), text)
        page = (self.dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('<section id="LH1" data-title="The reset dialog">', page)
        self.assertIn('<section id="LH2"', page)
        self.assertIn("&lt;b&gt;with a tag&lt;/b&gt;", page)
        self.assertNotIn("<b>with a tag</b>", page)
        # a placeholder inside the owner's text is not expanded
        self.assertIn("and {{SECTIONS}}.", page)
        self.assertNotRegex(page, r"\{\{(TITLE|INTRO)\}\}")
        self.assertIn('src="LH1/dialog%20390x844.png"', page)
        self.assertIn("Look at: is the text clear", page)
        self.assertIn("(ZD3)", page)
        self.assertIn('href="http://127.0.0.1:5173/admin"', page)
        self.assertIn("<pre>- old\n+ new</pre>", page)
        self.assertIn("<title>Review — the dialogs</title>", page)

    def test_the_page_offers_the_three_verdicts_and_no_yes_no(self):
        build.build(self.dir)
        page = (self.dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('[["ok", "ok"], ["change", "chg"], ["question", "q"]]', page)
        self.assertNotIn('"yes"', page)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn("Download all comments (.md)", page)

    def test_a_missing_screenshot_writes_nothing(self):
        (self.dir / "LH1" / "dialog 390x844.png").unlink()
        code, text = build.build(self.dir)
        self.assertEqual(code, 1)
        self.assertIn("MISSING LH1 LH1/dialog 390x844.png", text)
        self.assertFalse((self.dir / "index.html").exists())

    def test_bad_input_is_refused(self):
        cases = {
            "duplicate id": lambda d: d["sections"][1].update(id="LH1"),
            "one-letter id": lambda d: d["sections"][0].update(id="F1"),
            "shot outside": lambda d: d["sections"][0]["shots"][0].update(src="../x.png"),
            "absolute shot": lambda d: d["sections"][0]["shots"][0].update(src="/etc/x.png"),
            "script link": lambda d: d["sections"][0]["links"][0].update(href="javascript:alert(1)"),
            "no title": lambda d: d.update(title=""),
            "no sections": lambda d: d.update(sections=[]),
            "shots not a list": lambda d: d["sections"][0].update(shots="x.png"),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                data = sections()
                change(data)
                self.write(data)
                code, _ = build.build(self.dir)
                self.assertEqual(code, 2)

    def test_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, str(SCRIPTS / "build.py"), str(self.dir)],
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = subprocess.run([sys.executable, str(SCRIPTS / "build.py")],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(bad.returncode, 2)


class ServerTest(Folder):
    def setUp(self):
        super().setUp()
        build.build(self.dir)
        self.server = serve.make_server(self.dir, port=0, quiet=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def request(self, method: str, path: str, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode("utf-8")
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def post(self, body, headers=None):
        status, data = self.request("POST", "/comments", body, headers)
        return status, json.loads(data.decode("utf-8"))

    def test_post_then_get_round_trip_persists_to_comments_jsonl(self):
        status, row = self.post({"id": "LH1", "verdict": "change", "text": "  a larger button\n"})
        self.assertEqual(status, 200, row)
        self.assertEqual((row["id"], row["verdict"], row["text"]), ("LH1", "change", "a larger button"))
        self.assertRegex(row["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(self.post({"id": "LH2", "verdict": "ok"})[0], 200)
        status, data = self.request("GET", "/comments")
        self.assertEqual(status, 200)
        rows = json.loads(data.decode("utf-8"))
        self.assertEqual([(r["id"], r["verdict"]) for r in rows], [("LH1", "change"), ("LH2", "ok")])
        self.assertEqual(set(rows[0]), {"ts", "id", "verdict", "text"})
        lines = (self.dir / "comments.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), rows[0])

    def test_the_page_and_its_screenshots_are_served(self):
        status, data = self.request("GET", "/index.html")
        self.assertEqual(status, 200)
        self.assertIn("LH1".encode("utf-8"), data)
        status, data = self.request("GET", "/LH1/dialog%20390x844.png")
        self.assertEqual((status, data), (200, PNG))

    def test_bad_comments_are_refused_and_not_written(self):
        for body in ({"id": "LH9", "verdict": "ok"}, {"id": "LH1", "verdict": "yes"},
                     {"id": "LH1", "verdict": "ok", "text": 5}, ["LH1", "ok"], {"verdict": "ok"}):
            with self.subTest(body=body):
                self.assertEqual(self.post(body)[0], 400)
        self.assertEqual(self.request("POST", "/comments", b"{not json")[0], 400)
        self.assertEqual(self.request("POST", "/elsewhere", {"id": "LH1", "verdict": "ok"})[0], 404)
        self.assertFalse((self.dir / "comments.jsonl").exists())

    def test_a_post_after_a_cut_last_line_is_kept_and_read(self):  # full r1 F5
        cut = '{"ts": "t0", "id": "LH2", "verdict": "question", "text": "'.encode("utf-8") + "é".encode("utf-8")[:1]
        (self.dir / "comments.jsonl").write_bytes(cut)
        self.assertEqual(self.post({"id": "LH1", "verdict": "ok"})[0], 200)
        status, data = self.request("GET", "/comments")
        self.assertEqual(status, 200)
        self.assertEqual([(r["id"], r["verdict"]) for r in json.loads(data.decode("utf-8"))], [("LH1", "ok")])
        out = comments.report(self.dir)
        self.assertTrue(out.startswith("Lines: 2\n"), out)
        self.assertIn("- L2 [new]", out)

    def test_a_text_over_the_limit_is_refused_not_cut(self):  # full r1 F6
        status, row = self.post({"id": "LH1", "verdict": "change", "text": "é" * (serve.MAX_TEXT + 1)})
        self.assertEqual(status, 413, row)
        self.assertFalse((self.dir / "comments.jsonl").exists())
        self.assertEqual(self.post({"id": "LH1", "verdict": "change", "text": "é" * serve.MAX_TEXT})[0], 200)

    def test_foreign_origin_or_host_is_refused(self):
        good = {"id": "LH1", "verdict": "ok"}
        self.assertEqual(self.post(good, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.post(good, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/comments", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.post(good, {"Origin": f"http://localhost:{self.port}"})[0], 200)
        self.assertEqual(self.post(good, {"Origin": f"http://127.0.0.1:{self.port}"})[0], 200)

    def test_nothing_outside_the_folder_is_served(self):
        (Path(self.tmp.name) / "secret.txt").write_text("no", encoding="utf-8")
        status, _ = self.request("GET", "/../secret.txt")
        self.assertEqual(status, 404)

    def test_a_symlink_out_of_the_folder_is_not_followed(self):  # r1 F4
        secret = Path(self.tmp.name) / "secret.txt"
        secret.write_text("no", encoding="utf-8")
        (self.dir / "link.txt").symlink_to(secret)
        status, data = self.request("GET", "/link.txt")
        self.assertEqual(status, 404)
        self.assertNotEqual(data, b"no")


class LanServerTest(Folder):
    """--lan: the owner's phone on the same network. Bound to 127.0.0.1 here (no firewall prompt
    in a test); `local_clients` emptied, so the test client counts as a phone on the LAN."""
    LAN = "192.0.2.10"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def setUp(self):
        super().setUp()
        build.build(self.dir)
        self.server = serve.make_server(self.dir, port=0, quiet=True, lan_ip=self.LAN, bind="127.0.0.1")
        self.server.local_clients = set()
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.lan = {"Host": f"{self.LAN}:{self.port}"}

    def raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        payload = None if body is None else json.dumps(body).encode("utf-8")
        conn.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response, data

    def test_a_lan_client_without_the_key_is_refused(self):
        self.assertEqual(self.raw("GET", "/index.html", headers=self.lan)[0].status, 403)
        self.assertEqual(self.raw("GET", "/index.html?k=wrong", headers=self.lan)[0].status, 403)
        self.assertEqual(self.raw("GET", "/index.html?k=%D0%AF", headers=self.lan)[0].status, 403)
        self.assertEqual(self.raw("GET", "/index.html", headers={**self.lan, "Cookie": f"{serve.COOKIE}_{self.port}=x"})[0].status, 403)
        # the right key under another server's cookie name opens nothing here
        other = {**self.lan, "Cookie": f"{serve.COOKIE}_{self.port + 1}={self.server.token}"}
        self.assertEqual(self.raw("GET", "/index.html", headers=other)[0].status, 403)
        self.assertEqual(self.raw("POST", "/comments", {"id": "LH1", "verdict": "ok"}, self.lan)[0].status, 403)
        self.assertFalse((self.dir / "comments.jsonl").exists())

    def test_the_key_in_the_link_opens_the_page_and_its_cookie_the_rest(self):
        response, _ = self.raw("GET", f"/index.html?k={self.server.token}", headers=self.lan)
        self.assertEqual(response.status, 200)
        cookie = response.getheader("Set-Cookie", "")
        self.assertIn(f"{serve.COOKIE}_{self.port}={self.server.token}", cookie)  # one name per port
        self.assertIn("HttpOnly", cookie)
        jar = {**self.lan, "Cookie": cookie.split(";")[0]}
        self.assertEqual(self.raw("GET", "/LH1/dialog%20390x844.png", headers=jar)[0].status, 200)
        posted = self.raw("POST", "/comments", {"id": "LH1", "verdict": "ok"},
                          {**jar, "Origin": f"http://{self.LAN}:{self.port}"})
        self.assertEqual(posted[0].status, 200, posted[1])
        self.assertEqual(self.raw("GET", "/comments", headers=jar)[0].status, 200)

    def test_the_lan_url_carries_the_key(self):
        self.assertEqual(serve.lan_url(self.server), f"http://{self.LAN}:{self.port}/index.html?k={self.server.token}")

    def test_find_lan_ip_falls_back_to_the_host_name_without_a_route(self):  # full r2 F1
        from unittest import mock

        class NoRoute:
            def __init__(self, *args):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def connect(self, address):
                raise OSError("Network is unreachable")

        hosts = [(2, 2, 17, "", ("127.0.0.1", 0)), (2, 2, 17, "", ("192.168.1.20", 0))]
        with mock.patch.object(serve.socket, "socket", NoRoute), \
                mock.patch.object(serve.socket, "getaddrinfo", return_value=hosts):
            self.assertEqual(serve.find_lan_ip(), "192.168.1.20")
        with mock.patch.object(serve.socket, "socket", NoRoute), \
                mock.patch.object(serve.socket, "getaddrinfo", side_effect=OSError("no name")):
            self.assertIsNone(serve.find_lan_ip())

    def test_the_lan_host_is_refused_without_lan(self):
        plain = serve.make_server(self.dir, port=0, quiet=True)
        thread = threading.Thread(target=plain.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertIsNone(serve.lan_url(plain))
            port = plain.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/index.html", headers={"Host": f"{self.LAN}:{port}"})
            self.assertEqual(conn.getresponse().status, 403)
            conn.close()
        finally:
            plain.shutdown()
            plain.server_close()
            thread.join(timeout=5)


class CommentsReportTest(Folder):
    def test_report_by_section_marks_new_rows_and_strays(self):
        rows = [{"ts": "t1", "id": "LH1", "verdict": "change", "text": "larger"},
                {"ts": "t2", "id": "LH2", "verdict": "ok", "text": ""},
                {"ts": "t3", "id": "LH1", "verdict": "question", "text": "why\nso?"},
                {"ts": "t4", "id": "ZZ9", "verdict": "ok", "text": ""}]
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n{broken\n"
        (self.dir / "comments.jsonl").write_text(text, encoding="utf-8")
        out = comments.report(self.dir, since=2)
        self.assertTrue(out.startswith("Lines: 5\n"), out)
        self.assertLess(out.index("## LH1 — The reset dialog"), out.index("## LH2 — Privacy"))
        self.assertIn("Last: question", out)
        self.assertIn("- L1 t1 **change**: larger", out)
        self.assertIn("- L3 [new] t3 **question**: why\n  so?", out)
        self.assertIn("## No section", out)
        self.assertIn("'ZZ9'", out)

    def test_a_line_still_being_written_is_left_for_the_next_read(self):  # r1 F1
        done = json.dumps({"ts": "t1", "id": "LH1", "verdict": "ok", "text": ""}, ensure_ascii=False)
        half = json.dumps({"ts": "t2", "id": "LH2", "verdict": "ok", "text": ""}, ensure_ascii=False)
        (self.dir / "comments.jsonl").write_text(done + "\n" + half, encoding="utf-8")
        out = comments.report(self.dir)
        self.assertTrue(out.startswith("Lines: 1\n"), out)
        self.assertIn("- L1 [new] t1 **ok**", out)  # no --since: every row is new
        self.assertNotIn("t2", out)

    def test_a_multibyte_character_cut_mid_write_does_not_break_the_read(self):  # r2 F2
        done = json.dumps({"ts": "t1", "id": "LH1", "verdict": "ok", "text": ""}, ensure_ascii=False)
        tail = '{"ts": "t2", "id": "LH2", "verdict": "question", "text": "'.encode("utf-8") + "é".encode("utf-8")[:1]
        (self.dir / "comments.jsonl").write_bytes(done.encode("utf-8") + b"\n" + tail)
        out = comments.report(self.dir)
        self.assertTrue(out.startswith("Lines: 1\n"), out)
        self.assertIn("- L1 [new] t1 **ok**", out)  # no --since: every row is new

    def test_no_comments_yet(self):
        out = comments.report(self.dir)
        self.assertTrue(out.startswith("Lines: 0\n"))
        self.assertEqual(out.count("Last: no comment"), 2)


class ServeCliTest(Folder):
    def test_cli_binds_a_free_local_port_and_writes_server_json(self):
        proc = subprocess.Popen([sys.executable, str(SCRIPTS / "serve.py"), str(self.dir)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            line = proc.stdout.readline().strip()
            match = re.match(r"^READY http://127\.0\.0\.1:(\d+)/index\.html$", line)
            self.assertTrue(match, line)
            info = json.loads((self.dir / "server.json").read_text(encoding="utf-8"))
            self.assertEqual(info["port"], int(match.group(1)))
            self.assertEqual(info["pid"], proc.pid)
        finally:
            proc.terminate()
            proc.communicate(timeout=10)


class UtilsSkillTextTest(unittest.TestCase):
    """The utils:review-page skill: when a normal session starts a page and how it ends it."""

    def setUp(self):
        self.text = (SCRIPTS.parent / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"---\n(.*?)\n---\n", self.text, re.S)
        self.assertIsNotNone(match, "SKILL.md has no frontmatter")
        self.frontmatter = match.group(1)
        self.body = self.text[match.end():]
        self.flat = " ".join(self.text.split())
        self.flat_body = " ".join(self.body.split())

    def test_frontmatter_names_the_skill_and_its_triggers(self):
        self.assertIn("name: review-page", self.frontmatter.splitlines())
        description = next(line for line in self.frontmatter.splitlines()
                           if line.startswith("description:"))
        for needle in ("two or more", "review page", "\"done\""):
            with self.subTest(needle=needle):
                self.assertIn(needle, description)
        self.assertRegex(description, r"[Nn]ot for yes/no")

    def test_the_body_names_the_scripts_and_their_flags(self):
        for needle in ("scripts/build.py", "scripts/serve.py", "--lan", "scripts/comments.py",
                       "--since", "start_new_session=True"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_background_agents_start_a_page_only_on_their_prompts_word(self):
        self.assertIn("only when its prompt says so", self.flat)

    def test_the_stop_command_stands_in_its_own_code_block(self):
        self.assertIn("kill <PID>", self.body)
        self.assertIn("its own code block", self.flat_body)

    def test_a_pid_that_is_no_longer_the_server_is_not_killed(self):
        self.assertIn("the server is already gone: do not kill that PID, and say so",
                      self.flat_body)
        self.assertIn("shows both `serve.py` and this page's review folder path",
                      self.flat_body)

    def test_the_owners_request_gets_a_page_also_for_one_item(self):
        self.assertIn("The owner's request always gets a page, also for a single item.",
                      self.flat_body)
        self.assertIn("One item, and the session decides on its own: no page.", self.flat_body)

    def test_the_start_one_liner_leaves_the_shell_where_it_was(self):
        line = next(line for line in self.body.splitlines() if "start_new_session=True" in line)
        self.assertNotIn("cd ", line)

    def test_a_handoff_carries_the_open_page(self):
        self.assertIn("A handoff or handover prompt written while a page is open carries the "
                      "review folder, the PID, the URL and the phone URL, and `lines read: <n>`",
                      self.flat_body)

    def test_ok_on_the_page_grants_nothing(self):
        self.assertIn("\"ok\"", self.flat_body)
        self.assertIn("never grants", self.flat_body)

    def test_the_page_is_never_published(self):
        self.assertIn("The page and its files are never a claude.ai artifact, never committed, "
                      "never published", self.flat_body)

    def test_no_captain_run_state_in_a_normal_session(self):
        self.assertNotIn("run.md", self.text)
        self.assertNotIn("## Processes", self.text)

    def test_the_readme_lists_the_skill(self):
        readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
        self.assertIn("`review-page` (since 0.9.0)", readme)
        self.assertIn("plugins/utils/skills/review-page/SKILL.md", readme)


if __name__ == "__main__":
    unittest.main()
