#!/usr/bin/env python3
"""Every SKILL.md under plugins/ has frontmatter Claude Code can load.

Run:  python3 tests/test_skills.py
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted((ROOT / "plugins").glob("*/skills/*/SKILL.md"))
EXPECTED = {
    "architecture-fundamentals",
    "3amigos",
    "bg-claude-rc",
    "branch-board",
    "captain",
    "captain-setup",
    "clean-code",
    "clean-code-python",
    "clean-code-typescript",
    "clean-code-logging",
    "coord",
    "memory-defrag",
    "memory-init",
    "new-session-tab",
}


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}
    out = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


class SkillFrontmatterTest(unittest.TestCase):
    def test_every_expected_skill_exists(self):
        self.assertEqual({p.parent.name for p in SKILLS}, EXPECTED)

    def test_name_matches_directory_and_description_triggers(self):
        for path in SKILLS:
            with self.subTest(skill=path.parent.name):
                fm = frontmatter(path)
                self.assertEqual(fm.get("name"), path.parent.name)
                self.assertTrue(fm.get("description", "").startswith("Use when"), fm.get("description"))
                self.assertLess(len(fm["description"]), 1024)

    def test_clean_code_skill_names_its_companion_files(self):
        text = (ROOT / "plugins" / "clean-code" / "skills" / "clean-code" / "SKILL.md").read_text()
        for companion in ("measure.py", "boundaries.py", "architecture.md", "rationalizations.md"):
            self.assertIn(companion, text)
        self.assertIn("CLAUDE_PLUGIN_ROOT", text)


class MarketplaceManifestTest(unittest.TestCase):
    """The marketplace advertises each plugin at the version the plugin declares."""

    def setUp(self):
        self.marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())

    def plugin_manifest(self, name: str) -> dict:
        return json.loads((ROOT / "plugins" / name / ".claude-plugin" / "plugin.json").read_text())

    def local_entries(self) -> list[dict]:
        return [e for e in self.marketplace["plugins"] if isinstance(e["source"], str)]

    def third_party_entries(self) -> list[dict]:
        return [e for e in self.marketplace["plugins"] if not isinstance(e["source"], str)]

    def test_every_advertised_plugin_exists_with_a_manifest(self):
        for entry in self.local_entries():
            with self.subTest(plugin=entry["name"]):
                self.assertEqual(entry["source"], f"./plugins/{entry['name']}")
                self.assertEqual(self.plugin_manifest(entry["name"])["name"], entry["name"])

    def test_versions_agree_between_the_two_manifests(self):
        for entry in self.local_entries():
            with self.subTest(plugin=entry["name"]):
                self.assertEqual(entry["version"], self.plugin_manifest(entry["name"])["version"])

    def test_third_party_plugins_are_pinned_to_a_reviewed_commit(self):
        # Someone else's repo can change under us; an unpinned entry would ship that change unreviewed.
        for entry in self.third_party_entries():
            with self.subTest(plugin=entry["name"]):
                source = entry["source"]
                self.assertEqual(source["source"], "git-subdir")
                self.assertRegex(source.get("sha", ""), r"^[0-9a-f]{40}$")
                self.assertEqual(Path(source["path"]).name, entry["name"])
                self.assertIn("version", entry)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
