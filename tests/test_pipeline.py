"""Tests for the JSON -> BOARD.md -> HTML half of the pipeline.

The point of the markdown stage is that it is the source of truth: a value the
collector measured must survive into the page unchanged, and a value edited in
the markdown must show up on the next render. Both directions are asserted here,
because a renderer that quietly re-derives a number from the JSON would make the
markdown decorative.

Run: python3 tests/test_pipeline.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "plugins", "branch-board",
                     "skills", "branch-board")
BOARD = os.path.join(SKILL, "board.py")
RENDER = os.path.join(SKILL, "render.py")


def sample_json(**overrides):
    branch = {
        "name": "feature/thing", "role": "work", "in_window_by": "commit",
        "plans": [], "author": "Jane Doe", "last_date": "2026-08-27",
        "tip": "abc1234", "local_only": False, "merge_base": "def567890",
        "ahead": 3, "behind": 7, "merged": False, "landed_by": None,
        "files": 12, "insertions": 340, "deletions": 20,
        "top_dirs": [{"path": "backend/app", "files": 9}],
        "commits": [{"sha": "abc1234", "author": "Jane Doe",
                     "date": "2026-08-27", "subject": "feat: the thing"}],
        "pr": {"number": 42, "state": "OPEN", "title": "The thing",
               "isDraft": False, "url": "https://example.test/42"},
    }
    branch.update(overrides.pop("branch", {}))
    data = {
        "meta": {"repo": "/tmp/x", "repo_name": "demo-repo", "base": "origin/main",
                 "base_sha": "1234abc", "days": 7, "generated": "27.08.2026, 12:00",
                 "gh": True, "fetched": True, "pruned": True, "warnings": [],
                 "commands": ["git for-each-ref ..."]},
        "branches": [branch],
    }
    data["meta"].update(overrides.pop("meta", {}))
    return data


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bb-pipe-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def to_md(self, data):
        jp = os.path.join(self.tmp, "board.json")
        mp = os.path.join(self.tmp, "BOARD.md")
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        subprocess.run([sys.executable, BOARD, jp, "--out", mp], check=True,
                       capture_output=True)
        with open(mp, encoding="utf-8") as f:
            return mp, f.read()

    def to_html(self, md_text):
        mp = os.path.join(self.tmp, "BOARD.md")
        hp = os.path.join(self.tmp, "board.html")
        with open(mp, "w", encoding="utf-8") as f:
            f.write(md_text)
        subprocess.run([sys.executable, RENDER, mp, "--out", hp], check=True,
                       capture_output=True)
        with open(hp, encoding="utf-8") as f:
            return f.read()


class TestBoardSkeleton(Pipeline):
    def test_measured_values_are_filled_in(self):
        _, md = self.to_md(sample_json())
        self.assertIn("- state: in review", md)
        self.assertIn("- position: 3 напред / 7 назад от base-а", md)
        self.assertIn("+340 −20", md)
        self.assertIn("#42 OPEN", md)

    def test_judgement_is_left_as_a_todo(self):
        _, md = self.to_md(sample_json())
        # exactly one per branch plus one for the summary
        self.assertEqual(md.count("TODO:"), 2)

    def test_state_names_the_evidence_not_just_the_state(self):
        _, md = self.to_md(sample_json(branch={
            "merged": True, "landed_by": "pr",
            "pr": {"number": 9, "state": "MERGED", "title": "t",
                   "isDraft": False, "url": "https://example.test/9"}}))
        self.assertIn("- state: landed", md)
        self.assertIn("PR #9 е merged (squash", md)

    def test_a_branch_with_only_incidental_docs_is_said_to_have_no_plan(self):
        _, md = self.to_md(sample_json(branch={"plans": [{
            "path": "docs/setup.md", "kind": "incidental", "title": "Setup",
            "goal": "", "checkboxes": {"done": 0, "todo": 0}, "tasks": [],
            "tasks_done": 0, "flags": [], "lines": 5}]}))
        self.assertIn("няма собствен план", md)
        self.assertIn("docs/setup.md", md)

    def test_pointers_are_grouped_separately(self):
        data = sample_json()
        data["branches"].append(dict(data["branches"][0],
                                     name="prod", role="pointer", ahead=0,
                                     commits=[], top_dirs=[], pr=None,
                                     merged=True, landed_by="ancestor"))
        _, md = self.to_md(data)
        self.assertIn("# Pointers", md)
        self.assertLess(md.index("## feature/thing"), md.index("# Pointers"))
        self.assertGreater(md.index("## prod"), md.index("# Pointers"))


class TestRender(Pipeline):
    def test_the_markdown_is_the_source_not_the_json(self):
        _, md = self.to_md(sample_json())
        edited = md.replace("- author: Jane Doe", "- author: Някой Друг")
        page = self.to_html(edited)
        self.assertIn("Някой Друг", page)
        self.assertNotIn("Jane Doe", page)

    def test_prose_written_into_the_markdown_reaches_the_page(self):
        _, md = self.to_md(sample_json())
        edited = md.replace(
            "TODO: една честна линия — какво е това и докъде е стигнало.",
            "Това е човешката линия.", 1)
        page = self.to_html(edited)
        self.assertIn("Това е човешката линия.", page)

    def test_an_unanswered_todo_renders_visibly_rather_than_vanishing(self):
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        self.assertIn("prose--todo", page)

    def test_the_state_becomes_a_chip_with_a_semantic_class(self):
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        self.assertIn('class="chip chip--review"', page)

    def test_a_prune_warning_becomes_a_banner(self):
        _, md = self.to_md(sample_json(meta={
            "pruned": False, "warnings": ["no prune this run (--no-fetch)"]}))
        page = self.to_html(md)
        self.assertIn('class="banner"', page)
        self.assertIn("no prune this run", page)

    def test_no_warning_means_no_banner(self):
        _, md = self.to_md(sample_json())
        self.assertNotIn('class="banner"', self.to_html(md))

    def test_html_in_the_markdown_is_escaped(self):
        _, md = self.to_md(sample_json())
        edited = md.replace("- author: Jane Doe",
                            "- author: <script>alert(1)</script>")
        page = self.to_html(edited)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_page_carries_no_root_document_tags(self):
        # the Artifact tool supplies <!doctype>/<html>/<head>/<body> itself
        _, md = self.to_md(sample_json())
        page = self.to_html(md).lower()
        for tag in ("<!doctype", "<html", "<head>", "<body"):
            self.assertNotIn(tag, page)

    def test_the_title_names_the_repo(self):
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        self.assertEqual(re.search(r"<title>(.*?)</title>", page).group(1),
                         "demo-repo Branches")

    def test_every_tag_is_balanced(self):
        from html.parser import HTMLParser

        class P(HTMLParser):
            void = {"link", "br", "img", "meta", "hr", "input"}

            def __init__(self):
                super().__init__()
                self.stack, self.bad = [], []

            def handle_starttag(self, tag, attrs):
                if tag not in self.void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack[-1] != tag:
                    self.bad.append(tag)
                else:
                    self.stack.pop()

        _, md = self.to_md(sample_json())
        p = P()
        p.feed(self.to_html(md))
        self.assertEqual((p.stack, p.bad), ([], []))

    def test_list_elements_only_contain_legal_children(self):
        # a <ul> whose children are <div> is invalid; the browser reparents it
        # and the layout silently stops matching the stylesheet
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        for tag, legal in (("ul", {"li"}), ("ol", {"li"}),
                           ("dl", {"dt", "dd", "div"})):
            for body in re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", page, re.S):
                kids = set(re.findall(r"<(\w+)", body)) - {"span", "a", "code",
                                                           "strong", "dt", "dd"}
                kids = {k for k in kids if k not in legal}
                self.assertEqual(kids, set(), f"<{tag}> has illegal child {kids}")

    def test_every_colour_token_is_defined_in_the_bare_root(self):
        # a token defined only under a media query renders one theme's text on
        # the other theme's ground for viewers on the default "system" setting
        _, md = self.to_md(sample_json())
        css = self.to_html(md)
        css = css[css.index("<style>"):css.index("</style>")]
        root = css[css.index(":root{"):css.index("@media")]
        defined = set(re.findall(r"--([\w-]+):", root))
        used = set(re.findall(r"var\(--([\w-]+)\)", css))
        self.assertEqual(sorted(used - defined), [])

    def test_only_google_fonts_are_fetched_from_outside(self):
        # The Artifact CSP blocks sub-resource REQUESTS to other hosts. An <a>
        # to GitHub is a navigation the viewer chooses, not a fetch, so only
        # <link> and src= are the assertion here.
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        hosts = set(re.findall(r'<link[^>]+href="https?://([^/"]+)', page))
        hosts |= set(re.findall(r'\bsrc="https?://([^/"]+)', page))
        self.assertTrue(hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"},
                        f"unexpected asset host: {hosts}")

    def test_outbound_links_open_safely(self):
        _, md = self.to_md(sample_json())
        page = self.to_html(md)
        for tag in re.findall(r"<a [^>]+>", page):
            self.assertIn('rel="noopener"', tag)



class TestHandWrittenMarkdown(Pipeline):
    """Regression: BOARD.md is the source of truth and a human writes prose
    into it. A bullet written under a branch was not attached to that branch:
    parse() fell through to the section handler and moved it into the section
    intro, above every record. A `- word: text` note became a monospaced field
    row instead — a judgement rendered in the typeface reserved for measurements.
    """

    def board_with(self, extra):
        _, md = self.to_md(sample_json())
        return md.replace(
            "TODO: една честна линия — какво е това и докъде е стигнало.",
            "Човешката линия.\n\n" + extra, 1)

    def test_a_bullet_under_a_branch_stays_with_that_branch(self):
        page = self.to_html(self.board_with("- чакаме ревю от инфра"))
        import re
        intro = re.findall(r'<p class="section__intro[^"]*">(.*?)</p>', page)
        self.assertNotIn("чакаме ревю от инфра", " ".join(intro),
                         "the note was moved to the top of the section")
        self.assertIn("чакаме ревю от инфра", page)

    def test_a_colon_in_a_hand_written_note_does_not_make_it_a_field(self):
        page = self.to_html(self.board_with("- бележка: чакаме ревю от инфра"))
        import re
        keys = re.findall(r'<div class="k">(.*?)</div>', page)
        self.assertNotIn("бележка", keys,
                         "a human note is rendered as a measured field")


class TestContrast(Pipeline):
    """Regression: the page had never been looked at rendered. In the LIGHT
    theme --muted on --paper measures 3.80:1 — below WCAG AA's 4.5:1 for normal
    text. It carries every field label, every section heading, the footer
    generation stamp, and the unanswered TODO that SKILL.md says must be
    "visible rather than silent". The dark theme is fine at 5.77:1.
    """

    AA = 4.5

    @staticmethod
    def _lum(hexcolor):
        h = hexcolor.lstrip("#")
        parts = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        parts = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                 for c in parts]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    @classmethod
    def _ratio(cls, fg, bg):
        a, b = cls._lum(fg), cls._lum(bg)
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)

    def tokens(self, block):
        _, md = self.to_md(sample_json())
        css = self.to_html(md)
        css = css[css.index("<style>"):css.index("</style>")]
        start = css.index(block)
        body = css[start:css.index("}", start)]
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", body))

    def test_muted_text_meets_aa_in_the_light_theme(self):
        t = self.tokens(":root{")
        r = self._ratio(t["muted"], t["paper"])
        self.assertGreaterEqual(round(r, 2), self.AA,
                                f"--muted on --paper is {r:.2f}:1; it carries the "
                                f"field labels, the footer and the unanswered TODO")

    def test_muted_text_meets_aa_in_the_dark_theme(self):
        # positive control: this one already passes, so a failure above is real
        t = self.tokens(':root[data-theme="dark"]{')
        r = self._ratio(t["muted"], t["paper"])
        self.assertGreaterEqual(round(r, 2), self.AA, f"{r:.2f}:1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
