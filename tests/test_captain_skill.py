#!/usr/bin/env python3
"""Tests for the captain plugin: SKILL.md and references, and scripts/audit-main.py.

audit-main.py is run as a subprocess on small synthetic transcripts in tests/fixtures/captain/,
shaped like real ~/.claude/projects/*/*.jsonl files: one JSON object per line, assistant tool
calls in .message.content[] with type "tool_use", subagent entries marked isSidechain, and the
session directory in `cwd`.

Run:  python3 tests/test_captain_skill.py
"""
from __future__ import annotations

import importlib.util
import shutil
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "plugins" / "captain" / "skills" / "captain"
SKILL_MD = SKILL_DIR / "SKILL.md"
TOOLS_MD = SKILL_DIR / "reference" / "tools.md"
PROMPTS_MD = SKILL_DIR / "reference" / "prompts.md"
AUDIT = SKILL_DIR / "scripts" / "audit-main.py"
FIXTURES = ROOT / "tests" / "fixtures" / "captain"
PLUGIN_DIR = ROOT / "plugins" / "captain"
SETUP_DIR = PLUGIN_DIR / "skills" / "captain-setup"
SETUP_MD = SETUP_DIR / "SKILL.md"
NOTIFY_TMPL = SETUP_DIR / "notify.sh.tmpl"
# Approximate budget after the official guidance (SKILL.md under 500 lines, under ~5k tokens);
# 21,000 characters stands in for ~5k tokens.
SKILL_MAX_LINES = 500
SKILL_MAX_CHARS = 21_000
AGENTS_DIR = ROOT / "plugins" / "captain" / "agents"
CACHE_SKILL = "/Users/x/.claude/plugins/cache/m/captain/0.1.0/skills/captain"
FIXTURE_ARGS = ("--repo", "/repo", "--skill-root", CACHE_SKILL)
CODEX_CALL = "command timeout 1200 codex exec"
EXIT_CLEAN, EXIT_VIOLATIONS, EXIT_BAD_INPUT, EXIT_INCOMPLETE = 0, 1, 2, 3


def run_audit(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(AUDIT), *args],
                          capture_output=True, text=True, timeout=30)


def run_fixture(name: str) -> subprocess.CompletedProcess:
    return run_audit(*FIXTURE_ARGS, str(FIXTURES / name))


def code_lines(text: str) -> list[str]:
    """Lines inside fenced code blocks: the executable examples."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            lines.append(line)
    return lines


def tools_md_problems(text: str) -> list[str]:
    problems = []
    for needle in ("gpt-6-astra", "--print-timeout"):
        if needle not in text:
            problems.append(f"missing {needle}")
    code = code_lines(text)
    if not any(CODEX_CALL in line for line in code):
        problems.append(f"no executable example with {CODEX_CALL!r}")
    if any(re.search(r"grok\s+(-p|--)", line) for line in code):
        problems.append("executable grok example; grok was dropped")
    for line in text.splitlines():
        if re.search(r"--model[ =]astra\b", line):
            problems.append(f"--model astra: {line!r}")
        if "--dangerously-skip-permissions" in line and "never" not in line.lower():
            problems.append(f"flag outside a never line: {line!r}")
    return problems


def violation_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("VIOLATION")]


def load_audit():
    spec = importlib.util.spec_from_file_location("audit_main", str(AUDIT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assistant(ts: int, name, tool_input, sidechain: bool = False, cwd: str = "/repo") -> dict:
    block = {"type": "tool_use", "id": f"t{ts}", "name": name, "input": tool_input}
    return {"type": "assistant", "isSidechain": sidechain, "cwd": cwd,
            "timestamp": f"2026-09-26T11:{ts:02d}:00.000Z",
            "message": {"role": "assistant", "content": [block]}}


def read_text(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def sections(text: str, heading: str) -> list[tuple[str, str]]:
    """Split markdown into (heading line, body) for headings that start with `heading`."""
    parts = re.split(rf"(?m)^(?={re.escape(heading)} )", text)
    return [(p.splitlines()[0], p) for p in parts if p.startswith(heading + " ")]


class SkillMdTest(unittest.TestCase):
    def test_skill_md_exists_and_is_lean(self):
        text = read_text(SKILL_MD)
        lines = text.splitlines()
        self.assertLessEqual(len(lines), SKILL_MAX_LINES,
                             f"SKILL.md has {len(lines)} lines, budget is {SKILL_MAX_LINES}")
        self.assertLessEqual(len(text), SKILL_MAX_CHARS,
                             f"SKILL.md has {len(text)} characters, approximate budget "
                             f"{SKILL_MAX_CHARS} (~5k tokens)")

    def test_skill_can_be_started_by_name(self):
        text = read_text(SKILL_MD)
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertTrue(match, "no frontmatter")
        # the owner may start a run by naming the skill, so Claude must be able to invoke it
        self.assertNotIn("disable-model-invocation", match.group(1))
        description = dict(re.findall(r"(?m)^([a-z-]+):\s*(.*?)\s*$", match.group(1)))["description"]
        self.assertIn("never start a run on your own", description)
        self.assertLess(len(description), 1024)

    def test_rules_r1_to_r21_each_end_with_why(self):
        text = read_text(SKILL_MD)
        found = {}
        for head, body in sections(text, "###"):
            match = re.match(r"^### R(\d+)\b", head)
            if match:
                # a rule section ends at the next heading of any level
                body = re.split(r"(?m)^#{1,3} ", body[len(head):], maxsplit=1)[0]
                found[int(match.group(1))] = body
        self.assertEqual(sorted(found), list(range(1, 22)), "SKILL.md must have ### R1 .. ### R21")
        for number, body in found.items():
            # the section ends with a line starting **Why:** (it may wrap, but no new paragraph)
            lines = [line.strip() for line in body.strip().splitlines()]
            why = [i for i, line in enumerate(lines) if line.startswith("**Why:**")]
            self.assertTrue(why, f"R{number} has no **Why:** line")
            self.assertNotIn("", lines[why[-1]:], f"R{number} continues after its **Why:** line")


class ReferenceTextTest(unittest.TestCase):
    def test_tools_md_has_required_cli_strings_and_forbidden_flags_only_on_never(self):
        self.assertEqual(tools_md_problems(read_text(TOOLS_MD)), [])

    def test_removing_the_codex_timeout_fails_the_check(self):
        # C25 mutation regression: the check must notice a lost `timeout 1200`.
        text = read_text(TOOLS_MD).replace(CODEX_CALL, "command codex exec")
        self.assertTrue(tools_md_problems(text))

    def test_every_review_template_forbids_the_web(self):
        templates = [(head, body) for head, body in sections(read_text(PROMPTS_MD), "##")
                     if re.search(r"(?i)review prompt|consensus prompt", head)
                     and not re.search(r"(?i)runner", head)]
        self.assertTrue(templates, "prompts.md has no review template")
        for head, body in templates:
            self.assertRegex(body.lower(), r"do not browse the web", f"no no-web line in {head!r}")


def cli_flags(text: str, marker: str) -> set[str]:
    """Short and long flags after `marker` in executable examples, continuation lines joined."""
    joined = "\n".join(code_lines(text)).replace("\\\n", " ")
    flags = set()
    for line in joined.splitlines():
        if marker in line:
            rest = re.sub(r"\"[^\"]*\"|'[^']*'", " ", line.split(marker, 1)[1])
            flags.update(re.findall(r"(?<![\w<>&-])(--?[A-Za-z][A-Za-z0-9-]*)", rest))
    flags.discard("--help")
    return flags


def help_text(argv: list[str]) -> str | None:
    binary = shutil.which(argv[0]) or (os.path.expanduser(argv[0]) if os.path.isfile(
        os.path.expanduser(argv[0])) else None)
    if not binary:
        return None
    result = subprocess.run([binary, *argv[1:]], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"`{' '.join(argv)}` exited {result.returncode}")
    return result.stdout + result.stderr


class CliHelpTest(unittest.TestCase):
    """Every long flag that tools.md passes to a CLI is listed by its --help (skip if absent)."""

    def test_flag_extraction_joins_continuations_and_keeps_short_flags(self):
        text = "```bash\ntimeout 9 codex exec -m x \\\n  --json -c k=v \"<p>\" > log\n```\n"
        self.assertEqual(cli_flags(text, "codex exec"), {"-m", "--json", "-c"})

    def check(self, marker: str, argv: list[str]):
        text = help_text(argv)
        if text is None:
            self.skipTest(f"{argv[0]} is not installed")
        flags = cli_flags(read_text(TOOLS_MD), marker)
        self.assertTrue(flags, f"tools.md has no flags for an executable {marker} example")
        for flag in sorted(flags):
            self.assertIn(flag, text, f"{flag} is not in `{' '.join(argv)}`")

    def test_codex_exec_flags(self):
        self.check("codex exec", ["codex", "exec", "--help"])

    def test_agy_flags(self):
        self.check("agy -p", ["~/.local/bin/agy", "--help"])


class AgentsTest(unittest.TestCase):
    # (model, effort) per agent; Sonnet never above high (R4)
    EXPECTED = {
        "worker": ("opus", "medium"),
        "deep": ("opus", "high"),
        "light-coder": ("sonnet", "high"),
        "runner": ("sonnet", "medium"),
    }

    def test_agent_frontmatter(self):
        if not AGENTS_DIR.is_dir():
            self.skipTest("plugins/captain/agents/ does not exist")
        files = sorted(AGENTS_DIR.glob("*.md"))
        self.assertTrue(files, "agents/ has no .md file")
        for path in files:
            with self.subTest(agent=path.name):
                text = path.read_text(encoding="utf-8")
                match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
                self.assertTrue(match, "no frontmatter")
                fields = dict(re.findall(r"(?m)^([a-z-]+):\s*(.*?)\s*$", match.group(1)))
                for key in ("name", "description", "model", "effort"):
                    self.assertTrue(fields.get(key), f"missing {key}")
                self.assertIn(path.stem, self.EXPECTED, "agent without an expected model/effort")
                self.assertEqual(fields["name"], path.stem)
                self.assertEqual((fields["model"], fields["effort"]), self.EXPECTED[path.stem])

    def test_every_expected_agent_exists(self):
        self.assertEqual(sorted(p.stem for p in AGENTS_DIR.glob("*.md")), sorted(self.EXPECTED))


class AuditFixturesTest(unittest.TestCase):
    def test_clean_coordinator_session_has_no_violations(self):
        result = run_fixture("clean.jsonl")
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)
        self.assertEqual(violation_lines(result.stdout), [])

    def test_sidechain_work_is_ignored(self):
        result = run_fixture("clean.jsonl")
        self.assertNotIn("gradlew", result.stdout)

    def test_edit_and_write_on_project_files_are_flagged(self):
        # DL1: docs and a root TODO pass; source files and a plugin SKILL.md are agent work (DL2)
        result = run_fixture("edits.jsonl")
        self.assertEqual(result.returncode, EXIT_VIOLATIONS, result.stdout + result.stderr)
        found = violation_lines(result.stdout)
        self.assertEqual(len(found), 3, result.stdout)
        self.assertIn("plugins/p/skills/s/SKILL.md", found[2])
        self.assertNotIn("docs/plans", result.stdout)
        self.assertNotIn("TODO.md", "\n".join(found))
        self.assertIn("Edit", found[0])
        self.assertIn("src/app.py", found[0])
        self.assertIn("Write", found[1])
        self.assertIn("src/new_module.py", found[1])
        self.assertIn("2026-09-26T10:02:00", found[0])

    def test_build_commit_push_codex_and_artifact_are_flagged_exactly(self):
        result = run_fixture("bash-work.jsonl")
        self.assertEqual(result.returncode, EXIT_VIOLATIONS, result.stdout + result.stderr)
        found = violation_lines(result.stdout)
        self.assertEqual(len(found), 5, result.stdout)
        joined = "\n".join(found)
        for needle in ("./gradlew build", "git commit", "git push", "codex exec", "Artifact"):
            self.assertIn(needle, joined)
        self.assertNotIn("Bash: date", joined)

    def test_allowed_short_reads_and_notify_pass(self):
        result = run_fixture("allowed-reads.jsonl")
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)
        self.assertEqual(violation_lines(result.stdout), [])

    def test_agent_output_reads_are_violations(self):
        # C1, DL4: only `stat` of an agent output file is allowed, never its content; other
        # reads, also next to it, pass (DL1)
        result = run_fixture("agent-output-reads.jsonl")
        self.assertNotIn("notes.md", result.stdout)
        self.assertNotIn("handover-x.md", result.stdout)
        self.assertEqual(result.returncode, EXIT_VIOLATIONS, result.stdout + result.stderr)
        # `stat x | head -n 5 x` is outside the filter grammar: unverifiable, not a violation
        self.assertEqual(len(violation_lines(result.stdout)), 4, result.stdout)
        self.assertIn("UNVERIFIABLE", result.stdout)


class AuditInputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, lines: list[str]) -> Path:
        path = self.dir / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_help_states_what_it_cannot_see(self):
        result = run_audit("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("cannot", result.stdout.lower())
        self.assertIn("subagent", result.stdout.lower())
        self.assertIn("Task", result.stdout)
        self.assertIn("NON-ADVERSARIAL", result.stdout)

    def test_missing_file_is_bad_input(self):
        self.assertEqual(run_audit(str(self.dir / "nope.jsonl")).returncode, EXIT_BAD_INPUT)

    def test_no_argument_is_bad_input(self):
        self.assertEqual(run_audit().returncode, EXIT_BAD_INPUT)

    def test_malformed_only_is_bad_input(self):
        path = self.write("junk.jsonl", ["not json", "{broken"])
        self.assertEqual(run_audit(str(path)).returncode, EXIT_BAD_INPUT)

    def test_subagent_transcript_is_refused(self):
        sub = self.dir / "session" / "subagents"
        sub.mkdir(parents=True)
        path = sub / "agent-a1.jsonl"
        path.write_text(json.dumps(assistant(1, "Agent", {})) + "\n", encoding="utf-8")
        self.assertEqual(run_audit(str(path)).returncode, EXIT_BAD_INPUT)

    def test_stdin_dash_is_accepted(self):
        line = json.dumps(assistant(1, "Bash", {"command": "git commit -m x"})) + "\n"
        result = subprocess.run([sys.executable, str(AUDIT), "-"], input=line,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, EXIT_VIOLATIONS, result.stdout + result.stderr)

    def test_invalid_input_types_are_incomplete_not_a_crash(self):
        # C20: a list where a string belongs must not raise.
        for name, tool_input in (("Skill", {"skill": ["captain"]}),
                                 ("Bash", {"command": "date", "run_in_background": "yes"}),
                                 ("Read", {"file_path": ["TODO.md"]}),
                                 ("Glob", {"pattern": "TODO*", "path": 3})):
            with self.subTest(name=name):
                path = self.write("x.jsonl", [json.dumps(assistant(1, name, tool_input))])
                result = run_audit("--repo", "/repo", str(path))
                self.assertEqual(result.returncode, EXIT_INCOMPLETE, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("incomplete", result.stdout.splitlines()[-1])
                self.assertNotIn("0 violation", result.stdout)

    def test_json_without_records_is_incomplete(self):
        # C9: `[]`, `{}`, an unknown record type and an assistant record without a message.
        for lines in (["[]"], ["{truncated", "{}"], ['{"type":"garbage"}'], ['{"type":"assistant"}']):
            with self.subTest(lines=lines):
                result = run_audit(str(self.write("x.jsonl", lines)))
                self.assertEqual(result.returncode, EXIT_INCOMPLETE, result.stdout + result.stderr)

    def test_missing_input_on_allowed_tool_is_incomplete(self):
        for name, tool_input in (("Read", {}), ("Bash", {}), ("Agent", None), (None, {}),
                                 ("Agent", {}), ("SendMessage", {}), ("CronCreate", {"cron": "*"})):
            with self.subTest(name=name, tool_input=tool_input):
                path = self.write("x.jsonl", [json.dumps(assistant(1, name, tool_input))])
                result = run_audit(str(path))
                self.assertEqual(result.returncode, EXIT_INCOMPLETE, result.stdout + result.stderr)
                self.assertIn("UNVERIFIABLE", result.stdout)

    def test_mixed_input_reports_violation_over_incomplete(self):
        path = self.write("mixed.jsonl", [
            "{truncated",
            json.dumps({"type": "assistant"}),
            json.dumps({"type": "assistant", "message": {"content": "just text"}}),
            json.dumps(assistant(4, "Bash", {"command": "git log -n 1"})),
            json.dumps(assistant(5, "Bash", {"command": "git commit -m x"})),
            "",
        ])
        result = run_audit(str(path))
        self.assertEqual(result.returncode, EXIT_VIOLATIONS, result.stdout + result.stderr)
        self.assertEqual(len(violation_lines(result.stdout)), 1, result.stdout)
        self.assertIn("1 malformed", result.stdout)

    def test_the_owner_merge_grant_allows_switch_and_push_of_that_branch_only(self):
        def owner(ts: int, text: str) -> str:
            return json.dumps({"type": "user", "timestamp": f"2026-09-26T11:{ts:02d}:00.000Z",
                               "message": {"role": "user", "content": text}, "cwd": "/repo"})
        push = lambda ts, branch: json.dumps(assistant(ts, "Bash",
                                                       {"command": f"git push origin {branch}"}))
        path = self.write("grant.jsonl", [
            push(1, "main"),                                       # before the grant: violation
            owner(2, "<command-name>/captain</command-name>\n<command-args>merge main</command-args>"),
            push(3, "main"), json.dumps(assistant(4, "Bash", {"command": "git switch main"})),
            push(5, "feature"),                                    # not the named branch
            json.dumps({**json.loads(owner(6, "/captain merge feature")), "isSidechain": True}),
            push(7, "feature"),                                    # a sidechain grants nothing
            owner(8, "/captain off"),
            push(9, "main"),                                       # off drops the grant
        ])
        result = run_audit(str(path))
        found = violation_lines(result.stdout)
        self.assertEqual(len(found), 4, result.stdout)
        for line, minute in zip(found, ("01", "05", "07", "09")):
            self.assertIn(f"T11:{minute}:00", line)

    def test_the_owner_merge_grant_lasts_for_the_run_and_needs_the_real_envelope(self):
        def record(kind: str, ts: str, **extra) -> str:
            return json.dumps({"type": kind, "timestamp": ts, "cwd": "/repo", **extra})
        def owner(text: str) -> dict:
            return {"role": "user", "content": text}
        def skill(args: str) -> dict:
            return {"role": "assistant", "content": [{"type": "tool_use", "id": "s1", "name": "Skill",
                                                      "input": {"skill": "captain", "args": args}}]}
        push = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                  "input": {"command": "git push origin main"}}]}
        quoted = owner("Explain: <command-name>/captain</command-name><command-args>merge main</command-args>")
        path = self.write("expiry.jsonl", [
            record("user", "2026-10-02T10:00:00.000Z", message=owner("/captain merge main")),
            record("assistant", "2026-10-02T13:00:00.000Z", message=push),    # hours later: ok
            record("user", "2026-10-02T13:01:00.000Z", message=owner("/captain base release")),
            record("user", "2026-10-02T13:02:00.000Z", message=owner("/captain resume")),
            record("user", "2026-10-02T13:02:30.000Z", message=owner("/captain what is left?")),
            record("assistant", "2026-10-02T13:02:40.000Z", message=skill("what is left?")),
            record("assistant", "2026-10-02T13:03:00.000Z", message=push),    # base, resume: ok
            record("assistant", "2026-10-02T13:04:00.000Z", message=skill("end")),
            record("assistant", "2026-10-02T13:05:00.000Z", message=push),    # `captain end`
            record("user", "2026-10-02T13:06:00.000Z", message=owner("/captain merge main")),
            record("user", "2026-10-02T13:07:00.000Z", message=owner("/captain 1h")),
            record("assistant", "2026-10-02T13:08:00.000Z", message=push),    # a new start
            record("user", "2026-10-02T13:09:00.000Z", message=owner("/captain merge main")),
            record("user", "2026-10-02T13:10:00.000Z", message=owner("/captain merge topic")),
            record("assistant", "2026-10-02T13:11:00.000Z", message=push),    # a new grant
            record("user", "2026-10-02T14:00:00.000Z", message=owner("/captain merge main")),
            record("assistant", "2026-10-02T14:01:00.000Z", message=skill("merge main")),
            record("assistant", "2026-10-03T02:01:00.000Z", message=push),    # 12 h backstop
            record("user", "2026-10-03T03:00:00.000Z", message=quoted),       # a quote, no grant
            record("assistant", "2026-10-03T03:01:00.000Z", message=push),
            record("user", "nonsense", message=owner("/captain merge main")),  # no time, no grant
            record("assistant", "2026-10-03T03:02:00.000Z", message=push),
        ])
        found = violation_lines(run_audit(str(path)).stdout)
        self.assertEqual([line.split()[1][8:16] for line in found],
                         ["02T13:05", "02T13:08", "02T13:11", "03T02:01", "03T03:01", "03T03:02"])

    def test_the_owner_merge_grant_does_not_cross_repos(self):
        def record(kind: str, ts: str, cwd: str, message: dict) -> str:
            return json.dumps({"type": kind, "timestamp": ts, "cwd": cwd, "message": message})
        push = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                  "input": {"command": "git push origin main"}}]}
        path = self.write("repos.jsonl", [
            record("user", "2026-10-02T10:00:00.000Z", "/repo-a",
                   {"role": "user", "content": "/captain merge main"}),
            record("assistant", "2026-10-02T10:01:00.000Z", "/repo-a", push),
            record("assistant", "2026-10-02T10:02:00.000Z", "/repo-b", push),
        ])
        found = violation_lines(run_audit(str(path)).stdout)
        self.assertEqual([line.split()[1][11:16] for line in found], ["10:02"])

    def test_the_grant_follows_the_repository_across_its_worktrees(self):
        # Codex kp1 r1 F9: the audit binds the grant to the git common dir, like the guard
        with tempfile.TemporaryDirectory() as tmp:
            repo, other = Path(tmp) / "repo", Path(tmp) / "wt"
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-q", "--allow-empty", "-m", "x"], check=True)
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "wt",
                            str(other)], check=True)
            push = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                                      "name": "Bash",
                                                      "input": {"command": "git push origin main"}}]}
            path = self.write("worktrees.jsonl", [
                json.dumps({"type": "user", "timestamp": "2026-10-02T10:00:00.000Z",
                            "cwd": str(repo), "message": {"role": "user",
                                                          "content": "/captain merge main"}}),
                json.dumps({"type": "assistant", "timestamp": "2026-10-02T10:01:00.000Z",
                            "cwd": str(other), "message": push}),
            ])
            self.assertEqual(violation_lines(run_audit(str(path)).stdout), [])

    def test_a_push_after_resume_without_a_typed_grant_is_unverifiable(self):
        # kp1 r2 F4: an R21 successor may push on a carried grant this transcript cannot show
        def record(kind: str, ts: str, message: dict) -> str:
            return json.dumps({"type": kind, "timestamp": ts, "cwd": "/repo-a", "message": message})
        push = {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                  "input": {"command": "git push origin main"}}]}
        commit = {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Bash",
                                                    "input": {"command": "git commit -m x"}}]}
        resume = {"role": "user", "content": "/captain resume handoff=/h.md from=a name=a-r2"}
        path = self.write("resumed.jsonl", [
            record("assistant", "2026-10-02T09:59:00.000Z", push),
            record("user", "2026-10-02T10:00:00.000Z", resume),
            record("assistant", "2026-10-02T10:01:00.000Z", push),
            record("assistant", "2026-10-02T10:02:00.000Z", commit),
        ])
        out = run_audit(str(path)).stdout
        self.assertEqual([line.split()[1][11:16] for line in violation_lines(out)],
                         ["09:59", "10:02"])
        self.assertIn("grant may be carried, R21", out)

    def test_a_merge_flow_command_in_a_chain_is_a_violation(self):
        audit = load_audit()
        for command in ("git merge --no-ff topic | head -n 5", "git merge --no-ff topic; git status -s",
                        "git status -s && git commit --no-edit"):
            with self.subTest(command=command):
                kind = audit.classify("Bash", {"command": command}, Path("/repo"), audit.SKILL_ROOT)[0]
                self.assertEqual(kind, "VIOLATION")

    def test_known_content_blocks_pass(self):
        entry = {"type": "assistant", "cwd": "/repo", "message": {"content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "redacted_thinking", "data": "x"}, {"type": "text", "text": "hi"}]}}
        result = run_audit("--repo", "/repo", str(self.write("ok.jsonl", [json.dumps(entry)])))
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)

    def test_nested_tool_results_are_not_main_calls(self):
        nested = {"type": "tool_use", "id": "n1", "name": "Edit", "input": {"file_path": "/repo/a"}}
        user = {"type": "user", "cwd": "/repo", "timestamp": "2026-09-26T11:00:00Z",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": [nested]}]},
                "toolUseResult": {"content": [nested], "messages": [{"message": {"content": [nested]}}]}}
        path = self.write("nested.jsonl", [json.dumps(user), json.dumps(assistant(1, "Agent", {"prompt": "p"}))])
        result = run_audit("--repo", "/repo", str(path))
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout + result.stderr)

    def test_long_command_prints_the_whole_offending_segment(self):
        command = "git log -n 1 && " + "echo " + "x" * 300 + "\ngit push origin feature"
        path = self.write("long.jsonl", [json.dumps(assistant(1, "Bash", {"command": command}))])
        result = run_audit(str(path))
        self.assertEqual(result.returncode, EXIT_VIOLATIONS)
        self.assertIn("x" * 300, result.stdout)

    def test_repo_root_is_the_git_toplevel_of_cwd(self):
        repo = self.dir / "gitrepo"
        (repo / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        entry = assistant(1, "Write", {"file_path": str(repo / "tmp/captain/r/run.md"), "content": "x"},
                          cwd=str(repo / "sub"))
        path = self.write("sub.jsonl", [json.dumps(entry)])
        result = run_audit(str(path))
        self.assertEqual(result.returncode, EXIT_CLEAN, result.stdout)

    def test_relative_paths_resolve_against_the_record_cwd(self):
        # C33: from <repo>/plugins, tmp/captain/x is <repo>/plugins/tmp/captain/x
        repo = self.dir / "gitrepo2"
        (repo / "plugins").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        entry = assistant(1, "Write", {"file_path": "tmp/captain/x", "content": "x"},
                          cwd=str(repo / "plugins"))
        path = self.write("rel.jsonl", [json.dumps(entry)])
        self.assertEqual(run_audit(str(path)).returncode, EXIT_VIOLATIONS)

    def test_bad_record_and_content_shapes_are_incomplete(self):
        # C35, C36
        for line in ('{"type":[]}', '{"type":{}}',
                     json.dumps({"type": "assistant", "cwd": "/repo", "message": {"content": [42, {}]}}),
                     json.dumps(assistant(1, "Agent", {"prompt": []})),
                     json.dumps({"type": "assistant", "cwd": "/repo", "message": {"content": [
                         {"type": "future_tool", "name": "Write",
                          "input": {"file_path": "src/x", "content": "x"}}]}}),
                     json.dumps({"type": "assistant", "cwd": "/repo",
                                 "message": {"content": [{"type": "text"}]}}),
                     # C36 regression: an unhashable block type must not raise
                     json.dumps({"type": "assistant", "message": {"content": [{"type": []}]}}),
                     json.dumps({"type": "assistant", "message": {"content": [{"type": {}}]}}),
                     json.dumps({"type": "assistant", "cwd": "/repo",
                                 "message": {"content": [{"type": "thinking", "thinking": 3}]}}),
                     json.dumps(assistant(1, "Write", {"file_path": "tmp/captain/x"}))):
            with self.subTest(line=line):
                result = run_audit("--repo", "/repo", str(self.write("x.jsonl", [line])))
                self.assertEqual(result.returncode, EXIT_INCOMPLETE, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_cwd_outside_git_without_repo_is_incomplete(self):
        entry = assistant(1, "Write", {"file_path": "tmp/captain/r/run.md", "content": "x"},
                          cwd=str(self.dir))
        path = self.write("nogit.jsonl", [json.dumps(entry)])
        self.assertEqual(run_audit(str(path)).returncode, EXIT_INCOMPLETE)

    def test_repo_option_overrides_missing_cwd(self):
        entry = assistant(1, "Write", {"file_path": "tmp/captain/r/run.md", "content": "x"})
        del entry["cwd"]
        path = self.write("nocwd.jsonl", [json.dumps(entry)])
        self.assertEqual(run_audit(str(path)).returncode, EXIT_INCOMPLETE)
        self.assertEqual(run_audit("--repo", "/repo", str(path)).returncode, EXIT_CLEAN)


class ToolRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def kind(self, name: str, tool_input: dict, root: str = "/repo") -> str:
        return self.audit.classify(name, tool_input, Path(root), self.audit.SKILL_ROOT)[0]

    def test_task_is_the_old_name_of_agent(self):
        self.assertEqual(self.kind("Task", {"prompt": "p"}), "ok")
        self.assertEqual(self.kind("Agent", {"prompt": "p"}), "ok")

    def test_skill_names_are_exact(self):
        for skill in ("captain", "captain:captain", "captain-setup", "captain:captain-setup",
                      "3amigos", "3amigos:3amigos"):
            self.assertEqual(self.kind("Skill", {"skill": skill}), "ok", skill)
        for skill in ("msg-notify", "unrelated:captain", "other:msg-notify", "commit-commands:commit",
                      "other:captain-setup", "captain:setup"):
            self.assertEqual(self.kind("Skill", {"skill": skill}), "VIOLATION", skill)

    def test_other_tools_are_violations(self):
        for name in ("NotebookEdit", "Artifact", "WebFetch", "mcp__serena__find_symbol",
                     "ExitWorktree"):
            self.assertEqual(self.kind(name, {"x": 1}), "VIOLATION", name)
        self.assertEqual(self.kind("EnterWorktree", {"name": "w1"}), "ok")
        self.assertEqual(self.kind("Grep", {"pattern": "x", "path": "/anywhere/src"}), "ok")
        # DL4: never an agent's output file
        self.assertEqual(self.kind("Grep", {"pattern": "x", "path": "/tmp/u/tasks/a1.output"}),
                         "VIOLATION")
        self.assertEqual(self.kind("Grep", {"pattern": 3}), "UNVERIFIABLE")
        self.assertEqual(self.kind("Grep", {"pattern": "x", "path": "/tmp/u/tasks"}), "VIOLATION")
        self.assertEqual(self.kind("Grep", {"pattern": "x", "path": "/tmp/u", "glob": "*.output"}),
                         "VIOLATION")

    def test_dl2_bash_calls_are_agent_work(self):
        def bash(command, **extra):
            return self.kind("Bash", {"command": command, **extra})
        self.assertEqual(bash("date", timeout=120000), "ok")
        self.assertEqual(bash("date", timeout=120001), "VIOLATION")
        self.assertEqual(bash("sleep 300", run_in_background=True), "ok")
        for command in ("git status -s", "npm test", "cat x"):
            with self.subTest(command=command):
                self.assertEqual(bash(command, run_in_background=True), "VIOLATION")
        # Edit is allowed on run state, so a malformed one is unverifiable, like Write
        self.assertEqual(self.kind("Edit", {"x": 1}), "UNVERIFIABLE")


class PathRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "tmp" / "captain").mkdir(parents=True)
        (self.repo / "src").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def kind(self, name: str, tool_input: dict, skill_root=None) -> str:
        if name == "Write":
            tool_input = {"content": "x", **tool_input}
        return self.audit.classify(name, tool_input, self.repo, skill_root or self.audit.SKILL_ROOT)[0]

    def test_kp1_r1_path_bypasses_are_denied(self):
        # Codex kp1 r1: F3 a TODO-named source file, F5 a skill file in another letter case
        for path in ("TODO.py", "TODO.sh", "TODO.json", "docs/SKILL.MD", "docs/skill.md",
                     "docs/Skills/x/reference/tools.md", "docs/SKILLS/x.md"):
            with self.subTest(path=path):
                self.assertEqual(self.kind("Write", {"file_path": path}), "VIOLATION")
        for path in ("TODO", "TODO.md", "TODO-later.txt", "docs/plans/skill-notes.md"):
            with self.subTest(path=path):
                self.assertEqual(self.kind("Write", {"file_path": path}), "ok")

    def test_a_recursive_grep_above_an_output_file_is_denied(self):
        # Codex kp1 r1 F4: Grep over a temp directory that holds tasks/<id>.output reads it
        session = Path(self.tmp.name) / "session"
        (session / "tasks").mkdir(parents=True)
        (session / "scratchpad").mkdir()
        (session / "tasks" / "a.output").write_text("x\n")
        for base in (self.tmp.name, str(session)):
            with self.subTest(base=base):
                self.assertEqual(self.kind("Grep", {"pattern": ".", "path": base,
                                                    "output_mode": "content"}), "VIOLATION")
        self.assertEqual(self.kind("Grep", {"pattern": ".", "path": str(session / "scratchpad")}),
                         "ok")
        self.assertEqual(self.kind("Grep", {"pattern": ".", "path": str(self.repo)}), "ok")
        # kp1 r2 F3: a Grep without a path searches the cwd
        def grep_in(cwd):
            return self.audit.classify("Grep", {"pattern": ".", "output_mode": "content"},
                                       self.repo, self.audit.SKILL_ROOT, cwd)[0]
        self.assertEqual(grep_in(session / "tasks"), "VIOLATION")
        self.assertEqual(grep_in(session), "VIOLATION")
        self.assertEqual(grep_in(self.repo), "ok")

    def test_allowed_paths(self):
        other = str(Path(self.tmp.name) / "other-repo")
        for name, tool_input in (
            # DL1: reads and search anywhere
            ("Read", {"file_path": "docs/plans/../../src/app.py"}),
            ("Read", {"file_path": "src/TODO.py"}),
            ("Read", {"file_path": other + "/skills/captain/scripts/audit-main.py"}),
            ("Read", {"file_path": str(SKILL_DIR / "scripts" / "audit-main.py")}),
            ("Glob", {"pattern": "tmp/captain/../../src/*"}),
            ("Glob", {"pattern": "TODO*", "path": other}),
            ("Glob", {"pattern": "**/TODO*"}),
            ("Glob", {"pattern": "src/**"}),
            # DL1: edits of run state, root TODO, docs and the local settings
            ("Write", {"file_path": "TODO-next.md"}),
            ("Write", {"file_path": "docs/notes/2026-10-13-x.md"}),
            ("Write", {"file_path": str(self.repo / "docs" / "README.txt")}),
            ("Write", {"file_path": "tmp/captain/r1/run.md"}),
            ("Write", {"file_path": str(self.repo / ".claude" / "settings.local.json")}),
            ("Read", {"file_path": str(self.repo / "TODO.md")}),
            ("Read", {"file_path": "docs/plans/x.md"}),
            ("Glob", {"pattern": "TODO*"}),
            ("Glob", {"pattern": "docs/plans/*.md"}),
            ("Glob", {"pattern": "*", "path": str(self.repo / "tmp" / "captain")}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(self.kind(name, tool_input), "ok")

    def test_paths_outside_the_allowed_area(self):
        other = str(Path(self.tmp.name) / "other-repo")
        for name, tool_input in (
            ("Write", {"file_path": "tmp/captain/../../src/app.py"}),
            ("Write", {"file_path": other + "/tmp/captain/x.py"}),
            ("Write", {"file_path": str(self.repo) + "-old/tmp/captain/x.md"}),
            ("Write", {"file_path": "src/TODO.md"}),
            # DL2: code, config, scripts, README and plugin skill files, also under docs/
            ("Write", {"file_path": "README.md"}),
            ("Write", {"file_path": "docs/conf.py"}),
            ("Write", {"file_path": "docs-old/x.md"}),
            ("Write", {"file_path": "docs/SKILL.md"}),
            ("Write", {"file_path": "docs/skills/x/reference/tools.md"}),
            ("Write", {"file_path": "plugins/captain/skills/captain/SKILL.md"}),
            ("Write", {"file_path": "plugins/captain/skills/captain/reference/tools.md"}),
            ("Write", {"file_path": "docs/../src/x.md"}),
            # DL4: never an agent's output file
            ("Read", {"file_path": "/private/tmp/u/tasks/a1.output"}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertEqual(self.kind(name, tool_input), "VIOLATION")

    def test_symlink_escape_is_a_violation(self):
        (self.repo / "tmp" / "captain" / "link").symlink_to(self.repo / "src")
        self.assertEqual(self.kind("Write", {"file_path": "tmp/captain/link/app.py"}), "VIOLATION")
        # C18: the same escape through a Glob pattern
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "link").symlink_to(self.repo / "src")
        self.assertEqual(self.kind("Edit", {"file_path": "docs/link/x.md", "old_string": "a",
                                            "new_string": "b"}), "VIOLATION")
        # DL1: a Glob only lists names, so it passes anywhere
        self.assertEqual(self.kind("Glob", {"pattern": "tmp/captain/link/*"}), "ok")

    def test_recursive_glob_is_ok(self):
        self.assertEqual(self.kind("Glob", {"pattern": "tmp/captain/**/*.md"}), "ok")
        self.assertEqual(self.kind("Glob", {"pattern": "docs/plans/**/*.md"}), "ok")

    def test_own_reference_files_are_readable(self):
        self.assertEqual(self.kind("Read", {"file_path": str(SKILL_DIR / "reference" / "tools.md")}), "ok")
        self.assertEqual(self.kind("Read", {"file_path": str(SKILL_DIR / "SKILL.md")}), "ok")

    def test_skill_root_is_explicit_not_guessed_from_the_path(self):
        # C19: a directory merely named like the plugin cache is not trusted to run a script
        command = {"command": f"python3 {CACHE_SKILL}/scripts/agent-context.py a1"}
        self.assertEqual(self.kind("Bash", command), "VIOLATION")
        self.assertEqual(self.kind("Bash", command, Path(CACHE_SKILL)), "ok")


class AgentMemoryPathTest(unittest.TestCase):
    """TS6 (PT1): main may Write/Edit `.agent-memory/<topic>.md` of the repo or the run
    worktree, nothing else of the memory layout."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.run = self.repo / ".claude" / "worktrees" / "captain-run-20261013-222621"
        self.agent = self.repo / ".claude" / "worktrees" / "w-auth"
        for d in (self.repo, self.run, self.agent):
            (d / ".agent-memory").mkdir(parents=True)
            (d / ".agent-memory" / "sub").mkdir()
        rules = self.repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "project-memory").symlink_to("../../.agent-memory")
        (self.repo / "src").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, path: str, root=None) -> set[str]:
        root = root or self.repo
        return {self.audit.classify("Write", {"file_path": path, "content": "x"}, root,
                                    self.audit.SKILL_ROOT, root)[0],
                self.audit.classify("Edit", {"file_path": path, "old_string": "a",
                                             "new_string": "b"}, root,
                                    self.audit.SKILL_ROOT, root)[0]}

    def test_allowed(self):
        for path in (".agent-memory/topic.md", str(self.repo / ".agent-memory" / "topic.md"),
                     str(self.run / ".agent-memory" / "topic.md"), ".agent-memory/TOPIC.MD"):
            with self.subTest(path=path):
                self.assertEqual(self.kinds(path), {"ok"})
        # main's cwd inside the run worktree: its own root
        self.assertEqual(self.kinds(".agent-memory/topic.md", self.run), {"ok"})

    def test_denied(self):
        for path in (".agent-memory/README.md", ".agent-memory/readme.md",
                     ".claude/rules/project-memory/topic.md", ".agent-memory/../src/x.md",
                     ".agent-memory/sub/topic.md", ".agent-memory/topic.py",
                     str(self.agent / ".agent-memory" / "topic.md")):
            with self.subTest(path=path):
                self.assertEqual(self.kinds(path), {"VIOLATION"})

    def test_symlinked_or_missing_memory_dir_is_denied(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (self.run / ".agent-memory" / "sub").rmdir()
        (self.run / ".agent-memory").rmdir()
        (self.run / ".agent-memory").symlink_to(other)
        self.assertEqual(self.kinds(str(self.run / ".agent-memory" / "topic.md")), {"VIOLATION"})
        bare = Path(self.tmp.name) / "bare"
        bare.mkdir()
        self.assertEqual(self.kinds(".agent-memory/topic.md", bare), {"VIOLATION"})

    def test_bash_copy_stays_agent_work(self):
        kind = self.audit.classify("Bash", {"command": "command cp x .agent-memory/topic.md"},
                                   self.repo, self.audit.SKILL_ROOT, self.repo)[0]
        self.assertEqual(kind, "VIOLATION")


class SetupActionsTest(unittest.TestCase):
    """captain-setup runs in the main session: exactly its actions pass, near misses do not."""
    HOME = os.path.expanduser("~")

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def kind(self, name: str, tool_input: dict, root="/repo") -> str:
        if name == "Write":
            tool_input = {"content": "x", **tool_input}
        return self.audit.classify(name, tool_input, Path(root) if root else None,
                                   self.audit.SKILL_ROOT)[0]

    def bash(self, command: str) -> str:
        return self.kind("Bash", {"command": command, "run_in_background": False})

    def test_setup_files_pass(self):
        for name, path in (
            ("Write", "~/.claude/captain/config.json"),
            ("Read", "~/.claude/skills/msg-notify/SKILL.md"),
            ("Read", str(ROOT / "plugins/captain/skills/captain-setup/notify.sh.tmpl")),
            # the captain skill reads its per-user config at start
            ("Read", "~/.claude/captain/config.json"),
        ):
            for root in ("/repo", None):
                with self.subTest(name=name, path=path, root=root):
                    self.assertEqual(self.kind(name, {"file_path": path}, root), "ok")

    def test_setup_file_near_misses(self):
        for name, path in (
            ("Write", "~/.claude/captain/other.json"),
            ("Write", "~/.claude/captain/notify.sh.bak"),
            ("Write", "/other/.claude/captain/config.json"),
            ("Write", "~/.claude/skills/msg-notify/SKILL.md"),
            ("Write", str(ROOT / "plugins/captain/skills/captain-setup/notify.sh.tmpl")),
        ):
            with self.subTest(name=name, path=path):
                self.assertEqual(self.kind(name, {"file_path": path}), "VIOLATION")

    def test_main_never_writes_the_notify_wrapper(self):
        # Codex kp1 r1 F2 (owner OP1): main could write notify.sh, then run it; a runner writes it
        wrapper = self.HOME + "/.claude/captain/notify.sh"
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "docs").mkdir()
            (repo / "docs" / "n.md").symlink_to(wrapper)
            for name, tool_input in (
                    ("Write", {"file_path": wrapper, "content": "x"}),
                    ("Write", {"file_path": "~/.claude/captain/notify.sh", "content": "x"}),
                    ("Write", {"file_path": "~/.claude/Captain/NOTIFY.SH", "content": "x"}),
                    ("Write", {"file_path": "docs/n.md", "content": "x"}),
                    ("Write", {"file_path": "../" * 12 + wrapper.lstrip("/"), "content": "x"}),
                    ("Edit", {"file_path": wrapper, "old_string": "a", "new_string": "b"}),
                    ("Bash", {"command": f"cat x > {wrapper}"}),
                    ("Bash", {"command": f"cat x >> '{wrapper}'"})):
                with self.subTest(name=name, tool_input=tool_input):
                    kind = self.audit.classify(name, tool_input, repo, self.audit.SKILL_ROOT,
                                               repo)[0]
                    self.assertNotEqual(kind, "ok")
        self.assertIn("captain:runner", read_text(SETUP_MD))

    def test_setup_commands_pass(self):
        for command in (
            "command -v codex", "command -v agy", "command -v supacode",
            "codex --help", "agy --help",
            "~/.local/bin/agy --help >/dev/null 2>&1",
            "chmod +x ~/.claude/captain/notify.sh", "chmod +x " + self.HOME + "/.claude/captain/notify.sh",
            "CAPTAIN_NOW=06:00 ~/.claude/captain/notify.sh 'captain-setup: test'",
            "CAPTAIN_NOW=12:00 " + self.HOME + "/.claude/captain/notify.sh hi",
            "CAPTAIN_NOW=00:00 ~/.claude/captain/notify.sh hi",
            "CAPTAIN_NOW=23:59 ~/.claude/captain/notify.sh hi",
            "CAPTAIN_NOW=12:00 CAPTAIN_SEND_NOW=1 ~/.claude/captain/notify.sh 'captain-setup: test'",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), "ok")

    def test_setup_write_without_valid_content_is_incomplete(self):
        for path in ("~/.claude/captain/config.json",):
            for tool_input in ({"file_path": path}, {"file_path": path, "content": 7}):
                with self.subTest(tool_input=tool_input):
                    self.assertEqual(self.audit.classify("Write", tool_input, Path("/repo"),
                                                         self.audit.SKILL_ROOT)[0], "UNVERIFIABLE")

    def test_setup_write_without_content_fails_the_audit_run(self):
        record = assistant(1, "Write", {"file_path": "~/.claude/captain/config.json"})
        result = subprocess.run([sys.executable, str(AUDIT), "--repo", "/repo", "-"],
                                input=json.dumps(record) + "\n", capture_output=True, text=True,
                                timeout=30)
        self.assertEqual(result.returncode, EXIT_INCOMPLETE, result.stdout + result.stderr)

    def test_setup_command_near_misses(self):
        for command, expected in (
            ("command -v rm", "UNVERIFIABLE"), ("command -v codex grok", "UNVERIFIABLE"),
            ("command -V codex", "UNVERIFIABLE"),
            # supacode is detected only; main never opens or closes a tab itself (R21: a runner does)
            ("command -v supacode codex", "UNVERIFIABLE"), ("supacode --help", "VIOLATION"),
            ("supacode tab new -i x", "VIOLATION"), ("supacode tab close -t x", "VIOLATION"),
            ("codex --help x", "VIOLATION"), ("codex exec --help", "VIOLATION"),
            ("git --help", "VIOLATION"),
            # grok was dropped from setup (12.10.2026): no detect or --help form passes any more
            ("command -v grok", "UNVERIFIABLE"), ("grok --help >/dev/null 2>&1", "VIOLATION"),
            ("~/.grok/bin/grok --help", "VIOLATION"), (self.HOME + "/.grok/bin/grok --help", "VIOLATION"),
            # codex, grok and agy are known-forbidden names outside these exact forms
            ("/tmp/grok --help", "VIOLATION"), ("~/.grok/bin/codex --help", "VIOLATION"),
            ("~/.local/bin/agy exec", "VIOLATION"),
            ("chmod +x ~/.claude/captain/config.json", "VIOLATION"),
            ("chmod 777 ~/.claude/captain/notify.sh", "VIOLATION"),
            ("chmod +x ~/.claude/captain/notify.sh x", "VIOLATION"),
            ("CAPTAIN_NOW=06:00 ~/.claude/captain/notify.sh a b", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=6 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=24:00 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=12:60 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("OTHER=06:00 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=06:00 PATH=/x ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=06:00 CAPTAIN_SEND_NOW=0 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_SEND_NOW=1 CAPTAIN_NOW=06:00 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=06:00 CAPTAIN_SEND_NOW=1 ~/.claude/captain/notify.sh a b", "UNVERIFIABLE"),
            ("CAPTAIN_SEND_NOW=1 ~/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=06:00 date", "UNVERIFIABLE"),
            ("CAPTAIN_NOW=06:00 /other/.claude/captain/notify.sh hi", "UNVERIFIABLE"),
        ):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), expected)


class BashClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def kind(self, command: str, background: bool = False) -> str:
        return self.audit.classify("Bash", {"command": command, "run_in_background": background},
                                   Path("/repo"), self.audit.SKILL_ROOT)[0]

    def test_kp1_r1_bypasses_are_denied(self):
        # Codex kp1 r1: F1 abbreviated or textconv diff options, F4 an output file by a
        # relative name or through git diff, F7 a shell `&`, F8 any commit but the TODO form
        for command in ("git diff --ext-dif", "git diff --ext-diff", "git diff --ext",
                        "git show --textconv HEAD", "git diff --outp=x", "git log -n 1 --ext-diff",
                        "cd /tmp/u/tasks; cat a.output", "cat a.output", "head -n 5 ./b.output",
                        "git diff --no-index /dev/null /tmp/u/tasks/a.output",
                        "git diff --no-index /dev/null a.output",
                        # kp1 r2 F2: --no-index reads whole directories outside the repository
                        "git diff --no-index a.txt b.txt", "git diff --no-index /var/empty /tmp/u/tasks",
                        "date &", "date & git status -s", "git status -s &",
                        "git commit -m x", "git commit -m x -- TODO.py", "git commit -m x -- docs/TODO.md",
                        "git commit -m '' -- TODO.md", "git commit -m x -- TODO.md TODO.md",
                        "git commit -am x -- TODO.md"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "VIOLATION")
        for command in ("git diff", "git diff --stat HEAD~1", "git diff --cached --name-only",
                        "git show --stat HEAD", "git show -s --format=%H HEAD",
                        "git diff -U3 --word-diff HEAD",
                        "git -C /repo commit -m 'docs: TODO' -- TODO.md",
                        "git commit -m x -- TODO TODO.txt", "date 2>&1", "date &>/dev/null"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "ok")
        # the fallback timer (reference/health.md) stays the one background call
        self.assertEqual(self.kind("sleep 300", background=True), "ok")
        self.assertEqual(self.kind("sleep 300 &", background=True), "VIOLATION")

    def test_allowed_commands(self):
        for command in (
            "date", "command date +%s", "git log -n 5", "git log --oneline -n 3", "git log -3",
            "git log --max-count=2 --oneline", "git status -s",
            "ps |\n grep codex", 'git log -n "\\\n1"', "date > /dev/null", "date >/dev/null 2>&1",
            "ps | grep -- codex", "git log -n 5 --format=%h --no-decorate", "git log -n 9 -n 2", "git --no-pager log -n 1",
            "cd /repo && git status -s", "command git -C /repo log -n 2 --oneline",
            "stat /tmp/x.output", "stat -L /tmp/x.output",
            "ps aux | grep codex | head -n 5", "ps aux | command grep -v grep | wc -l",
            "~/.claude/captain/notify.sh 'hi there'",
            os.path.expanduser("~/.claude/captain/notify.sh") + " hi",
            'command ~/.claude/captain/notify.sh "captain: report ready"',
            "git log -n 3\ngit status -s", "git status -s 2>&1",
            "ps | grep -e foo -e bar", "ps | grep -Ei codex", "ps | grep -c x", "date '+%F %T'",
            # C43: read-only relative dates for the timers, BSD and GNU
            "date -v+30M '+%M %H %d %m'", "date -v+1d -v-2H +%s", "date -v+30M",
            "date -d '+30 min' '+%M %H %d %m'", "date -d 'now + 2 hours' +%s",
            "date --date='-5 minutes' +%H:%M", "date -d '30 min'",
            "ps aux | grep 'a|b' # comment",
            # catching up with origin/<default>: the live guard checks which default
            "git merge --ff-only origin/main", "git merge --no-ff --no-edit origin/main",
            # DL1: read-only commands with file operands and git inspection
            "command cat src/app.py", "cat ~/.claude/captain/config.json", "head -n 20 docs/x.md",
            "tail -n 5 tmp/claude-logs/b.log", "wc -l a.md b.md", "ls -la tmp/captain",
            "find docs -name '*.md'", "stat -f %m /tmp/u/tasks/a1.output",
            "git diff --stat main", "git show HEAD:README.md", "git rev-parse HEAD",
            "git fetch", "git fetch origin", "git fetch --prune origin main",
            "git -C /repo diff main...captain/x",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "ok")

    def test_background_sleep_only(self):
        self.assertEqual(self.kind("sleep 300", background=True), "ok")
        self.assertEqual(self.kind("sleep 300"), "VIOLATION")
        self.assertEqual(self.kind("sleep 300 &"), "VIOLATION")
        # DL2: a background call other than the lone timer `sleep` is agent work
        self.assertEqual(self.kind("date & sleep 300", background=True), "VIOLATION")

    def test_forbidden_commands(self):
        for command in (
            "git commit -m x", "command git push", "cd /repo && ./build-dev.sh",
            "date && git commit -m x", "date; rm -rf build", "git log -n 1 || npm test",
            "git status -s\nmvn test", "codex exec 'x'", "kill 123",
            "git merge feature", "( git push )",
            "sleep 1 && git push",
            "(date); git commit -m x", "date # c\ngit commit -m x",
            "(date)|git push", "(date)&&git push", "ps | grep x # c\ngit push",
            "date | cat",
            "git log", "git log -p", "git log -n 1 -p", "git log --max-count=2 -p",
            "git log -n 1 --max-count=-1", "git log -n 1 -n 0",
            "date $(git push)", "date `git push`", "{ git push; }", "x=$(rm -rf src)", "git -c alias.log=!sh log -n 1", "git log -n 1 --output=x",
            "./gradlew build", "./build-dev.sh",
            "git merge --ff-only topic", "git merge --ff-only --no-edit origin/main",
            "git merge --ff-only origin/main extra", "git merge --ff-only",
            # DL2 and DL4: a build, a following tail, a find that acts, an output file, a refspec
            "npm test", "python3 -m pytest tests -q", "tail -f x.log", "tail -n 5 -F x.log",
            "tail --follow=name x.log", "find . -delete", "find . -name x -exec rm '{}' ';'",
            "cat /tmp/u/tasks/a1.output", "head -n 5 tmp/tasks/a2.output",
            "git fetch origin main:main", "git fetch origin +main", "git fetch --upload-pack=x",
            "git diff --output=x", "git show --ext-diff",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "VIOLATION")

    def test_quoted_separators_stay_inside_the_word(self):
        self.assertEqual(self.kind("date '+%H; git push'"), "ok")
        self.assertEqual(self.kind('ps aux | grep "x && git push"'), "ok")

    def test_unsupported_syntax_is_unverifiable(self):
        for command in ("date $(whoami)", "echo 'unterminated", "", "$'date'", "{ date; }",
                        "git status -s > out.txt", "date <<EOF\nrm -rf x\nEOF", "git log -n 1 < x",
                        ">src/x.py", ">src/x.py; date", "date; >src/x.py", "date \\",
                        # C28 brace/glob, C29 env prefix, C30 path executables, C31 date,
                        # C32/C41 filters and `command` options
                        "git log -n 1 {--output=src/pwn,--oneline}", "git log -n 1 {-n,100}",
                        "stat src/*", "stat src/?", "stat src/[ab]",
                        "LC_ALL=C date", "GIT_TRACE=/repo/src/pwn git status -s",
                        "./tmp/date", "./tmp/git status -s", "./notify.sh", "/repo/notify.sh hi",
                        "/other/msg-notify/notify.sh hi",
                        # the per-user wrapper only, with exactly one argument
                        "~/.claude/skills/msg-notify/notify.sh hi",
                        "~/.claude/plugins/cache/m/utils/1.0/skills/msg-notify/notify.sh hi",
                        "~/.claude/captain/notify.sh", "~/.claude/captain/notify.sh a b",
                        "/other/.claude/captain/notify.sh hi", "~/.claude/captain/x/notify.sh hi",
                        "~/.claude/captain/../captain/notify.sh hi",
                        "date 092612002026", "date -u 092612002026", "date -s 1200", "date +%s x",
                        "date -v+30M 092612002026", "date -v30X +%s", "date -d 'next friday' +%s",
                        "date -d '+30 min' -d '+1 min'", "date -d", "date -v+1d -d '+1 min' +%s",
                        "date -d @0 +%s", "date -f list +%s",
                        "ps | grep --regexp=x /repo/src/secret", "date | wc --files0-from=/repo/l",
                        "date | head -n 1 /etc/passwd", "date | grep -r x .", "ps | grep x file",
                        "ps | grep -e a b", "date | wc -l x", "date | head -c 5",
                        "command -p date"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "UNVERIFIABLE")


class PluginTextTest(unittest.TestCase):
    def test_no_personal_name_anywhere_in_the_plugin(self):
        # colleagues install this plugin; nothing in it may be addressed to one person
        found = []
        for path in sorted(PLUGIN_DIR.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.name == "plugin.json" and path.parent.name == ".claude-plugin":
                # authorship metadata may name the author, like every plugin in this repo
                manifest = json.loads(text)
                manifest.pop("author", None)
                text = json.dumps(manifest, ensure_ascii=False, indent=1)
            for number, line in enumerate(text.splitlines(), 1):
                # the Cyrillic spelling is deliberate: the name must not appear in either script
                if re.search(r"ivan|иван", line, re.I):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
        self.assertEqual(found, [], "\n".join(found))


class SetupSkillTest(unittest.TestCase):
    def test_setup_frontmatter(self):
        text = read_text(SETUP_MD)
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertTrue(match, "no frontmatter")
        fields = dict(re.findall(r"(?m)^([a-z-]+):\s*(.*?)\s*$", match.group(1)))
        self.assertEqual(fields.get("name"), "captain-setup")
        description = fields.get("description", "")
        self.assertTrue(description.startswith(
            "Use when the captain skill finds no ~/.claude/captain/config.json"), description)
        self.assertLess(len(description), 1024)
        # `captain` invokes it through the Skill tool, so model invocation must stay allowed
        self.assertNotIn("disable-model-invocation", match.group(1))

    def test_setup_body_names_its_steps(self):
        text = read_text(SETUP_MD)
        self.assertIn("eval", text)  # C3: the reason the eval is safe is stated
        self.assertIn("00–23", text)  # C5: setup rejects clock values outside the day
        for needle in ("command -v codex", "~/.local/bin/agy", "--help",
                       "~/.claude/skills/msg-notify/", "AskUserQuestion", "{message}",
                       "22:00", "06:00", "~/.claude/captain/config.json",
                       "~/.claude/captain/notify.sh", "notify.sh.tmpl", "chmod +x",
                       "/captain:captain-setup"):
            self.assertIn(needle, text)
        self.assertTrue(NOTIFY_TMPL.is_file(), "missing notify.sh.tmpl")


def render_notify(method: str, quiet_from: str = "22:00", quiet_to: str = "06:00",
                  script: str = "", command: str = "", away: str = "0") -> str:
    text = read_text(NOTIFY_TMPL)
    for key, value in (("METHOD", method), ("QUIET_FROM", quiet_from), ("QUIET_TO", quiet_to),
                       ("MSG_NOTIFY_SCRIPT", script), ("COMMAND", command),
                       ("AWAY_MINUTES", away)):
        text = text.replace(f"@@{key}@@", value)
    if "@@" in text:
        raise AssertionError("unfilled placeholder in notify.sh.tmpl")
    return text


class NotifyWrapperCase(unittest.TestCase):
    """Renders notify.sh.tmpl into a temporary home and records what the notifier received."""

    MESSAGE = 'it\'s "done" $(touch PWNED) `touch PWNED` ; touch PWNED'

    def setUp(self):
        if not shutil.which("sh"):
            self.skipTest("no sh")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.log = self.home / "calls.log"
        self.stub = self.home / "stub-notify.sh"
        self.stub.write_text(f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\" >> '{self.log}'; done\n"
                             f"printf -- '--\\n' >> '{self.log}'\n", encoding="utf-8")
        self.stub.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_wrapper(self, now: str, *args: str, extra_env: dict | None = None,
                    **fill) -> subprocess.CompletedProcess:
        wrapper = self.home / ".claude" / "captain" / "notify.sh"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(render_notify(**fill), encoding="utf-8")
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "CAPTAIN_NOW": now, **(extra_env or {})}
        return subprocess.run(["sh", str(wrapper), *args], capture_output=True, text=True,
                              timeout=10, cwd=str(self.home), env=env)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        out, current = [], []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            if line == "--":
                out.append(current)
                current = []
            else:
                current.append(line)
        return out

    def assert_not_executed(self):
        self.assertFalse((self.home / "PWNED").exists(), "the message was executed")


class NotifyTemplateTest(NotifyWrapperCase):

    def test_msg_notify_outside_quiet_hours_passes_the_message_verbatim(self):
        result = self.run_wrapper("12:00", self.MESSAGE, method="msg-notify", script=str(self.stub))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["claude", self.MESSAGE]])
        self.assert_not_executed()

    def test_quiet_window_across_midnight(self):
        for now, sent in (("21:59", True), ("22:00", False), ("23:30", False), ("00:00", False),
                          ("05:59", False), ("06:00", True), ("08:09", True)):
            with self.subTest(now=now):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(now, "hi", method="msg-notify", script=str(self.stub))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
                self.assertEqual(self.calls(), [["claude", "hi"]] if sent else [])

    def test_quiet_window_within_one_day(self):
        for now, sent in (("07:59", True), ("08:00", False), ("08:09", False), ("09:00", True)):
            with self.subTest(now=now):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(now, "hi", method="msg-notify", script=str(self.stub),
                                          quiet_from="08:00", quiet_to="09:00")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [["claude", "hi"]] if sent else [])

    def test_no_quiet_hours(self):
        result = self.run_wrapper("23:30", "hi", method="msg-notify", script=str(self.stub),
                                  quiet_from="", quiet_to="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["claude", "hi"]])

    def test_command_substitutes_the_message_as_one_argument(self):
        for command, expected in (
            (f"{self.stub} {{message}} --tail", [self.MESSAGE, "--tail"]),
            (f"{self.stub} 'fixed arg' {{message}}", ["fixed arg", self.MESSAGE]),
            (f"{self.stub} -t captain -m {{message}} {{message}}", ["-t", "captain", "-m",
                                                                     self.MESSAGE, self.MESSAGE]),
            (f"{self.stub} prefix", ["prefix", self.MESSAGE]),
        ):
            with self.subTest(command=command):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper("12:00", self.MESSAGE, method="command", command=command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [expected])
                self.assert_not_executed()

    def test_command_never_executes_the_message(self):
        # C3: {message} becomes the literal text "$1" before eval, so eval expands the message
        # once as data, wherever the user placed the placeholder.
        for command in (f"{self.stub} {{message}}", f"{self.stub} '{{message}}'",
                        f'{self.stub} "pre {{message}} post"', f"{self.stub} x{{message}}y",
                        f"{self.stub}"):
            for message in ("$(touch PWNED)", "`touch PWNED`", "; touch PWNED", "&& touch PWNED",
                            "| touch PWNED", "$(touch PWNED)'\"`touch PWNED`", "\n touch PWNED"):
                with self.subTest(command=command, message=message):
                    result = self.run_wrapper("12:00", message, method="command", command=command)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assert_not_executed()

    def test_clock_values_outside_the_day_are_rejected(self):
        # C5: hours 00-23 and minutes 00-59 only. A bad window or clock never silences.
        for now, quiet_from, quiet_to, sent in (
            ("23:59", "22:00", "06:00", False), ("00:00", "22:00", "06:00", False),
            ("24:00", "22:00", "06:00", True), ("29:59", "22:00", "06:00", True),
            ("12:60", "12:00", "13:00", True),
            ("23:30", "23:00", "24:00", True), ("23:30", "23:00", "23:60", True),
            ("01:00", "25:00", "02:00", True),
        ):
            with self.subTest(now=now, quiet_from=quiet_from, quiet_to=quiet_to):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(now, "hi", method="msg-notify", script=str(self.stub),
                                          quiet_from=quiet_from, quiet_to=quiet_to)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [["claude", "hi"]] if sent else [])

    def test_command_respects_quiet_hours(self):
        result = self.run_wrapper("23:00", "hi", method="command", command=f"{self.stub} {{message}}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_none_is_silent(self):
        result = self.run_wrapper("12:00", self.MESSAGE, method="none")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.calls(), [])
        self.assert_not_executed()

    def test_exactly_one_argument(self):
        for args in ((), ("a", "b")):
            with self.subTest(args=args):
                result = self.run_wrapper("12:00", *args, method="msg-notify", script=str(self.stub))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.calls(), [])

    def test_failing_notifier_is_reported(self):
        result = self.run_wrapper("12:00", "hi", method="msg-notify",
                                  script=str(self.home / "missing.sh"))
        self.assertNotEqual(result.returncode, 0)


class NotifyAwayTest(NotifyWrapperCase):
    """The away check: a ping goes out only when there is no input for the window after the
    event. The wrapper returns at once and decides in the background."""

    FAST = {"CAPTAIN_AWAY_SECONDS": "2", "CAPTAIN_AWAY_POLL": "1"}

    def notify_log(self) -> str:
        path = self.home / ".claude" / "captain" / "notify.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def wait_for_log(self, needle: str, timeout: float = 15.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.notify_log()
            if needle in text:
                return text
            time.sleep(0.2)
        self.fail(f"{needle!r} not in notify.log: {self.notify_log()!r}")

    def test_away_owner_gets_the_message_after_the_window(self):
        started = time.monotonic()
        result = self.run_wrapper("12:00", self.MESSAGE, method="msg-notify",
                                  script=str(self.stub), away="15",
                                  extra_env={**self.FAST, "CAPTAIN_IDLE": "99999"})
        self.assertLess(time.monotonic() - started, 1.5, "the caller waited for the window")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.calls(), [])
        self.wait_for_log("sending")
        deadline = time.monotonic() + 5
        while not self.calls() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(self.calls(), [["claude", self.MESSAGE]])
        self.assert_not_executed()

    def test_input_after_the_event_drops_the_message(self):
        # The fake clock keeps the check at elapsed=1 inside the 2s window. On the real clock,
        # `date +%s` truncates, so a late `start` plus `sleep 1` could read elapsed=2, and the
        # constant idle=0 then put the input at the window end, where it does not count.
        env = {**self.fake_clock(), **self.FAST, "CAPTAIN_IDLE": "0"}
        result = self.run_wrapper("12:00", "hi", method="command", command=f"{self.stub} {{message}}",
                                  away="15", extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_for_log("dropped")
        self.assertEqual(self.calls(), [])

    def test_send_now_skips_the_check(self):
        result = self.run_wrapper("12:00", "hi", method="msg-notify", script=str(self.stub),
                                  away="15", extra_env={"CAPTAIN_SEND_NOW": "1",
                                                        "CAPTAIN_IDLE": "0"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["claude", "hi"]])

    def test_zero_or_bad_window_sends_at_once(self):
        for away in ("0", "", "1x", "99999"):
            with self.subTest(away=away):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper("12:00", "hi", method="msg-notify", script=str(self.stub),
                                          away=away, extra_env={"CAPTAIN_IDLE": "0"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), [["claude", "hi"]])

    def test_unknown_idle_time_sends_at_once(self):
        # No ioreg on PATH and no override: the wrapper cannot tell, so it behaves as before.
        result = self.run_wrapper("12:00", "hi", method="msg-notify", script=str(self.stub),
                                  away="15", extra_env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["claude", "hi"]])

    def test_quiet_hours_win_before_the_check(self):
        result = self.run_wrapper("23:00", "hi", method="msg-notify", script=str(self.stub),
                                  away="15", extra_env={**self.FAST, "CAPTAIN_IDLE": "99999"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notify_log(), "")

    def fake_clock(self) -> dict:
        """A `date +%s` and a `sleep` on PATH that share a virtual clock, so the wrapper's
        whole-second arithmetic no longer depends on how fast the machine runs. `sleep N`
        returns at once and moves the clock N seconds; every other `date` call is the real one.
        The clock starts at `self.clock_start`."""
        bin_dir = self.home / "bin"
        bin_dir.mkdir(exist_ok=True)
        clock = self.home / "clock"
        self.clock_start = int(time.time())
        clock.write_text(str(self.clock_start), encoding="utf-8")
        real_date = shutil.which("date", path=os.environ.get("PATH", "/usr/bin:/bin")) or "/bin/date"
        date = bin_dir / "date"
        date.write_text("#!/bin/sh\n"
                        f"if [ \"$#\" -eq 1 ] && [ \"$1\" = +%s ]; then cat '{clock}'; exit; fi\n"
                        f"exec '{real_date}' \"$@\"\n", encoding="utf-8")
        sleep = bin_dir / "sleep"
        sleep.write_text("#!/bin/sh\n"
                         f"now=$(cat '{clock}'); echo $((now + $1)) > '{clock}'\n", encoding="utf-8")
        for stub in (date, sleep):
            stub.chmod(0o755)
        return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"}

    def fake_ioreg(self, input_at: int) -> dict:
        """An ioreg on PATH whose last input is at `input_at` seconds after the event, on the
        fake clock: both tests measure from the same `start` the wrapper reads."""
        env = self.fake_clock()
        bin_dir = self.home / "bin"
        (self.home / "input-ts").write_text(str(self.clock_start + input_at), encoding="utf-8")
        ioreg = bin_dir / "ioreg"
        ioreg.write_text("#!/bin/sh\n"
                         f"ts=$(cat '{self.home}/input-ts'); now=$(date +%s)\n"
                         "if [ \"$now\" -lt \"$ts\" ]; then idle=99999; else idle=$((now - ts)); fi\n"
                         'echo "  | |   \"HIDIdleTime\" = ${idle}000000000"\n', encoding="utf-8")
        ioreg.chmod(0o755)
        return env

    def test_input_right_at_the_event_drops_the_message(self):
        # Codex r1 F1: whole-second clocks must not hide input at the event itself.
        env = {**self.fake_ioreg(0), "CAPTAIN_AWAY_SECONDS": "3", "CAPTAIN_AWAY_POLL": "1"}
        result = self.run_wrapper("12:00", "hi", method="msg-notify", script=str(self.stub),
                                  away="15", extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_for_log("dropped")
        self.assertEqual(self.calls(), [])

    def test_input_after_the_window_does_not_drop_the_message(self):
        # Codex r1 F2: a poll longer than the window must not see input that came after it.
        env = {**self.fake_ioreg(3), "CAPTAIN_AWAY_SECONDS": "2", "CAPTAIN_AWAY_POLL": "5"}
        result = self.run_wrapper("12:00", "hi", method="msg-notify", script=str(self.stub),
                                  away="15", extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.wait_for_log("sending")
        deadline = time.monotonic() + 5
        while not self.calls() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(self.calls(), [["claude", "hi"]])

    def test_missing_notifier_fails_before_waiting(self):
        result = self.run_wrapper("12:00", "hi", method="msg-notify",
                                  script=str(self.home / "missing.sh"), away="15",
                                  extra_env={**self.FAST, "CAPTAIN_IDLE": "99999"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.sh", result.stderr)


GUARD = PLUGIN_DIR / "hooks" / "guard.py"
HOOKS_JSON = PLUGIN_DIR / "hooks" / "hooks.json"
CONTEXT = SKILL_DIR / "scripts" / "agent-context.py"


class GuardHookTest(unittest.TestCase):
    """hooks/guard.py: captain mode lasts for the whole session, until `/captain off`."""

    SESSION = "c969799f-4996-462a-86bd-e085e620405a"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "sessions"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, event: dict) -> subprocess.CompletedProcess:
        event = {"session_id": self.SESSION, "cwd": str(self.repo), **event}
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(self.state)}
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                              capture_output=True, text=True, timeout=30, env=env)

    def prompt(self, text: str) -> subprocess.CompletedProcess:
        return self.hook({"hook_event_name": "UserPromptSubmit", "prompt": text})

    def skill(self, name: str, args: str = "", **extra) -> subprocess.CompletedProcess:
        return self.hook({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                          "tool_input": {"skill": name, "args": args}, **extra})

    def pre(self, name: str, tool_input: dict, **extra) -> subprocess.CompletedProcess:
        return self.hook({"hook_event_name": "PreToolUse", "tool_name": name,
                          "tool_input": tool_input, **extra})

    def denied(self, result: subprocess.CompletedProcess) -> bool:
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return False
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertIn("/captain off", output["permissionDecisionReason"])
        return output["permissionDecision"] == "deny"

    EDIT = ("Edit", {"file_path": "view.html", "old_string": "a", "new_string": "b"})

    def test_hooks_json_wires_the_guard_to_three_events(self):
        hooks = json.loads(read_text(HOOKS_JSON))["hooks"]
        # the handoff hooks (R21) add SessionStart and a second PreToolUse group: test_captain_handoff.py
        self.assertEqual(set(hooks), {"UserPromptSubmit", "PostToolUse", "PreToolUse", "SessionStart"})
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Skill")
        for event in ("UserPromptSubmit", "PostToolUse", "PreToolUse"):
            command = hooks[event][0]["hooks"][0]["command"]
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard.py", command)
            self.assertTrue(command.startswith("python3 "), command)

    def test_resume_after_clear_turns_captain_mode_back_on(self):
        # /clear starts a new session without a marker; `/captain resume` is the first message (R21)
        self.assertFalse(self.denied(self.pre(*self.EDIT)))
        self.prompt("/captain resume")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))
        self.prompt("/captain:captain resume")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))

    def test_resume_in_a_successor_tab_turns_captain_mode_on(self):
        # a successor tab's first prompt names the handoff and both sessions (R21)
        self.assertFalse(self.denied(self.pre(*self.EDIT)))
        self.prompt("/captain resume handoff=/repo/tmp/captain/run/handoff-20261001-2200.md from=proj-c5 name=proj-c5-r2")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))

    def test_agent_memory_topic_passes_readme_does_not(self):
        # TS6 live: PT1 in the hook; a subagent call passes as today for any path (FR7)
        (self.repo / ".agent-memory").mkdir()
        self.prompt("/captain 30m")
        topic = {"file_path": str(self.repo / ".agent-memory" / "topic.md"), "content": "x"}
        readme = {"file_path": str(self.repo / ".agent-memory" / "README.md"), "content": "x"}
        self.assertFalse(self.denied(self.pre("Write", topic)))
        self.assertTrue(self.denied(self.pre("Write", readme)))
        self.assertFalse(self.denied(self.pre("Write", readme, agent_id="a1")))

    def test_without_captain_mode_nothing_is_denied(self):
        self.assertFalse(self.denied(self.pre(*self.EDIT)))
        self.assertFalse(self.denied(self.pre("Bash", {"command": "node server.js"})))

    def test_slash_command_turns_captain_mode_on_and_off(self):
        self.prompt("/captain:captain 30m away")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))
        self.prompt("/captain off")
        self.assertFalse(self.denied(self.pre(*self.EDIT)))

    def test_skill_call_turns_captain_mode_on_and_off(self):
        self.skill("captain:captain", "1h")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))
        self.skill("captain", "off")
        self.assertFalse(self.denied(self.pre(*self.EDIT)))

    def test_mode_outlives_the_time_box(self):
        # the run's end (R17) does not end captain mode; the next morning's edit is still denied
        self.prompt("/captain 2h")
        self.prompt("good morning, run it locally so I can test it")
        self.assertTrue(self.denied(self.pre("Bash", {"command": "PORT=8444 node server.js"})))
        self.assertTrue(self.denied(self.pre("Bash", {"command": "python3 - <<'EOF'\nx\nEOF"})))

    def test_other_prompts_and_skills_do_not_toggle(self):
        for text in ("/captain:captain-setup", "/captainx", "tell me about /captain off",
                     "captain off"):
            self.prompt(text)
        self.skill("captain:captain-setup")
        self.skill("coord", "off")
        self.assertFalse(self.denied(self.pre(*self.EDIT)))
        self.prompt("/captain")
        self.skill("captain:captain-setup", "off")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))

    def test_off_only_as_the_whole_argument(self):
        # Codex F1: free-text Skill arguments may contain the word "off"
        self.prompt("/captain 30m turn off debug logging")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))
        self.skill("captain:captain", "resume; the owner wants the debug flag off")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))
        self.skill("captain:captain", " OFF ")
        self.assertFalse(self.denied(self.pre(*self.EDIT)))

    def test_an_old_marker_survives_another_session_start(self):
        # Codex F2: only `/captain off` ends the mode, never the marker's age
        self.prompt("/captain 30m")
        marker = self.state / self.SESSION
        os.utime(marker, (0, 0))
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "/captain",
                   "session_id": "other-session"})
        self.assertTrue(marker.is_file())

    def test_malformed_pre_tool_use_passes_in_captain_mode(self):
        # Codex F3: bad input never blocks, also while the mode is on
        self.prompt("/captain 30m")
        for event in ({"hook_event_name": "PreToolUse"},
                      {"hook_event_name": "PreToolUse", "tool_name": "Edit"},
                      {"hook_event_name": "PreToolUse", "tool_name": 5, "tool_input": {}}):
            with self.subTest(event=event):
                self.assertFalse(self.denied(self.hook(event)))

    def test_subagents_are_never_denied(self):
        self.prompt("/captain 30m")
        self.assertFalse(self.denied(self.pre(*self.EDIT, agent_id="a70fdc96893de6b68",
                                              agent_type="captain:worker")))
        # a subagent cannot switch the mode either
        self.skill("captain", "off", agent_id="a1")
        self.assertTrue(self.denied(self.pre(*self.EDIT)))

    def test_coordinator_tools_pass_in_captain_mode(self):
        self.prompt("/captain 30m")
        for name, tool_input in (
            ("Agent", {"prompt": "p"}), ("SendMessage", {"to": "a1", "message": "m"}),
            ("TaskStop", {"task_id": "a1"}), ("ReadNotifications", {}), ("ListAgents", {}),
            ("Bash", {"command": "date +%s"}), ("Bash", {"command": "git log -n 3 --oneline"}),
            ("Write", {"file_path": str(self.repo / "tmp/captain/r1/run.md"), "content": "x"}),
            ("Bash", {"command": f"python3 '{SKILL_DIR}/scripts/agent-context.py' a70fdc96893de6b68"}),
        ):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertFalse(self.denied(self.pre(name, tool_input)))

    def test_sessions_are_separate(self):
        self.prompt("/captain 30m")
        other = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                           "tool_input": self.EDIT[1], "session_id": "other-session"})
        self.assertFalse(self.denied(other))

    # ---- the merge flow (R1, R10): main merges reviewed branches itself

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        *args], check=True, capture_output=True)

    def branches(self) -> None:
        """main with one commit; captain/feature and topic off it; topic changes the same line."""
        self.git("checkout", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "base")
        self.git("branch", "captain/feature")
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("checkout", "-q", "-b", "topic")
        (self.repo / "a.txt").write_text("topic\n")
        self.git("commit", "-q", "-am", "topic")
        self.git("checkout", "-q", "captain/feature")

    def merge_denied(self, result: subprocess.CompletedProcess) -> bool:
        """A deny the owner must lift: a protected HEAD or a missing grant."""
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return False
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertIn("/captain merge <branch>", output["permissionDecisionReason"])
        return output["permissionDecision"] == "deny"

    def form_denied(self, result: subprocess.CompletedProcess) -> bool:
        """A deny of the command form or the checkout state: names the canonical forms and
        never sends the coordinator to the owner."""
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return False
        output = json.loads(result.stdout)["hookSpecificOutput"]
        reason = output["permissionDecisionReason"]
        for needle in ("git -C '<abs dir>' merge --no-ff --no-edit <branch>", "commit --no-edit",
                       "merge --abort", "Fix the form and retry once"):
            self.assertIn(needle, reason)
        self.assertNotIn("/captain merge", reason)
        self.assertNotIn("ask the owner", reason)
        return output["permissionDecision"] == "deny"

    def bash(self, command: str) -> subprocess.CompletedProcess:
        return self.pre("Bash", {"command": command})

    def test_main_merges_a_reviewed_branch_into_the_feature_branch(self):
        self.branches()
        self.prompt("/captain 1h")
        for command in ("git merge --no-ff topic", f"git -C {self.repo} merge --no-ff --no-edit topic",
                        "command git merge --no-edit --no-ff topic"):
            with self.subTest(command=command):
                self.assertFalse(self.merge_denied(self.bash(command)))

    def test_merge_into_main_waits_for_the_owner_grant(self):
        self.branches()
        self.git("checkout", "-q", "main")
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff captain/feature")))
        self.assertTrue(self.merge_denied(self.bash("git push origin main")))
        # a Skill call made by the model never grants it
        self.skill("captain:captain", "merge main")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff captain/feature")))
        self.prompt("/captain merge main")
        self.assertFalse(self.merge_denied(self.bash("git merge --no-ff captain/feature")))
        self.assertFalse(self.merge_denied(self.bash("git push origin main")))
        self.assertFalse(self.merge_denied(self.bash("git switch main")))
        # only the named branch
        self.assertTrue(self.merge_denied(self.bash("git push origin captain/feature")))
        self.assertTrue(self.merge_denied(self.bash("git switch topic")))
        # `/captain off` drops the grant together with the mode
        self.prompt("/captain off")
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git push origin main")))

    def test_a_grant_from_another_run_or_older_than_12_hours_allows_nothing(self):
        self.branches()
        self.git("checkout", "-q", "main")
        self.prompt("/captain merge main")
        grant_path = self.state / f"{self.SESSION}.merge"
        grant = json.loads(grant_path.read_text())
        self.assertFalse(self.merge_denied(self.bash("git merge --no-ff captain/feature")))
        for forged in ({**grant, "run": "another-run"}, {**grant, "since": int(time.time()) - 43201},
                       {"branch": "main", "until": int(time.time()) + 3600}):  # the 0.14 format
            with self.subTest(forged=forged):
                grant_path.write_text(json.dumps(forged))
                self.assertTrue(self.merge_denied(self.bash("git merge --no-ff captain/feature")))

    def test_the_grant_lasts_for_the_run_and_ends_at_its_signals(self):
        self.branches()
        self.git("checkout", "-q", "main")
        push = "git push origin main"
        self.prompt("/captain 1h")
        self.prompt("/captain merge main")
        # base and resume keep the run and its grant; a model call never creates one
        self.prompt("/captain base release")
        self.prompt("/captain resume")
        self.skill("captain:captain", "resume")
        # free text, typed or from the model, is no new start (DK8)
        self.skill("captain:captain", "what is left?")
        self.prompt("/captain what is left?")
        self.assertFalse(self.merge_denied(self.bash(push)))
        # the model's `captain end` call before the end report (R17) ends it
        self.assertFalse(self.blocked(self.pre("Skill", {"skill": "captain", "args": "end"})))
        self.assertTrue(self.merge_denied(self.bash(push)))
        self.skill("captain:captain", "merge main")
        self.assertTrue(self.merge_denied(self.bash(push)))
        # a new typed start ends it
        self.prompt("/captain merge main")
        self.prompt("/captain 30m away")
        self.assertTrue(self.merge_denied(self.bash(push)))
        # a start the model makes ends it too
        self.prompt("/captain merge main")
        self.skill("captain:captain", "1h")
        self.assertTrue(self.merge_denied(self.bash(push)))
        # a new grant replaces the old one
        self.prompt("/captain merge main")
        self.prompt("/captain merge topic")
        self.assertTrue(self.merge_denied(self.bash(push)))
        # the denial says when a grant ends
        reason = json.loads(self.bash(push).stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        for needle in ("this run", "/captain off", "new `/captain` start", "captain end", "12 hours"):
            self.assertIn(needle, reason)

    def test_the_grant_does_not_cross_repos(self):
        self.branches()
        self.git("checkout", "-q", "main")
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
        subprocess.run(["git", "-C", str(other), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        subprocess.run(["git", "-C", str(other), "branch", "topic"], check=True)
        self.prompt("/captain merge main")  # typed in self.repo
        self.assertFalse(self.merge_denied(self.bash("git merge --no-ff captain/feature")))
        self.assertTrue(self.merge_denied(self.bash(f"git -C '{other}' merge --no-ff topic")))
        self.assertTrue(self.merge_denied(self.bash(f"git -C '{other}' push origin main")))
        # typed outside a repository, no grant is recorded
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "/captain merge main",
                   "cwd": self.tmp.name})
        self.assertFalse((self.state / f"{self.SESSION}.merge").exists())

    def test_dl1_light_work_passes_and_dl2_is_delegated(self):
        self.prompt("/captain 1h")
        (self.repo / "docs").mkdir()
        for name, tool_input in (
                ("Read", {"file_path": str(self.repo / "src" / "app.py")}),
                ("Grep", {"pattern": "x", "path": str(self.repo)}),
                ("Bash", {"command": "command cat ~/.claude/captain/config.json"}),
                ("Bash", {"command": f"wc -l {SKILL_DIR}/SKILL.md"}),
                ("Bash", {"command": f"git -C '{self.repo}' rev-parse HEAD"}),
                ("EnterWorktree", {"name": "w1"}),
                ("Skill", {"skill": "3amigos:3amigos", "args": "triage"}),
                ("Edit", {"file_path": str(self.repo / "docs" / "plan.md"), "old_string": "a",
                          "new_string": "b"}),
                ("Write", {"file_path": str(self.repo / "TODO.md"), "content": "x"})):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertFalse(self.denied(self.pre(name, tool_input)))
        for name, tool_input in (
                self.EDIT,
                ("Write", {"file_path": "plugins/p/skills/s/SKILL.md", "content": "x"}),
                ("Bash", {"command": "./gradlew build"}),
                ("Bash", {"command": "python3 -m pytest tests -q"}),
                ("Bash", {"command": "date", "timeout": 600000}),
                ("Read", {"file_path": "/private/tmp/u/tasks/a1.output"}),
                ("Bash", {"command": "tail -n 20 /private/tmp/u/tasks/a1.output"})):
            with self.subTest(name=name, tool_input=tool_input):
                result = self.pre(name, tool_input)
                self.assertTrue(self.denied(result))
                self.assertIn("This is agent work (R1, DL2): delegate it to a captain:runner",
                              result.stdout)

    def test_main_never_writes_the_state_files_through_bash(self):
        self.state = self.repo / "tmp" / "captain" / "state"
        self.prompt("/captain 1h")
        target = f"tmp/captain/state/{self.SESSION}.merge"
        for command in (f"echo '{{}}' > {target}", f"date >> {self.state}/{self.SESSION}.base",
                        f"cp /tmp/forged {target}", f"command mv x {self.state}/",
                        f"date | tee {target}", f"cat > {target} <<EOF\n{{}}\nEOF",
                        f"rm {self.state}/{self.SESSION}", f"dd if=/tmp/x of={target}"):
            with self.subTest(command=command):
                result = self.bash(command)
                self.assertTrue(self.blocked(result))
                self.assertIn("state files are written only by the guard", result.stdout)
        self.assertFalse(self.blocked(self.bash(f"cat {target}")))

    def test_main_never_pushes_a_protected_branch_or_builds(self):
        self.branches()
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git push origin main")))
        self.assertTrue(self.blocked(self.bash("git push --force origin main")))
        self.assertTrue(self.blocked(self.bash("npm run build")))

    def test_master_and_the_origin_default_are_protected(self):
        self.branches()
        self.git("branch", "master")
        self.git("branch", "trunk")
        self.git("update-ref", "refs/remotes/origin/trunk", "trunk")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.prompt("/captain 1h")
        for branch in ("master", "trunk"):
            with self.subTest(branch=branch):
                self.git("checkout", "-q", branch)
                self.assertTrue(self.merge_denied(self.bash("git merge --no-ff topic")))

    def test_a_detached_head_is_never_merged_into(self):
        self.branches()
        self.git("checkout", "-q", "--detach", "captain/feature")
        self.prompt("/captain 1h")
        self.assertTrue(self.form_denied(self.bash("git merge --no-ff topic")))

    def test_review_r1_holes_stay_closed(self):
        self.branches()
        (self.repo / "child").mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo / "child")], check=True)
        for args in (["commit", "-q", "--allow-empty", "-m", "x"], ["branch", "topic"]):
            subprocess.run(["git", "-C", str(self.repo / "child"), "-c", "user.email=t@t", "-c",
                            "user.name=t", *args], check=True)
        self.prompt("/captain 1h")
        # F1: a bare push never reaches the live checks and is denied
        self.assertTrue(self.blocked(self.bash("git push")))
        # F2: each -C resolves against the one before it, as git does: HEAD is the child's main
        # (protected), not the parent's captain/feature, which would pass (Codex r1 F7)
        self.assertTrue(self.merge_denied(self.bash(f"git -C {self.repo} -C child merge --no-ff topic")))
        self.assertFalse(self.blocked(self.bash(f"git -C {self.repo} merge --no-ff topic")))
        # F9: no working directory and no absolute -C, no merge flow
        self.assertTrue(self.blocked(self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                "tool_input": {"command": "git merge --no-ff topic"},
                                                "cwd": ""})))
        # F8: a ref named MERGE_HEAD is not a merge in progress
        self.git("update-ref", "refs/heads/MERGE_HEAD", "main")
        self.assertTrue(self.form_denied(self.bash("git commit --no-edit")))

    def test_review_r2_holes_stay_closed(self):
        self.branches()
        self.git("tag", "v1", "topic")
        self.prompt("/captain 1h")
        # F13: only a local branch is merged, never a SHA, a tag or FETCH_HEAD
        for source in ("v1", "refs/tags/v1", "FETCH_HEAD", "ORIG_HEAD"):
            with self.subTest(source=source):
                self.assertTrue(self.blocked(self.bash(f"git merge --no-ff {source}")))
        sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "topic"],
                             capture_output=True, text=True).stdout.strip()
        self.assertTrue(self.blocked(self.bash(f"git merge --no-ff {sha}")))
        # F12: a -C with ~ is denied, quoted or not
        self.assertTrue(self.form_denied(self.bash("git -C '~' merge --no-ff topic")))
        # F11: a push mapping or a mirror remote may push elsewhere
        self.prompt("/captain merge captain/feature")
        self.git("config", "remote.origin.push", "refs/heads/captain/feature:refs/heads/main")
        self.assertTrue(self.merge_denied(self.bash("git push origin captain/feature")))
        self.git("config", "--unset", "remote.origin.push")
        self.git("config", "remote.origin.mirror", "true")
        self.assertTrue(self.merge_denied(self.bash("git push origin captain/feature")))
        self.git("config", "--unset", "remote.origin.mirror")
        self.assertFalse(self.merge_denied(self.bash("git push origin captain/feature")))

    def test_review_r3_holes_stay_closed(self):
        self.branches()
        self.prompt("/captain 1h")
        # F15: a tag with the branch's name, on another commit, makes the name ambiguous
        self.git("tag", "topic", "main")
        self.assertTrue(self.form_denied(self.bash("git merge --no-ff topic")))
        self.git("tag", "-d", "topic")
        # F14: a tag named main does not hide that HEAD is main
        self.git("checkout", "-q", "main")
        self.git("tag", "main", "main")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff topic")))
        # F16: push.followTags would publish tags too
        self.prompt("/captain merge captain/feature")
        self.git("config", "push.followTags", "true")
        self.assertTrue(self.merge_denied(self.bash("git push origin captain/feature")))

    def test_without_origin_head_only_captain_branches_take_merges(self):
        # Codex r1 F4: an unknown default branch is never taken as safe
        self.branches()
        self.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.git("checkout", "-q", "-b", "trunk")
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff topic")))
        self.git("checkout", "-q", "-b", "captain/20261002-x")
        self.assertFalse(self.merge_denied(self.bash("git merge --no-ff topic")))

    def test_the_todo_only_commit_runs_on_a_run_branch_with_a_tracked_todo(self):
        # Codex kp1 r1 F8: the R18 TODO-only commit (KP1) passes the guard on a run branch
        self.branches()
        (self.repo / "TODO.md").write_text("- x\n")
        self.git("add", "TODO.md")
        self.git("commit", "-q", "-m", "todo")
        (self.repo / "TODO.md").write_text("- x\n- y\n")
        self.prompt("/captain 1h")
        commit = f"git -C '{self.repo}' commit -m 'docs: TODO' -- TODO.md"
        self.assertFalse(self.blocked(self.bash(commit)))
        # an untracked TODO file, a subdirectory -C, or a protected HEAD without the grant
        (self.repo / "TODO-new.md").write_text("x\n")
        self.assertTrue(self.form_denied(self.bash(
            f"git -C '{self.repo}' commit -m x -- TODO-new.md")))
        (self.repo / "docs").mkdir()
        self.assertTrue(self.form_denied(self.bash(
            f"git -C '{self.repo / 'docs'}' commit -m x -- TODO.md")))
        self.git("checkout", "-q", "-f", "main")
        (self.repo / "TODO.md").write_text("- x\n")
        self.git("add", "TODO.md")
        self.git("commit", "-q", "-m", "todo")
        (self.repo / "TODO.md").write_text("- x\n- y\n")
        self.assertTrue(self.merge_denied(self.bash(commit)))
        # never while a merge is in progress
        self.git("checkout", "-q", "-f", "captain/feature")
        (self.repo / "a.txt").write_text("feature\n")
        self.git("commit", "-q", "-am", "feature")
        subprocess.run(["git", "-C", str(self.repo), "merge", "--no-ff", "topic"], capture_output=True)
        self.assertTrue(self.form_denied(self.bash(commit)))

    def test_a_handoff_successor_takes_over_the_grant_of_the_run(self):
        # Codex kp1 r1 F6: MG1 carries the grant to the R21 successor of the same run
        self.branches()
        self.git("checkout", "-q", "main")
        self.prompt("/captain 1h")
        self.prompt("/captain merge main")
        before = json.loads((self.state / f"{self.SESSION}.merge").read_text())
        successor = "d0000000-0000-4000-8000-000000000001"
        self.hook({"hook_event_name": "UserPromptSubmit", "session_id": successor,
                   "prompt": "/captain resume handoff=/x/handoff.md from=a name=a-r2"})
        carried = json.loads((self.state / f"{successor}.merge").read_text())
        self.assertEqual(carried, before)  # same branch, repository, run and time
        self.assertEqual(json.loads((self.state / successor).read_text())["run"], before["run"])
        self.assertFalse((self.state / f"{self.SESSION}.merge").exists())  # held once
        push = {"hook_event_name": "PreToolUse", "session_id": successor, "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"}}
        self.assertFalse(self.blocked(self.hook(push)))
        # never a new grant: no live grant, another cwd, or a resume in a running session
        third = "d0000000-0000-4000-8000-000000000002"
        self.hook({"hook_event_name": "UserPromptSubmit", "session_id": third,
                   "prompt": "/captain resume", "cwd": self.tmp.name})
        self.assertFalse((self.state / f"{third}.merge").exists())
        fourth = "d0000000-0000-4000-8000-000000000003"
        self.hook({"hook_event_name": "UserPromptSubmit", "session_id": fourth,
                   "prompt": "/captain resume"})
        # a second handoff moves it on; the grant stays in one session only
        self.assertTrue((self.state / f"{fourth}.merge").exists())
        self.assertFalse((self.state / f"{successor}.merge").exists())
        self.assertTrue(self.blocked(self.hook(push)))

    def test_commit_on_main_needs_a_live_grant(self):
        # Codex r1 F3: the commit that concludes a merge into main checks the grant again
        self.branches()
        self.git("checkout", "-q", "main")
        (self.repo / "a.txt").write_text("main\n")
        self.git("commit", "-q", "-am", "main")
        subprocess.run(["git", "-C", str(self.repo), "merge", "--no-ff", "topic"], capture_output=True)
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git commit --no-edit")))
        self.assertFalse(self.merge_denied(self.bash("git merge --abort")))
        self.prompt("/captain merge main")
        self.assertFalse(self.merge_denied(self.bash("git commit --no-edit")))

    def test_commit_and_abort_only_while_a_merge_is_in_progress(self):
        self.branches()
        self.prompt("/captain 1h")
        self.assertTrue(self.form_denied(self.bash("git commit --no-edit")))
        self.assertTrue(self.form_denied(self.bash("git merge --abort")))
        (self.repo / "a.txt").write_text("feature\n")
        self.git("commit", "-q", "-am", "captain/feature")
        subprocess.run(["git", "-C", str(self.repo), "merge", "--no-ff", "topic"],
                       capture_output=True)  # conflicts on a.txt
        self.assertFalse(self.merge_denied(self.bash("git commit --no-edit")))
        self.assertFalse(self.merge_denied(self.bash("git merge --abort")))

    def test_a_merge_flow_command_runs_alone(self):
        self.branches()
        self.prompt("/captain 1h")
        for command in ("git status -s && git merge --no-ff topic",
                        "git merge --no-ff topic; git log -n 1", "git merge --no-ff topic | head -n 5"):
            with self.subTest(command=command):
                self.assertTrue(self.form_denied(self.bash(command)))

    def blocked(self, result: subprocess.CompletedProcess) -> bool:
        self.assertEqual(result.returncode, 0, result.stderr)
        return bool(result.stdout.strip()) \
            and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_merge_forms_outside_the_allow_list_are_denied(self):
        self.branches()
        self.prompt("/captain 1h")
        for command in ("git merge topic", "git merge --squash topic", "git merge --no-ff -X ours topic",
                        "git commit -m x", "git push --force origin captain/feature", "git push origin a:b",
                        "git switch -c new", "git branch new", "git branch -D topic",
                        "git worktree remove x", "git merge --no-ff topic..main", "git remote add x y"):
            with self.subTest(command=command):
                self.assertTrue(self.blocked(self.bash(command)))
        # with the grant, only the plain forms of the named branch pass
        self.prompt("/captain merge main")
        for command in ("git push --force origin main", "git push origin main:main",
                        "git switch -c main", "git push origin main extra"):
            with self.subTest(command=command):
                self.assertTrue(self.blocked(self.bash(command)))

    # ---- the run's base branch: `/captain base <branch>` typed by the owner

    def base(self) -> dict | None:
        path = self.state / f"{self.SESSION}.base"
        return json.loads(path.read_text()) if path.is_file() else None

    def test_the_base_comes_only_from_a_typed_prompt(self):
        self.branches()
        self.git("branch", "release")
        # a model Skill call records it only under AB1-AB6 (test_captain_auto_base.py); here HEAD is not release
        self.skill("captain:captain", "base release")
        self.skill("captain:captain", "1h base=release")
        self.assertIsNone(self.base())
        self.prompt("/captain 1h base=release")
        self.assertEqual(self.base()["branch"], "release")
        self.prompt("/captain off")
        self.assertIsNone(self.base())
        self.prompt("/captain base release")
        self.assertEqual(self.base()["branch"], "release")
        self.assertEqual(self.base()["repo"], os.path.realpath(self.repo))

    def test_main_master_and_the_origin_default_are_never_a_base(self):
        self.branches()
        self.git("branch", "master")
        for branch in ("main", "master", "-x"):
            with self.subTest(branch=branch):
                self.prompt(f"/captain base {branch}")
                self.assertIsNone(self.base())
        self.git("branch", "trunk")
        self.git("update-ref", "refs/remotes/origin/trunk", "trunk")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.prompt("/captain 1h base=trunk")
        self.assertIsNone(self.base())
        # merging into main still waits for the grant
        self.git("checkout", "-q", "main")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff --no-edit topic")))

    def test_main_merges_into_the_base_but_never_switches_or_pushes_it(self):
        self.branches()
        self.git("branch", "release")
        self.git("checkout", "-q", "release")
        self.prompt("/captain 1h")
        self.assertTrue(self.form_denied(self.bash("git merge --no-ff --no-edit topic")))
        self.prompt("/captain base release")
        self.assertFalse(self.blocked(self.bash("git merge --no-ff --no-edit topic")))
        self.assertTrue(self.merge_denied(self.bash("git push origin release")))
        self.assertTrue(self.merge_denied(self.bash("git switch release")))

    def test_the_base_counts_in_every_worktree_of_its_repo_only(self):
        self.branches()
        self.git("branch", "release")
        worktree = Path(self.tmp.name) / "wt"
        self.git("worktree", "add", "-q", str(worktree), "release")
        self.prompt("/captain 1h base=release")  # typed in the main checkout
        self.assertFalse(self.blocked(self.bash(f"git -C '{worktree}' merge --no-ff --no-edit topic")))
        # another repository with a branch of the same name is not the base
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "init", "-q", "-b", "release", str(other)], check=True)
        subprocess.run(["git", "-C", str(other), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        for args in (["branch", "topic"], ["update-ref", "refs/remotes/origin/main", "release"],
                     ["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"]):
            subprocess.run(["git", "-C", str(other), *args], check=True)
        self.assertTrue(self.form_denied(self.bash(f"git -C '{other}' merge --no-ff --no-edit topic")))

    def test_a_head_outside_captain_base_and_grant_is_denied(self):
        self.branches()
        self.git("branch", "release")
        self.git("checkout", "-q", "-b", "other")
        self.prompt("/captain 1h base=release")
        self.assertTrue(self.form_denied(self.bash("git merge --no-ff --no-edit topic")))
        self.assertTrue(self.form_denied(self.bash("git merge -m x topic")))

    def test_origin_default_merges_into_the_run_branch(self):
        self.branches()
        self.git("update-ref", "refs/remotes/origin/other", "topic")
        self.prompt("/captain 1h")
        for command in ("git merge --no-ff --no-edit origin/main", "git merge --ff-only origin/main"):
            with self.subTest(command=command):
                self.assertFalse(self.blocked(self.bash(command)))
        for command in ("git merge --no-ff origin/main", "git merge --no-ff --no-edit origin/other",
                        "git merge --ff-only origin/other", "git merge --ff-only topic",
                        "git merge --no-ff --no-edit refs/remotes/origin/main",
                        "git merge --no-ff --no-edit FETCH_HEAD"):
            with self.subTest(command=command):
                self.assertTrue(self.form_denied(self.bash(command)))
        # a local branch named origin/main shadows the remote ref in git
        self.git("branch", "origin/main", "topic")
        self.assertTrue(self.form_denied(self.bash("git merge --ff-only origin/main")))

    def test_a_granted_run_branch_keeps_both_sync_forms(self):
        # Codex r1 F3: a grant to push captain/feature must not narrow its sync to --ff-only
        self.branches()
        self.prompt("/captain merge captain/feature")
        for command in ("git merge --no-ff --no-edit origin/main", "git merge --ff-only origin/main"):
            with self.subTest(command=command):
                self.assertFalse(self.blocked(self.bash(command)))

    def test_a_protected_default_named_captain_is_no_run_branch(self):
        # Codex r2 F3: the origin default wins over the captain/* exception, also with a grant
        self.branches()
        self.git("branch", "captain/release")
        self.git("update-ref", "refs/remotes/origin/captain/release", "captain/release")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/captain/release")
        self.git("checkout", "-q", "captain/release")
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git merge --no-ff --no-edit topic")))
        self.prompt("/captain merge captain/release")
        self.assertTrue(self.form_denied(self.bash(
            "git merge --no-ff --no-edit origin/captain/release")))
        self.assertFalse(self.blocked(self.bash("git merge --ff-only origin/captain/release")))

    def test_main_never_writes_the_state_files(self):
        # Codex r1 F1: with the state directory inside tmp/captain, main still cannot forge a base
        self.branches()
        self.git("branch", "release")
        self.git("checkout", "-q", "release")
        self.state = self.repo / "tmp" / "captain" / "state"
        self.prompt("/captain 1h")
        common = os.path.realpath(self.repo / ".git")
        forged = json.dumps({"branch": "release", "repo": os.path.realpath(self.repo),
                             "common_dir": common, "since": 0})
        for name, tool_input in (
                ("Write", {"file_path": str(self.state / f"{self.SESSION}.base"), "content": forged}),
                ("Write", {"file_path": "tmp/captain/state/x.merge", "content": "{}"}),
                ("Edit", {"file_path": str(self.state / self.SESSION), "old_string": "a",
                          "new_string": "b"})):
            with self.subTest(name=name, tool_input=tool_input):
                self.assertTrue(self.blocked(self.pre(name, tool_input)))
        self.assertFalse(self.blocked(self.pre("Write", {
            "file_path": str(self.repo / "tmp/captain/r1/run.md"), "content": "x"})))
        # Codex r2 F1: another letter case names the same directory on a case-insensitive disk
        if (self.repo / "tmp" / "captain" / "STATE").exists():
            self.assertTrue(self.blocked(self.pre("Write", {
                "file_path": f"tmp/captain/STATE/{self.SESSION}.merge",
                "content": json.dumps({"branch": "main", "until": 4102444800})})))

    def test_main_catches_up_with_origin_only_fast_forward_and_with_the_grant(self):
        self.branches()
        self.git("checkout", "-q", "main")
        self.prompt("/captain 1h")
        self.assertTrue(self.merge_denied(self.bash("git merge --ff-only origin/main")))
        self.prompt("/captain merge main")
        self.assertFalse(self.blocked(self.bash("git merge --ff-only origin/main")))
        self.assertTrue(self.form_denied(self.bash("git merge --no-ff --no-edit origin/main")))

    def test_run_state_edit_and_artifact_open_pass(self):
        self.prompt("/captain 1h")
        run_md = str(self.repo / "tmp/captain/r1/run.md")
        self.assertFalse(self.denied(self.pre("Edit", {"file_path": run_md, "old_string": "a",
                                                       "new_string": "b"})))
        self.assertFalse(self.denied(self.pre("Artifact", {"action": "open",
                                                           "url": "https://claude.ai/artifact/x"})))
        self.assertTrue(self.denied(self.pre("Artifact", {"file_path": "x.html"})))
        for command in ("git branch -vv", "git worktree list --porcelain", "git remote -v",
                        "git branch --show-current"):
            with self.subTest(command=command):
                self.assertFalse(self.denied(self.bash(command)))

    def test_bad_input_never_blocks(self):
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(self.state)}
        for raw in ("", "not json", json.dumps({"hook_event_name": "PreToolUse"}),
                    json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "../x",
                                "prompt": "/captain"})):
            with self.subTest(raw=raw):
                result = subprocess.run([sys.executable, str(GUARD)], input=raw, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.state.exists() and any(self.state.iterdir()))


class AgentContextTest(unittest.TestCase):
    """scripts/agent-context.py: an agent's context size from its transcript's last usage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        self.subagents = self.projects / "-repo" / "sess" / "subagents"
        self.subagents.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, agent: str, usages: list[dict]) -> None:
        lines = [json.dumps({"type": "user", "isSidechain": True, "message": {"content": "go"}})]
        for usage in usages:
            lines.append(json.dumps({"type": "assistant", "isSidechain": True,
                                     "message": {"model": "claude-opus-5-5", "usage": usage,
                                                 "content": [{"type": "text", "text": "x"}]}}))
        (self.subagents / f"agent-{agent}.jsonl").write_text("\n".join(lines) + "\nnot json\n")

    def run_context(self, *ids: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "CAPTAIN_PROJECTS_DIR": str(self.projects)}
        return subprocess.run([sys.executable, str(CONTEXT), *ids], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_last_usage_counts_and_the_30_percent_line(self):
        self.transcript("afresh", [{"input_tokens": 5, "cache_read_input_tokens": 90_000,
                                    "cache_creation_input_tokens": 4_000, "output_tokens": 1_000}])
        self.transcript("aold", [{"input_tokens": 1, "cache_read_input_tokens": 10},
                                 {"input_tokens": 2, "cache_read_input_tokens": 300_000,
                                  "cache_creation_input_tokens": 15_000, "output_tokens": 698}])
        result = self.run_context("afresh", "aold")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "afresh 95005 tokens 9% keep")
        self.assertEqual(lines[1], "aold 315700 tokens 31% replace")

    def test_exactly_30_percent_is_replace(self):
        self.transcript("aedge", [{"input_tokens": 300_000}])
        self.assertEqual(self.run_context("aedge").stdout.strip(), "aedge 300000 tokens 30% replace")

    def test_below_30_percent_is_keep(self):
        # the owner, 20.10.2026: writers at 24-26% were replaced; 20% was raised to 30%
        self.transcript("a20", [{"input_tokens": 200_000}])
        self.transcript("abelow", [{"input_tokens": 299_999}])
        self.assertEqual(self.run_context("a20", "abelow").stdout.splitlines(),
                         ["a20 200000 tokens 20% keep", "abelow 299999 tokens 29% keep"])

    def test_no_measurement_is_unknown_not_zero(self):
        # Codex F4: a missing or empty usage must not read as an empty context
        self.transcript("anone", [])
        self.transcript("aempty", [{"input_tokens": 300_000}, {}])
        result = self.run_context("anone", "aempty")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.splitlines(),
                         ["anone unknown replace", "aempty 300000 tokens 30% replace"])

    def test_bad_records_never_overwrite_or_stop_the_measurement(self):
        # Codex round 2 F2, F3: a bool is not a count; a non-object JSON line is skipped
        self.transcript("abool", [{"input_tokens": 300_000}, {"input_tokens": False}])
        with open(self.subagents / "agent-abool.jsonl", "a") as handle:
            handle.write('["usage"]\n')
        self.transcript("amixed", [{"input_tokens": 300_000},
                                   {"input_tokens": False, "output_tokens": 0},
                                   {"input_tokens": -1}])
        self.transcript("anext", [{"input_tokens": 1_000}])
        result = self.run_context("abool", "amixed", "anext")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["abool 300000 tokens 30% replace", "amixed 300000 tokens 30% replace",
                          "anext 1000 tokens 0% keep"])

    def test_unknown_agent_and_bad_ids(self):
        result = self.run_context("amissing")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "amissing not found replace")
        self.assertEqual(self.run_context().returncode, 2)
        self.assertEqual(self.run_context("../x").returncode, 2)


class ContextScriptAllowedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def kind(self, command: str, skill_root: str = CACHE_SKILL) -> str:
        return self.audit.classify("Bash", {"command": command}, Path("/repo"), Path(skill_root))[0]

    def test_only_the_skills_own_context_script_with_agent_ids(self):
        script = f"{CACHE_SKILL}/scripts/agent-context.py"
        self.assertEqual(self.kind(f"python3 {script} a70fdc96893de6b68"), "ok")
        self.assertEqual(self.kind(f"command python3 '{script}' a1 a2 | head -n 5"), "ok")
        for command in (f"python3 {script}", f"python3 {script} -x", f"python3 {script} ../a",
                        "python3 /tmp/agent-context.py a1", f"python3 {script} a1 > out.txt",
                        f"python3 -c 'print(1)' {script}", f"{script} a1"):
            with self.subTest(command=command):
                self.assertNotEqual(self.kind(command), "ok")


class MemoryFilesTest(unittest.TestCase):
    """The harness asks main to keep its auto memory; captain mode must not block that."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def kind(self, name: str, tool_input: dict) -> str:
        return self.audit.classify(name, tool_input, Path("/repo"), self.audit.SKILL_ROOT)[0]

    def test_memory_markdown_may_be_read_written_and_edited(self):
        memory = os.path.expanduser("~/.claude/projects/-Users-x-repo/memory/lesson.md")
        self.assertEqual(self.kind("Write", {"file_path": memory, "content": "x"}), "ok")
        self.assertEqual(self.kind("Read", {"file_path": memory}), "ok")
        self.assertEqual(self.kind("Edit", {"file_path": memory, "old_string": "a",
                                            "new_string": "b"}), "ok")

    def test_nothing_else_under_projects(self):
        home = os.path.expanduser("~/.claude/projects/-Users-x-repo")
        for path in (f"{home}/session.jsonl", f"{home}/memory/../session.md",
                     f"{home}/memory/sub/x.md", f"{home}/memory/x.py", "memory/lesson.md",
                     "/repo/memory/lesson.md", f"{home}/sess/subagents/memory/x.md"):
            with self.subTest(path=path):
                self.assertNotEqual(self.kind("Write", {"file_path": path, "content": "x"}), "ok")
                self.assertNotEqual(self.kind("Edit", {"file_path": path, "old_string": "a",
                                                       "new_string": "b"}), "ok")


class CaptainModeTextTest(unittest.TestCase):
    def test_skill_names_the_off_argument_and_the_guard(self):
        text = read_text(SKILL_MD)
        self.assertIn("`/captain off`", text)
        self.assertIn("hooks/guard.py", text)
        self.assertIn("agent-context.py", text)

    def test_health_md_replaces_a_writer_at_30_percent(self):
        text = read_text(SKILL_DIR / "reference" / "health.md")
        self.assertIn("agent-context.py", text)
        self.assertIn("30%", text)
        self.assertNotIn("20% context", text)



class ConsensusTextTest(unittest.TestCase):
    """Captain 0.15.0 (AM1): the full consensus is a 3amigos panel run by main."""

    CONSENSUS_MD = SKILL_DIR / "reference" / "consensus.md"

    def test_r9_sends_full_consensus_to_a_3amigos_panel_and_drops_the_runner(self):
        text = " ".join(read_text(SKILL_MD).split())
        self.assertIn("3amigos panel", text)
        self.assertIn("one-voter mini-consensus", text)
        self.assertNotIn("Consensus runner", text)

    def test_consensus_md_maps_a_captain_question_onto_a_triage_task(self):
        text = " ".join(read_text(self.CONSENSUS_MD).split())
        for needle in ("## Tiers", "## Mini-consensus", "decisions.md",
                       "## Full consensus: a 3amigos panel", "**Mapping.**",
                       "`verdict` is the option letter", "--voters 3",
                       "`no consensus`", "never unlocks an R10 action",
                       "tmp/captain/<run>/amigos-<ID>/", "min(300 s, park − 5 min)",
                       "starts at once", "## Fallback without 3amigos",
                       '"recommendation after 3amigos: OP2"', "a subagent cannot nest them",
                       "park − 5 min is under 60 s", "absent from `tally.json`",
                       "no `ok` answer at all", "not in `data.md`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("consensus runner", text.lower())

    def test_mini_consensus_stays_one_voter_chain(self):
        text = read_text(self.CONSENSUS_MD)
        mini = text.split("## Mini-consensus", 1)[1].split("\n## ", 1)[0]
        self.assertIn("One voter at a time, never a panel.", mini)
        self.assertNotIn("3amigos", mini)

    def test_prompts_md_has_the_panel_task_and_the_runner_prompt(self):
        text = read_text(PROMPTS_MD)
        self.assertIn("## Full consensus prompt (R9) - 3amigos `task.md`", text)
        self.assertIn("## Panel runner prompt (R9) - to the `captain:runner`", text)
        self.assertIn('{"items":[{"id":"<decision ID>","verdict":"<option letter>"', text)
        self.assertIn("--fields verdict --voters 3", text)
        self.assertIn('No "ok" file at all', text)
        self.assertIn("plus one line per decision", text)
        self.assertNotIn("Consensus runner prompt", text)
        self.assertNotIn("to the `captain:deep` runner", text)

    def test_tools_md_has_no_consensus_runner(self):
        text = read_text(TOOLS_MD)
        self.assertNotIn("the consensus runner", text)
        self.assertIn("Opus voter of a 3amigos panel", text)
        self.assertIn("Fable voter of a 3amigos panel", text)
        self.assertIn("that passes `panel.py --check`; fallback without 3amigos", text)


class ReviewTriageTextTest(unittest.TestCase):
    def test_skill_points_r6_at_the_triage_reference(self):
        text = read_text(SKILL_MD)
        self.assertIn("`reference/triage.md`", text)
        self.assertIn("no FIX NOW", text)
        self.assertTrue((SKILL_DIR / "reference" / "triage.md").is_file())

    def test_triage_md_names_the_classes_and_the_trap(self):
        text = read_text(SKILL_DIR / "reference" / "triage.md")
        for needle in ("FIX NOW", "ACCEPT", "TODO", "MECHANISM:", "NEW EVIDENCE:",
                       "Accepted risks:", "normal use"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_review_prompt_keeps_the_verdict_line_and_adds_the_triage_fields(self):
        text = read_text(PROMPTS_MD)
        self.assertIn("Verdict: approve | changes", text)
        self.assertIn("Findings:", text)
        self.assertIn("F1. <blocking|non-blocking> <severity high|medium|low>", text)
        self.assertIn('Non-blocking:', text)
        self.assertIn('NEW EVIDENCE:', text)
        self.assertIn("Fix list message (R6)", text)


class RunLessonsTextTest(unittest.TestCase):
    """The lessons of the 30.09.2026 run (captain 0.6.0)."""

    REFERENCE = SKILL_DIR / "reference"

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def test_owner_commands_come_as_one_block_with_the_expected_output(self):
        self.assertIn("one block of `!` commands", read_text(SKILL_MD))
        text = read_text(self.REFERENCE / "queue.md")
        for needle in ("## Owner `!` commands (R16)", "All steps in one message",
                       "## The merge flow (R1, R10)", "`/captain merge <branch>`",
                       "states the output it expects", "No `&&` chain", "Merge Without",
                       "runs each\n   approved one as a `!` command"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_health_check_stats_one_literal_path_per_call(self):
        self.assertIn("One `stat` per Bash call", read_text(self.REFERENCE / "health.md"))
        path = "/private/tmp/s/tasks/a1.output"
        self.assertEqual(self.audit.classify("Bash", {"command": f"stat -L -f %m '{path}'"},
                                             Path("/repo"), self.audit.SKILL_ROOT)[0], "ok")
        loop = "for a in a1 a2; do stat -L -f %m /private/tmp/s/tasks/$a.output; done"
        self.assertEqual(self.audit.classify("Bash", {"command": loop},
                                             Path("/repo"), self.audit.SKILL_ROOT)[0],
                         "UNVERIFIABLE")

    def test_codex_runner_asks_for_its_final_report(self):
        text = read_text(TOOLS_MD)
        self.assertIn("Your final report (after re-invocation, not an interim one): the verdict "
                      "line VERBATIM, the count of findings (blocking / non-blocking), the path "
                      "of the -o final file, and the exit code. Not the findings themselves. "
                      "No commentary.", text)
        self.assertNotIn("the findings and the Non-blocking line VERBATIM", text)

    def test_spec_review_comes_before_code_writers(self):
        self.assertIn("A new or unreviewed spec gets its review loop first", read_text(SKILL_MD))
        text = read_text(PROMPTS_MD)
        self.assertIn("**Spec first (R5).**", text)
        self.assertIn("are authoritative where the spec file differs", text)

    def test_writer_registers_a_new_test_file_in_the_runner_script(self):
        self.assertIn("A new test file is also added to the repo's test runner script",
                      read_text(PROMPTS_MD))

    def test_review_prompt_lists_files_of_sibling_branches(self):
        text = read_text(PROMPTS_MD)
        self.assertIn("Files from sibling branches, not on", text)
        self.assertIn("report them as missing.", text)
        self.assertIn("git show '<branch>:<path>'", text)

    def test_worktree_cleanup_unlocks_and_never_forces(self):
        text = read_text(self.REFERENCE / "health.md")
        self.assertIn("## Worktree cleanup - after the merge into the default branch", text)
        self.assertIn("Not at R17", text)
        self.assertIn("worktree unlock", text)
        self.assertIn("never `-f`", text)

    def test_deadline_with_only_owner_commands_waiting_says_one_line_first(self):
        self.assertIn("only the owner's `!` commands wait", read_text(self.REFERENCE / "health.md"))

    def test_astra_review_effort_has_a_why_line(self):
        self.assertIn("confirmed `medium` for astra reviews (EF3)", read_text(TOOLS_MD))



class FewerStopsTextTest(unittest.TestCase):
    """Captain 0.15.0: dev targets (DP1), fix-all (ZD1), the health line (TH1),
    `Remaining:` (ST1) and short agent reports (KT1)."""

    REFERENCE = SKILL_DIR / "reference"

    @staticmethod
    def flat(path: Path) -> str:
        return " ".join(read_text(path).split())

    @staticmethod
    def rule(text: str, rule: str) -> str:
        return text.split(f"### {rule} ", 1)[1].split("\n### ", 1)[0]

    def test_listed_dev_targets_are_in_scope_and_the_rest_is_queued(self):
        text = read_text(SKILL_MD)
        self.assertNotIn("Not for devops, deploys or changes to external systems", text)
        self.assertIn("beyond listed dev targets", text)
        flat = " ".join(text.split())
        self.assertIn("a listed dev target after R5", flat)
        self.assertIn("another repo is written only if the owner names it for this run",
                      " ".join(self.rule(text, "R10").split()))
        queue = self.flat(self.REFERENCE / "queue.md")
        for needle in ("## Dev targets (Scope, R10)", "`dev_targets`", "`terraform apply`",
                       "the revert is checked", "against `target`",
                       "a check it cannot make → it does not run",
                       "unless the owner names that repository for this run",
                       "needs a new confirmation",
                       "its one question is the confirmation"):
            with self.subTest(needle=needle):
                self.assertIn(needle, queue)
        self.assertNotIn("one question at start; on yes", queue)
        prompts = " ".join(read_text(PROMPTS_MD).split())
        self.assertIn("or the work reaches an external system other than a dev target listed "
                      "under Scope below.", prompts)
        setup = read_text(SETUP_MD)
        self.assertIn("## 5. Dev targets (optional, `dev_targets`)", setup)
        self.assertIn('"confirmed":"YYYY-MM-DD"', setup)
        self.assertIn("`dev_targets` is kept unchanged", " ".join(setup.split()))

    def test_fix_all_makes_todo_the_last_resort(self):
        text = " ".join(read_text(SKILL_MD).split())
        self.assertIn("`mode: fix-all — <reason>`", text)
        self.assertIn("in `fix-all`, TODO is the last resort", text)
        triage = self.flat(self.REFERENCE / "triage.md")
        for needle in ("## `fix-all` runs - TODO is the last resort (ZD1)",
                       "limit plus one re-review timeout", "a new hypothesis",
                       "It does not reset the loop's re-review count",
                       "carries a one-line reason",
                       "With a box, time does not cover it → TODO with the reason \"does not fit: needs ~<N> "
                       "min, <M> min to hard end\", in both modes."):
            with self.subTest(needle=needle):
                self.assertIn(needle, triage)
        self.assertNotIn("Time does not cover it → the owner question", triage)
        queue = self.flat(self.REFERENCE / "queue.md")
        self.assertIn("- mode: fix-all | normal — <one-line reason>", queue)
        self.assertIn("`TODO: added <n>, closed <m>`", queue)
        self.assertIn("when added > 0 it is the report's first line", queue)
        self.assertIn("New hypothesis to test first:", read_text(PROMPTS_MD))

    def test_every_health_check_prints_one_status_line(self):
        text = read_text(SKILL_MD)
        r13 = " ".join(self.rule(text, "R13").split())
        self.assertIn("exactly one R11 status line", r13)
        self.assertIn("none runs → delete it", r13)
        self.assertNotIn("silent", r13.split("**Why:**")[0].lower())
        self.assertIn("plus the R13 health line", " ".join(self.rule(text, "R12").split()))
        health = self.flat(self.REFERENCE / "health.md")
        self.assertIn("## The 15-minute check - one status line (R13)", health)
        self.assertNotIn("The 15-minute check - silent", health)
        for needle in ("explicit exception to R12", "`CronDelete` the health job",
                       "It is not a report", "a one-shot check pinned to that minute",
                       "goes into this same line with its R19 ID",
                       "A blank health id stays blank"):
            with self.subTest(needle=needle):
                self.assertIn(needle, health)
        self.assertNotIn("its own R12 event line", health)
        self.assertNotIn("a separate R12 event line", health)

    def test_every_report_ends_with_what_is_left(self):
        self.assertIn("end with `Remaining:`", " ".join(read_text(SKILL_MD).split()))
        self.assertIn("7 of 12 tasks done (58%)", read_text(SKILL_MD))
        queue = self.flat(self.REFERENCE / "queue.md")
        for needle in ("## Status, park and end reports - `Remaining:` (R12)",
                       "`Nothing remains.` only when all six are empty",
                       "groups of `## Groups` with merged tasks whose test run",
                       "`Continuing with <ID>.`", "`Waiting for you on <ID>.`",
                       "`Stopping; captain mode stays on.`",
                       "The R13 health line is not a report",
                       "7. `Remaining:` and the last line",
                       "Each line ends with `[waits on you]` or `[info]`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, queue)

    def test_agents_send_one_short_report(self):
        self.assertIn("in ≤ 8 lines; review findings reach the writer by path",
                      " ".join(read_text(SKILL_MD).split()))
        prompts = " ".join(read_text(PROMPTS_MD).split())
        for needle in ("send one message, when done or blocked; never routine progress",
                       "a permission denial, a data risk, a time limit reached",
                       "at most 8 lines", "'<abs run dir>/reports/<agent name>-<task ID>.md'",
                       "main passes the writer that path, never the findings text",
                       "<Opus reviewer only:> Write the output below to",
                       "'<abs path of the review's final message>'",
                       "'<abs run dir>/reviews/<task ID>-r<k>-triage.md'",
                       "an Opus reviewer writes only its output file",
                       "Review findings <F-list> for your work",
                       "the path of the review findings, their F-IDs and round <k>/3"):
            with self.subTest(needle=needle):
                self.assertIn(needle, prompts)
        self.assertNotIn("findings verbatim", prompts)
        for path in sorted(AGENTS_DIR.glob("*.md")):
            with self.subTest(agent=path.name):
                body = " ".join(read_text(path).split())
                self.assertIn("never routine progress", body)
                self.assertIn("at most 8 lines", body)
                self.assertIn("a time limit reached", body)
                self.assertIn("its own output contract (review, triage, vote)", body)



class ImplicitNoIndexAndCarriedGrantTest(unittest.TestCase):
    """IF1: a plain `git diff` that git turns into --no-index; AU1: the grant presumed after
    an R21 `/captain resume`."""

    @classmethod
    def setUpClass(cls):
        cls.audit = load_audit()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.repo, self.outside, self.worktree = base / "repo", base / "out", base / "wt"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.py").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "src/a.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "x"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "wt",
                        str(self.worktree)], check=True)
        self.sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        (self.outside / "tasks").mkdir(parents=True)
        (self.outside / "tasks" / "a1.output").write_text("secret\n", encoding="utf-8")
        (self.repo / "logs" / "tasks").mkdir(parents=True)
        (self.repo / "logs" / "tasks" / "b2.output").write_text("secret\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def kind(self, command: str, cwd: Path | None = None) -> str:
        cwd = self.repo if cwd is None else cwd
        return self.audit.classify("Bash", {"command": command}, self.repo,
                                   self.audit.SKILL_ROOT, cwd)[0]

    def test_a_diff_operand_outside_the_work_tree_is_denied(self):
        for command in (f"git diff HEAD {self.outside}/tasks/a1.output",
                        f"git diff {self.repo}/src/a.py {self.outside}",
                        "git diff src/a.py ../out", f"git diff -- {self.outside}",
                        f"git diff HEAD -- ../out/tasks", "git diff HEAD /etc/hosts",
                        f"cd {self.outside} && git diff a b",
                        f"cd {self.outside}; git diff tasks/x tasks/y",
                        f"git -C {self.outside} diff a b", "git -C .. diff repo/src out",
                        # a failed cd leaves the shell in the repository
                        f"cd {self.repo}/nope; git diff HEAD ../out",
                        f"cd {self.repo}/src/a.py || git diff HEAD ../out"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "VIOLATION")
        # git runs outside any repository: every git diff with an operand is --no-index
        self.assertEqual(self.kind("git diff a b", cwd=self.outside), "VIOLATION")

    def test_a_directory_operand_over_agent_output_files_is_denied(self):
        for command in ("git diff HEAD logs", "git diff HEAD -- logs/tasks", "git diff HEAD .",
                        f"git -C {self.repo} diff {self.sha} -- logs"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "VIOLATION")

    def test_normal_diffs_in_the_repository_stay_allowed(self):
        for command in ("git diff", "git diff --stat", f"git diff {self.sha}..{self.sha}",
                        f"git diff {self.sha} {self.sha} -- src/a.py",
                        f"git diff {self.sha} {self.sha} -- src", "git diff main...wt",
                        f"git diff HEAD -- {self.repo}/src/a.py",
                        f"git -C '{self.worktree}' diff main -- src/a.py",
                        f"git -C '{self.worktree}' diff --stat {self.sha}..HEAD",
                        f"cd {self.worktree} && git diff HEAD -- src",
                        "git -C src diff HEAD -- a.py"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "ok")
        # a worktree outside the record's repository is checked against its own work tree
        self.assertEqual(self.kind("git diff HEAD -- src/a.py", cwd=self.worktree), "ok")

    def test_a_directory_the_audit_cannot_follow_is_unverifiable(self):
        self.assertEqual(self.kind("cd - && git diff a b"), "UNVERIFIABLE")
        self.assertEqual(self.kind(f"git -C {self.repo}/gone diff HEAD /etc/hosts"),
                         "UNVERIFIABLE")
        self.assertEqual(self.kind("cd - && git diff"), "ok")
        # zd3 r1 F3: a cd after the first command may not run (`||`), so the cwd is unknown
        for command in (f"cd {self.outside} || cd {self.repo}; git diff a b",
                        f"date && cd {self.repo} && git diff HEAD -- src"):
            with self.subTest(command=command):
                self.assertEqual(self.kind(command), "UNVERIFIABLE")

    def test_the_live_guard_denies_an_implicit_no_index_diff(self):
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(Path(self.tmp.name) / "sessions")}

        def hook(event: dict) -> subprocess.CompletedProcess:
            event = {"session_id": GuardHookTest.SESSION, "cwd": str(self.repo), **event}
            return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                  capture_output=True, text=True, timeout=30, env=env)

        def denied(command: str) -> bool:
            out = hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                        "tool_input": {"command": command}}).stdout
            return bool(out.strip()) and \
                json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"

        hook({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h"})
        self.assertTrue(denied("git diff src/a.py ../out/tasks/a1.output"))
        self.assertTrue(denied("git diff HEAD logs"))
        self.assertFalse(denied(f"git diff {self.sha} {self.sha} -- src/a.py"))

    def audit_rows(self, lines: list[str]) -> list[str]:
        path = Path(self.tmp.name) / "resumed.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return violation_lines(run_audit(str(path)).stdout)

    @staticmethod
    def record(kind: str, ts: str, message: dict) -> str:
        return json.dumps({"type": kind, "timestamp": ts, "cwd": "/repo-a", "message": message})

    @staticmethod
    def bash(command: str) -> dict:
        return {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                  "input": {"command": command}}]}

    RESUME = {"role": "user", "content": "/captain resume handoff=/h.md from=a name=a-r2"}

    def test_a_force_push_after_resume_stays_a_violation(self):
        # AU1 F2: no grant allows a force push, carried or not
        found = self.audit_rows([
            self.record("user", "2026-10-02T10:00:00.000Z", self.RESUME),
            self.record("assistant", "2026-10-02T10:01:00.000Z",
                        self.bash("git push --force origin main")),
            self.record("assistant", "2026-10-02T10:02:00.000Z",
                        self.bash("git push -f origin main")),
            self.record("assistant", "2026-10-02T10:03:00.000Z", self.bash("git switch -c main")),
            self.record("assistant", "2026-10-02T10:04:00.000Z", self.bash("git push origin main")),
        ])
        self.assertEqual([line.split()[1][11:16] for line in found], ["10:01", "10:02", "10:03"])

    def test_the_presumed_grant_ends_at_captain_end(self):
        # AU1 F3: the model's `captain end` call (and an owner's `/captain off`) ends it too
        skill = {"role": "assistant", "content": [{"type": "tool_use", "id": "s1", "name": "Skill",
                                                   "input": {"skill": "captain", "args": "end"}}]}
        found = self.audit_rows([
            self.record("user", "2026-10-02T10:00:00.000Z", self.RESUME),
            self.record("assistant", "2026-10-02T10:01:00.000Z", self.bash("git push origin main")),
            self.record("assistant", "2026-10-02T10:02:00.000Z", skill),
            self.record("assistant", "2026-10-02T10:03:00.000Z", self.bash("git push origin main")),
            self.record("user", "2026-10-02T10:04:00.000Z", self.RESUME),
            self.record("assistant", "2026-10-02T10:05:00.000Z", self.bash("git switch main")),
            self.record("user", "2026-10-02T10:06:00.000Z",
                        {"role": "user", "content": "/captain off"}),
            self.record("assistant", "2026-10-02T10:07:00.000Z", self.bash("git switch main")),
        ])
        self.assertEqual([line.split()[1][11:16] for line in found], ["10:03", "10:07"])


class GuardBaseCarryTest(unittest.TestCase):
    """GN2: `/captain resume` carries the run's recorded base with the grant, or alone."""

    A = "a0000000-0000-4000-8000-00000000000a"
    B = "b0000000-0000-4000-8000-00000000000b"
    C = "c0000000-0000-4000-8000-00000000000c"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "sessions"
        self.repo = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        for branch in ("release", "topic"):
            self.git("branch", branch)
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        *args], check=True, capture_output=True)

    def hook(self, session: str, event: dict) -> subprocess.CompletedProcess:
        event = {"session_id": session, "cwd": str(self.repo), **event}
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(self.state)}
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result

    def prompt(self, session: str, text: str) -> None:
        self.hook(session, {"hook_event_name": "UserPromptSubmit", "prompt": text})

    def record(self, session: str, kind: str = "") -> dict | None:
        path = self.state / f"{session}{kind}"
        return json.loads(path.read_text()) if path.is_file() else None

    def rewrite_base(self, session: str, **fields) -> None:
        base = {**self.record(session, ".base"), **fields}
        (self.state / f"{session}.base").write_text(json.dumps(base) + "\n")

    def merge_blocked(self, session: str) -> bool:
        result = self.hook(session, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                     "tool_input": {"command": "git merge --no-ff --no-edit topic"}})
        return bool(result.stdout.strip()) and \
            json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_the_base_moves_with_the_grant(self):
        self.prompt(self.A, "/captain 1h base=release")
        self.prompt(self.A, "/captain merge main")
        base, grant = self.record(self.A, ".base"), self.record(self.A, ".merge")
        self.assertEqual(base["run"], grant["run"])
        self.prompt(self.B, "/captain resume")
        self.assertEqual((self.record(self.B, ".base"), self.record(self.B, ".merge")), (base, grant))
        self.assertEqual(self.record(self.B)["run"], grant["run"])
        self.assertIsNone(self.record(self.A, ".base"))  # held once
        self.assertIsNone(self.record(self.A, ".merge"))
        self.git("checkout", "-q", "release")  # the successor merges into the base, no retype
        self.assertFalse(self.merge_blocked(self.B))

    def test_the_base_moves_without_a_grant(self):
        # the common run: a base and no `/captain merge`
        self.prompt(self.A, "/captain 1h base=release")
        base = self.record(self.A, ".base")
        self.prompt(self.B, "/captain resume handoff=/x/handoff.md from=a name=a-r2")
        self.assertEqual(self.record(self.B, ".base"), base)
        self.assertEqual(self.record(self.B)["run"], base["run"])
        self.assertIsNone(self.record(self.A, ".base"))
        self.assertIsNone(self.record(self.B, ".merge"))  # a carry never creates a grant
        self.git("checkout", "-q", "release")
        self.assertFalse(self.merge_blocked(self.B))
        # a second handoff moves it on
        self.prompt(self.C, "/captain resume")
        self.assertEqual(self.record(self.C, ".base"), base)
        self.assertIsNone(self.record(self.B, ".base"))

    def test_no_carry_across_another_git_common_dir(self):
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        self.prompt(self.A, "/captain 1h base=release")
        self.rewrite_base(self.A, common_dir=os.path.realpath(other / ".git"))
        self.prompt(self.B, "/captain resume")
        self.assertIsNone(self.record(self.B, ".base"))
        self.assertIsNotNone(self.record(self.A, ".base"))
        self.assertNotEqual(self.record(self.B)["run"], self.record(self.A)["run"])

    def test_no_carry_with_two_live_candidates(self):
        self.prompt(self.A, "/captain 1h base=release")
        self.prompt(self.C, "/captain 1h base=release")
        self.prompt(self.B, "/captain resume")
        self.assertIsNone(self.record(self.B, ".base"))
        self.assertIsNotNone(self.record(self.A, ".base"))
        self.assertIsNotNone(self.record(self.C, ".base"))
        # two grants are as ambiguous: neither grant nor base moves
        self.prompt(self.A, "/captain merge main")
        self.prompt(self.C, "/captain merge main")
        fresh = "d0000000-0000-4000-8000-00000000000d"  # B is no longer a new session
        self.prompt(fresh, "/captain resume")
        self.assertIsNone(self.record(fresh, ".merge"))
        self.assertIsNone(self.record(fresh, ".base"))
        self.assertIsNotNone(self.record(self.A, ".merge"))

    def test_one_grant_beside_another_live_base_carries_nothing(self):
        # ZD2 r1 F1: a grant does not outvote another session's live base
        self.prompt(self.A, "/captain 1h base=release")
        self.prompt(self.C, "/captain 1h base=release")
        self.prompt(self.A, "/captain merge main")
        self.prompt(self.B, "/captain resume")
        self.assertIsNone(self.record(self.B, ".merge"))
        self.assertIsNone(self.record(self.B, ".base"))
        for session, kind in ((self.A, ".merge"), (self.A, ".base"), (self.C, ".base")):
            self.assertIsNotNone(self.record(session, kind))
        self.assertNotIn(self.record(self.B)["run"], (self.record(self.A)["run"],
                                                      self.record(self.C)["run"]))

    def test_a_stale_base_is_not_carried(self):
        # an abandoned session keeps its marker: an old base, or one from an earlier run, stays
        self.prompt(self.A, "/captain 1h base=release")
        self.rewrite_base(self.A, since=int(time.time()) - 13 * 3600)
        self.prompt(self.B, "/captain resume")
        self.assertIsNone(self.record(self.B, ".base"))
        self.prompt(self.A, "/captain 1h")  # a new run of A; the base of the old run stays
        self.assertIsNotNone(self.record(self.A, ".base"))
        self.rewrite_base(self.A, since=int(time.time()))
        self.prompt(self.C, "/captain resume")
        self.assertIsNone(self.record(self.C, ".base"))
        self.assertIsNotNone(self.record(self.A, ".base"))
        # with a grant of the new run, the old run's base still stays (Codex r9 F1)
        self.prompt(self.A, "/captain merge main")
        fresh = "d0000000-0000-4000-8000-00000000000d"
        self.prompt(fresh, "/captain resume")
        self.assertIsNotNone(self.record(fresh, ".merge"))
        self.assertIsNone(self.record(fresh, ".base"))
        self.assertIsNotNone(self.record(self.A, ".base"))

    def test_a_base_typed_in_the_resume_prompt_wins(self):
        self.prompt(self.A, "/captain 1h base=release")
        self.prompt(self.B, "/captain resume base=topic")
        self.assertEqual(self.record(self.B, ".base")["branch"], "topic")


MEMORY_PY = ROOT / "plugins" / "project-memory" / "scripts" / "memory.py"
MEMORY_OPEN = '<only with "Project memory: on" in run.md (PK6):>'
MEMORY_CLOSE = "No such lesson → no draft, no line."
MEMORY_WORDS = (".agent-memory", "Memory candidate", "Project memory", "memory-drafts")


def fenced_block_after(text: str, heading: str) -> list[str]:
    """The lines of the first fenced block after `heading`."""
    rest = text[text.index(heading):].splitlines()
    start = next(i for i, line in enumerate(rest) if line.startswith("```"))
    end = next(i for i in range(start + 1, len(rest)) if rest[i].startswith("```"))
    return rest[start + 1:end]


def memory_paragraph(lines: list[str]) -> tuple[int, int]:
    start = next(i for i, line in enumerate(lines) if line.startswith(MEMORY_OPEN))
    end = next(i for i in range(start, len(lines)) if lines[i].endswith(MEMORY_CLOSE))
    return start, end


class MemoryFrameTextTest(unittest.TestCase):
    """Captain 0.16.0 (PK1, PK6): TS4 the frame paragraph, TS5 an `off` frame is today's."""

    @classmethod
    def setUpClass(cls):
        cls.prompts = read_text(PROMPTS_MD)
        cls.frame = fenced_block_after(cls.prompts, "## Agent frame (R3)")
        spec = importlib.util.spec_from_file_location("pm_memory", MEMORY_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.readme_text = module.README_TEXT

    def test_frame_paragraph_behind_the_placeholder(self):
        start, end = memory_paragraph(self.frame)
        paragraph = " ".join(" ".join(self.frame[start:end + 1]).split())
        for needle in ("'<abs run dir>/memory-drafts/<agent name>-<task ID>-<n>.md'",
                       "write it as a draft memory file, one per topic",
                       "`Memory candidate: <abs draft path> — <one line why>`",
                       "these lines do not count toward the 8 lines",
                       "never create, edit or delete anything under `.agent-memory/`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, paragraph)
        self.assertIn("at most 8 lines", " ".join(self.frame))
        self.assertTrue(self.frame[start - 1].startswith("7. decisions; 8. not confirmed"))
        self.assertEqual(end, len(self.frame) - 1, "the paragraph closes the frame")

    def test_candidate_prefix_matches_the_project_memory_readme(self):
        self.assertIn("`Memory candidate: <one line>`", self.readme_text)
        start, end = memory_paragraph(self.frame)
        self.assertIn("`Memory candidate: ", " ".join(self.frame[start:end + 1]))

    def test_an_off_frame_has_no_memory_text(self):
        start, end = memory_paragraph(self.frame)
        off = self.frame[:start] + self.frame[end + 1:]
        for line in off:
            for word in MEMORY_WORDS:
                self.assertNotIn(word, line, f"memory text outside the placeholder: {line!r}")
        self.assertTrue(off[-1].startswith("7. decisions; 8. not confirmed"))

    def test_bootstrap_step_8_only_reports_detect(self):
        block = fenced_block_after(self.prompts, "## Bootstrap prompt")
        hits = [line for line in block if "memory" in line.lower()]
        self.assertEqual(hits, ["8. python3 '<skill root>/scripts/memory-apply.py' detect "
                                "--checkout='<abs run checkout>'"])
        self.assertIn("   Report its one line verbatim.", block)

    def test_memory_commit_prompt_replaces_the_first_sentence(self):
        text = " ".join(self.prompts.split())
        self.assertIn("## Memory commit prompt (`captain:runner`)", self.prompts)
        self.assertIn("\"Your only commands on `.agent-memory/` are the `memory-apply.py` "
                      "command below; you write no memory text.\"", text)
        block = " ".join(fenced_block_after(self.prompts, "## Memory commit prompt"))
        self.assertIn("memory-apply.py' commit", block)
        self.assertIn("memory-apply.py' restore", block)
        for gone in ("draft-check", "apply"):  # the away queue was dropped
            self.assertNotIn(f"memory-apply.py' {gone}", self.prompts)

    def test_memory_revalidation_is_one_opus_pass(self):
        block = " ".join(" ".join(fenced_block_after(
            self.prompts, "## Memory revalidation prompt")).split())
        self.assertIn("<topic>.md | keep / fix <what> / drop <why>", block)
        self.assertIn("true against the repo", block)
        self.assertNotIn("Memory candidate", block)

    def test_queue_and_run_state_name_the_memory_step(self):
        queue = read_text(SKILL_DIR / "reference" / "queue.md")
        for needle in ("- Project memory (PK6): on (<abs memory.py path>) | off: <reason>",
                       "## Memory candidates", "## Memory step (R17",
                       "MSH3 Revalidate. One `captain:worker` (Opus), single pass",
                       "`Opus revalidation (MP1) | passed`", "not written: no time",
                       # TS3a: ZP0, a dirty .agent-memory skips the whole step
                       "ZP0 Clean check", "--ignored\n   --untracked-files=all -- .agent-memory`",
                       "No kept row after MSH1 → no write, no revalidation, no commit",
                       "all dropped → no commit, never",
                       "not written: dirty .agent-memory", "no write, no `restore`, no commit",
                       '"memory": {"candidates": <n>'):
            with self.subTest(needle=needle):
                self.assertIn(needle, queue)
        self.assertNotIn("Memory:", queue)  # MP2: no memory section in the end report
        self.assertIn("Memory on → the memory step first", read_text(SKILL_MD))
        self.assertIn("## Memory candidates", read_text(SKILL_DIR / "reference" / "handoff.md"))

if __name__ == "__main__":
    unittest.main()
