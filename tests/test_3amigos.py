#!/usr/bin/env python3
"""Tests for plugins/3amigos/skills/3amigos/scripts/{panel,tally}.py.

panel.py is run for real against a stub `codex` binary put first on PATH (find_bin uses
shutil.which first, so the stub wins over any real install). The stub's behaviour is chosen
by a mode file and every call is counted, so retries can be asserted. HOME is redirected to a
tempdir; no network, no real voter is called.

Run:  python3 tests/test_3amigos.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "3amigos" / "skills" / "3amigos" / "scripts"
PANEL = SCRIPTS / "panel.py"
TALLY = SCRIPTS / "tally.py"

GOOD = {"ideas": ["a", "b", "c"]}

# The codex stub. mode file: ok | short | fail | slowfail | hang | limit | limitok. Counts calls in
# <name>.calls and records its cwd and its -C argument in <name>.cwd.
STUB = r'''#!/usr/bin/env python3
import os, sys, time
name = os.path.basename(sys.argv[0])
d = os.environ["STUB_DIR"]
open(os.path.join(d, name + ".calls"), "a").write("x")
mode = open(os.path.join(d, name + ".mode")).read().strip()
open(os.path.join(d, name + ".cwd"), "w").write(os.getcwd() + "\n" + sys.argv[sys.argv.index("-C") + 1])
if mode in ("limit", "limitok"):  # codex reports it on stderr; limitok exits 0
    sys.stderr.write("You've hit your usage limit.\n")
    sys.exit(1 if mode == "limit" else 0)
if mode == "hang":
    time.sleep(60)
if mode == "slowfail":
    time.sleep(4)
if mode in ("fail", "slowfail"):
    sys.stderr.write("boom\n")
    sys.exit(3)
body = '{"ideas": ["a", "b", "c"]}' if mode == "ok" else '{"ideas": ["a"]}'
text = "Here you go:\n```json\n" + body + "\n```\n"
sys.stdin.read()
out = sys.argv[sys.argv.index("-o") + 1]
open(out, "w").write(text)
'''


def write_json(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class TallyTest(unittest.TestCase):
    def tally(self, answers: dict, *extra, fields="verdict", expect_ok=True):
        """Run tally.py on one file per voter; return (summary, rows), or the process when expect_ok is False.

        A key may hold a subdir ("a/codex"); a list value becomes {"items": [...]}, any other value is
        written as the whole file (a str verbatim, so a broken JSON file can be tested).
        """
        tmp = Path(tempfile.mkdtemp())
        files = []
        for name, body in answers.items():
            path = tmp / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(body, str):
                path.write_text(body, encoding="utf-8")
            else:
                write_json(path, {"items": body} if isinstance(body, list) else body)
            files.append(str(path))
        p = subprocess.run([sys.executable, str(TALLY), "--list", "items", "--id", "id", "--fields", fields,
                            *extra, *files], capture_output=True, text=True, timeout=30)
        if not expect_ok:
            self.assertNotEqual(p.returncode, 0, p.stdout)
            self.assertEqual(list(tmp.rglob("tally.json")), [])
            return p
        self.assertEqual(p.returncode, 0, p.stderr)
        summary = json.loads(p.stdout)
        return summary, json.loads(Path(summary["file"]).read_text(encoding="utf-8"))

    def test_agree_majority_and_split(self):
        def item(i, v):
            return {"id": i, "verdict": v}
        summary, rows = self.tally({
            "codex": [item(1, "keep"), item(2, "cut"), item(3, "keep")],
            "fable": [item(1, "keep"), item(2, "cut"), item(3, "cut")],
            "opus": [item(1, "keep"), item(2, "keep"), item(3, "assign")],
        })
        kinds = {r["id"]: r["kind"] for r in rows}
        self.assertEqual(kinds, {1: "agree", 2: "majority", 3: "split"})
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[2]["decision"], {"verdict": "cut"})
        self.assertIsNone(by_id[3]["decision"])
        self.assertEqual((summary["items"], summary["agree"], summary["majority"], summary["split"]), (3, 1, 1, 1))

    def test_single_vote_is_insufficient_not_majority(self):
        summary, rows = self.tally({"codex": [{"id": 1, "verdict": "keep"}]}, "--voters", "3")
        self.assertEqual(rows[0]["kind"], "insufficient")
        self.assertIsNone(rows[0]["decision"])

    def test_majority_is_computed_against_expected_panel_size(self):
        votes = {"codex": [{"id": 1, "verdict": "keep"}], "fable": [{"id": 1, "verdict": "keep"}]}
        _, rows = self.tally(votes, "--voters", "3")
        self.assertEqual(rows[0]["kind"], "majority")
        _, rows = self.tally(votes, "--voters", "4")
        self.assertEqual(rows[0]["kind"], "split")

    def test_duplicate_ids_and_missing_fields_are_invalid(self):
        summary, rows = self.tally({
            "codex": [{"id": 1, "verdict": "keep"}, {"id": 1, "verdict": "cut"}, {"id": 2, "verdict": "keep"}],
            "fable": [{"id": 1, "verdict": "keep"}, {"id": 2}],
            "opus": [{"id": 2, "verdict": "keep"}],
        })
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(summary["invalid"], 3)  # two codex copies of id 1, fable's id 2
        self.assertEqual(set(by_id[1]["votes"]), {"fable"})
        self.assertEqual(by_id[1]["kind"], "insufficient")
        self.assertEqual(set(by_id[2]["votes"]), {"codex", "opus"})
        self.assertEqual(by_id[2]["kind"], "majority")

    def test_more_files_than_voters_is_an_error(self):  # F1: a 2:2 tie came out as "majority"
        p = self.tally({"codex": [{"id": 1, "verdict": "keep"}], "fable2": [{"id": 1, "verdict": "keep"}],
                        "claude": [{"id": 1, "verdict": "cut"}], "fable": [{"id": 1, "verdict": "cut"}]},
                       "--voters", "3", expect_ok=False)
        self.assertIn("--voters", p.stderr)

    def test_voters_below_one_is_an_error(self):  # review F3: --voters 0 bypassed the file count check
        p = self.tally({"codex": [{"id": 1, "verdict": "keep"}], "fable": [{"id": 1, "verdict": "keep"}]},
                       "--voters", "0", expect_ok=False)
        self.assertIn("--voters", p.stderr)

    def test_duplicate_voter_name_is_an_error(self):  # F2: a/codex.json overwrote b/codex.json
        p = self.tally({"a/codex": [{"id": 1, "verdict": "keep"}], "b/codex": [{"id": 1, "verdict": "cut"}]},
                       expect_ok=False)
        self.assertIn("codex", p.stderr)

    def test_ids_of_mixed_types_are_one_item_sorted_naturally(self):  # F5: TypeError in sorted
        summary, rows = self.tally({
            "codex": [{"id": "12", "verdict": "keep"}, {"id": 2, "verdict": "cut"}, {"id": "b", "verdict": "cut"}],
            "fable": [{"id": 12, "verdict": "keep"}, {"id": "2", "verdict": "cut"}, {"id": 10, "verdict": "cut"}],
        })
        self.assertEqual([str(r["id"]) for r in rows], ["2", "10", "12", "b"])
        self.assertEqual(rows[2]["kind"], "agree")
        self.assertEqual(set(rows[2]["votes"]), {"codex", "fable"})
        self.assertEqual(summary["items"], 4)

    def test_same_id_as_number_and_string_in_one_file_is_a_duplicate(self):  # F5
        summary, rows = self.tally({"codex": [{"id": 1, "verdict": "keep"}, {"id": "1", "verdict": "cut"}],
                                    "fable": [{"id": 1, "verdict": "keep"}]})
        self.assertEqual(summary["invalid"], 2)
        self.assertEqual(rows[0]["kind"], "insufficient")

    def test_unreadable_voter_file_is_skipped_and_reported(self):  # F6: KeyError / crash
        summary, rows = self.tally({
            "codex": [{"id": 1, "verdict": "keep"}],
            "claude": [{"id": 1, "verdict": "keep"}],
            "opus": {"other": []},
            "fable": {"items": {"id": 1}},
            "fable2": "not json {",
        }, "--voters", "5")
        self.assertEqual(sorted(s["file"].rsplit("/", 1)[1] for s in summary["skipped"]),
                         ["fable.json", "fable2.json", "opus.json"])
        self.assertTrue(all(s["why"] for s in summary["skipped"]))
        self.assertEqual(rows[0]["kind"], "split")  # 2 of 5: skipped files are missing voters

    def test_list_and_dict_field_values_are_compared_not_crashed(self):  # F6: unhashable type
        summary, rows = self.tally({
            "codex": [{"id": 1, "verdict": ["a", "b"]}, {"id": 2, "verdict": {"x": 1, "y": 2}}],
            "fable": [{"id": 1, "verdict": ["a", "b"]}, {"id": 2, "verdict": {"y": 2, "x": 1}}],
        })
        self.assertEqual([r["kind"] for r in rows], ["agree", "agree"])
        self.assertEqual(rows[0]["decision"], {"verdict": ["a", "b"]})

    def test_string_values_ignore_case_and_whitespace(self):  # PD1
        _, rows = self.tally({"codex": [{"id": 1, "verdict": "Keep "}], "fable": [{"id": 1, "verdict": "keep"}],
                              "opus": [{"id": 1, "verdict": "cut"}]})
        self.assertEqual(rows[0]["kind"], "majority")
        self.assertEqual(rows[0]["decision"], {"verdict": "Keep "})  # as the first majority voter wrote it

    def test_first_field_is_primary_and_secondary_fields_get_details(self):  # PD2
        def item(i, v, who):
            return {"id": i, "verdict": v, "assignee": who}
        summary, rows = self.tally({
            "codex": [item(1, "keep", "ann"), item(2, "keep", "ann"), item(3, "cut", "ann")],
            "fable": [item(1, "keep", "bob"), item(2, "keep", "ann"), item(3, "keep", "bob")],
            "opus": [item(1, "keep", "cy"), item(2, "cut", "bob"), item(3, "assign", "ann")],
        }, fields="verdict,assignee")
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[1]["kind"], "agree")  # all said keep, the assignee alone is split
        self.assertEqual(by_id[1]["decision"], {"verdict": "keep", "assignee": None})
        self.assertEqual(by_id[1]["details"]["assignee"]["kind"], "split")
        self.assertEqual(by_id[2]["kind"], "majority")
        self.assertEqual(by_id[2]["decision"], {"verdict": "keep", "assignee": "ann"})
        self.assertEqual(by_id[2]["details"], {"assignee": {"value": "ann", "kind": "agree"}})  # among keep voters
        self.assertEqual(by_id[3]["kind"], "split")
        self.assertIsNone(by_id[3]["decision"])
        self.assertEqual((summary["agree"], summary["majority"], summary["split"]), (1, 1, 1))

    def test_tie_for_the_top_is_split(self):  # F1 pin: unreachable via the CLI once files <= --voters
        sys.path.insert(0, str(SCRIPTS))
        import tally
        votes = {v: {"verdict": x} for v, x in (("a", "keep"), ("b", "keep"), ("c", "cut"), ("d", "cut"))}
        self.assertEqual(tally.judge(votes, ["verdict"], 3)[0], "split")

    def test_summary_lists_ids_each_voter_did_not_vote_on(self):  # PD5
        summary, _ = self.tally({
            "codex": [{"id": 1, "verdict": "keep"}, {"id": 2, "verdict": "keep"}, {"id": 3, "verdict": "keep"}],
            "fable": [{"id": 1, "verdict": "keep"}, {"id": 3}],
            "opus": [{"id": 1, "verdict": "keep"}, {"id": 2, "verdict": "keep"}, {"id": 3, "verdict": "keep"}],
        })
        self.assertEqual(summary["missing"], {"fable": [2, 3]})  # an invalid item counts as not voted

    def test_skipped_voter_misses_every_id(self):  # review F1
        summary, _ = self.tally({"codex": [{"id": 1, "verdict": "keep"}], "fable": [{"id": 1, "verdict": "keep"}],
                                 "opus": {}}, "--voters", "3")
        self.assertEqual(summary["missing"], {"opus": [1]})

    def test_letter_ids_sort_digit_runs_by_number(self):  # review F2
        _, rows = self.tally({"codex": [{"id": "F10", "verdict": "keep"}, {"id": "F2", "verdict": "keep"}]})
        self.assertEqual([r["id"] for r in rows], ["F2", "F10"])


class ExtractTest(unittest.TestCase):
    def test_braces_in_strings_and_fences_in_values_survive(self):
        sys.path.insert(0, str(SCRIPTS))
        import panel
        obj = {"ideas": ["use } and { freely", "code: ```x```"], "n": {"k": 1}}
        text = "intro {not json} ```json\n" + json.dumps(obj) + "\n``` outro"
        self.assertEqual(panel.extract(text), obj)


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "codex"
        # the running interpreter, not a slow `env python3` shim, so the stub starts fast under load
        stub.write_text(STUB.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
        stub.chmod(0o755)
        self.mode("codex", "ok")
        (self.tmp / "task.md").write_text("Propose ideas.")
        (self.tmp / "data.md").write_text("data")

    def mode(self, name, mode):
        (self.tmp / f"{name}.mode").write_text(mode)

    def calls(self, name):
        path = self.tmp / f"{name}.calls"
        return len(path.read_text()) if path.exists() else 0

    def run_panel(self, *args, path=None):
        env = dict(os.environ)
        env.update(PATH=path or f"{self.bin}{os.pathsep}{env['PATH']}", STUB_DIR=str(self.tmp), HOME=str(self.tmp))
        return subprocess.run([sys.executable, str(PANEL), *args], capture_output=True, text=True, env=env, timeout=60)

    def panel(self, *extra, voters="codex", path=None):
        out = self.tmp / "out"
        p = self.run_panel("--task", str(self.tmp / "task.md"), "--input", str(self.tmp / "data.md"),
                           "--out", str(out), "--voters", voters, *extra, path=path)
        self.assertEqual(p.returncode, 0, p.stderr)
        return {r["voter"]: r for r in map(json.loads, p.stdout.splitlines())}, out

    def test_ok_answer_with_fenced_json_is_saved(self):
        res, out = self.panel("--require", "ideas=3")
        self.assertEqual(res["codex"]["status"], "ok", res["codex"])
        self.assertEqual(json.loads((out / "codex.json").read_text()), GOOD)
        self.assertEqual(self.calls("codex"), 1)

    def test_invalid_count_is_missing_with_reason(self):
        self.mode("codex", "short")
        res, _ = self.panel("--require", "ideas=3")
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertEqual(res["codex"]["why"], "'ideas' has 1 items, expected 3")

    def test_nonzero_exit_is_retried_once_then_missing(self):
        self.mode("codex", "fail")
        res, _ = self.panel(voters="codex")
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertEqual(res["codex"]["why"], "exit 3")
        self.assertEqual(self.calls("codex"), 2)

    def test_reused_out_dir_does_not_keep_stale_results(self):
        res, out = self.panel("--require", "ideas=3", voters="codex")
        self.assertEqual(res["codex"]["status"], "ok")
        self.mode("codex", "fail")
        res, out = self.panel("--require", "ideas=3", voters="codex")
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertFalse((out / "codex.json").exists())
        self.assertFalse((out / "codex.final.txt").exists())

    def test_launch_error_is_a_missing_result(self):
        (self.tmp / ".local" / "bin").mkdir(parents=True)
        bad = self.tmp / ".local" / "bin" / "codex"
        bad.write_text("not executable")
        bad.chmod(0o644)
        (self.bin / "codex").unlink()
        res, _ = self.panel(path=f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin")  # no real codex on PATH
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertEqual(res["codex"]["why"], "launch error: PermissionError")

    def test_deadline_is_missing_and_not_retried(self):
        self.mode("codex", "hang")
        res, _ = self.panel("--deadline", "3")
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertEqual(res["codex"]["why"], "deadline")
        self.assertEqual(self.calls("codex"), 1)

    def test_timeout_is_an_alias_of_deadline(self):
        self.mode("codex", "hang")
        res, _ = self.panel("--timeout", "1")
        self.assertEqual(res["codex"]["why"], "deadline")

    def test_deadline_covers_the_retry(self):
        # first attempt fails after 4 s, so the retry gets only the 2 s left
        self.mode("codex", "slowfail")
        res, _ = self.panel("--deadline", "6", voters="codex")
        self.assertEqual(res["codex"]["why"], "deadline")
        self.assertEqual(self.calls("codex"), 2)

    def test_voter_runs_in_its_own_empty_work_dir(self):
        (self.tmp / "out").mkdir()
        (self.tmp / "out" / "opus.json").write_text(json.dumps(GOOD))  # another voter's answer
        res, out = self.panel("--require", "ideas=3")
        self.assertEqual(res["codex"]["status"], "ok", res["codex"])
        cwd, arg = (self.tmp / "codex.cwd").read_text().splitlines()
        work = out / "work-codex"
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(work))
        self.assertEqual(os.path.realpath(arg), os.path.realpath(work))
        self.assertEqual(os.listdir(work), [])

    def test_bad_command_line_exits_2_and_runs_nothing(self):
        base = ["--task", str(self.tmp / "task.md"), "--input", str(self.tmp / "data.md"), "--out", str(self.tmp / "out")]
        for extra in (["--require", "ideas"], ["--require", "ideas=-1"], ["--require", "=3"], ["--require", "ideas=\u00b2"],
                      ["--voters", "gemini"], ["--voters", "grok"], ["--voters", "codex,grok"],
                      ["--voters", "codex,codex"]):
            p = self.run_panel(*base, *extra)
            self.assertEqual(p.returncode, 2, (extra, p.stdout, p.stderr))
            self.assertEqual(p.stdout, "")
            self.assertIn("usage:", p.stderr)
        self.assertEqual(self.calls("codex"), 0)
        self.assertFalse((self.tmp / "out").exists())

    def test_usage_limit_is_not_retried(self):
        self.mode("codex", "limit")
        res, _ = self.panel()
        self.assertEqual(res["codex"]["status"], "missing")
        self.assertEqual(res["codex"]["why"], "usage-limit")
        self.assertEqual(self.calls("codex"), 1)

    def test_usage_limit_with_exit_0_is_not_retried(self):
        # empty final file, limit text on stderr
        self.mode("codex", "limitok")
        res, _ = self.panel()
        self.assertEqual(res["codex"]["why"], "usage-limit")
        self.assertEqual(self.calls("codex"), 1)

    def test_check_mode_validates_an_answer_file_and_runs_no_voter(self):
        good = write_json(self.tmp / "opus.json", GOOD)
        short = write_json(self.tmp / "fable.json", {"ideas": ["a"]})
        (self.tmp / "fable2.json").write_text("not json")
        cases = [(good, "ok", ""), (short, "missing", "'ideas' has 1 items, expected 3"),
                 (self.tmp / "fable2.json", "missing", "bad JSON: JSONDecodeError"),
                 (self.tmp / "nope.json", "missing", "no file")]
        for path, status, why in cases:
            p = self.run_panel("--check", str(path), "--require", "ideas=3")
            self.assertEqual(p.returncode, 0, p.stderr)
            line = json.loads(p.stdout)
            self.assertEqual((line["voter"], line["status"], line["why"]), (path.stem, status, why))
            self.assertEqual(line["file"], str(path) if status == "ok" else "")
        self.assertEqual(self.calls("codex"), 0)

    def test_vanished_process_group_after_deadline_is_still_deadline(self):
        sys.path.insert(0, str(SCRIPTS))
        import panel
        from unittest import mock

        class Proc:
            pid, returncode, calls = 999999, None, 0

            def communicate(self, timeout=None):
                Proc.calls += 1
                if Proc.calls == 1:
                    raise subprocess.TimeoutExpired("x", timeout)
                return b"", b""

        out = Path(tempfile.mkdtemp())
        prompt = out / "prompt.full.md"
        prompt.write_text("p")
        with mock.patch.object(panel, "find_bin", return_value="/bin/true"), \
                mock.patch.object(panel.subprocess, "Popen", return_value=Proc()), \
                mock.patch.object(panel.os, "killpg", side_effect=ProcessLookupError) as killpg:
            obj, why = panel.run_once("codex", str(prompt), str(out), 1, "medium")
        killpg.assert_called_once()
        self.assertEqual((obj, why), (None, "deadline"))


class SkillTextTest(unittest.TestCase):
    """3amigos 0.5.0: captain runs its full consensus through the panel."""

    SKILL_MD = SCRIPTS.parent / "SKILL.md"

    def description(self) -> str:
        text = self.SKILL_MD.read_text(encoding="utf-8")
        head = text.split("\n---\n", 1)[0]
        return next(line for line in head.splitlines() if line.startswith("description:"))

    def test_description_says_captain_uses_it_for_complex_decisions(self):
        description = self.description()
        self.assertIn("Captain uses it for its complex decisions", description)
        self.assertNotIn("not for captain", description.lower())
        self.assertLess(len(description), 1024)

    def test_skill_has_a_called_from_captain_section(self):
        text = self.SKILL_MD.read_text(encoding="utf-8")
        section = text.split("## Called from captain", 1)[1].split("\n## ", 1)[0]
        for needle in ("`--out`", "tmp/captain/<run>/amigos-<ID>/", "park time caps the deadline",
                       "min(300 s, park − 5 min)", "park − 5 min is under 60 s",
                       "config `tools` is honoured",
                       "Fable stand-in starts at once", "`no consensus`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, section)

    def test_version_is_0_5_0_in_both_manifests(self):
        plugin = json.loads((SCRIPTS.parents[2] / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], "0.5.0")
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        entry = next(p for p in market["plugins"] if p["name"] == "3amigos")
        self.assertEqual(entry["version"], "0.5.0")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
