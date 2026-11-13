#!/usr/bin/env python3
"""Tests for plugins/utils/skills/share-artifact/SKILL.md.

The skill is prose that a subagent follows in the user's own Chrome, so these tests check the
text: no real address leaks into it, the access levels and the default are named, and the
guard rails that keep a share private are spelled out in the subagent prompt.

Run:  python3 tests/test_share_artifact.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "plugins" / "utils" / "skills" / "share-artifact" / "SKILL.md"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def subagent_prompt(text: str) -> str:
    """The fenced block under the "Subagent prompt" heading."""
    match = re.search(r"## Subagent prompt\n.*?\n````text\n(.*?)\n````", text, re.S)
    return match.group(1) if match else ""


class ShareArtifactSkillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL.read_text()
        cls.prompt = subagent_prompt(cls.text)

    def test_names_no_real_email_address(self):
        self.assertEqual(EMAIL.findall(self.text), [])

    def test_names_the_three_levels_and_the_default(self):
        for level in ("Editor", "Commenter", "Viewer"):
            self.assertIn(level, self.text)
        self.assertRegex(self.text, r"default[^.\n]*\*\*Commenter\*\*")

    def test_accepts_both_artifact_link_forms(self):
        self.assertIn("claude.ai/artifact/", self.text)
        self.assertIn("claude.ai/code/artifact/", self.text)

    def test_has_a_subagent_prompt_with_slots_to_fill(self):
        self.assertTrue(self.prompt, "no ````text block under ## Subagent prompt")
        for slot in ("<ARTIFACT_URLS>", "<EMAILS>", "<LEVEL>", "<MODE>"):
            self.assertIn(slot, self.prompt)

    def test_prompt_keeps_the_share_private_and_the_tabs_untouched(self):
        for phrase in (
            "anthropic-skills:chrome-browser",
            "tabs_context_mcp",
            "new tab",
            "Only people invited",
            "Anyone with the link",
            "dry-run",
            "Send invite",
            "expires",
            "tabs_close_mcp",
        ):
            self.assertIn(phrase, self.prompt)


if __name__ == "__main__":
    sys.exit(unittest.main())
