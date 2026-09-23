"""The files of a git ref, mirrored into a temporary directory.

Imported by measure.py and boundaries.py for --at and --compare; nothing runs
this file. The mirror keeps the repository layout, and a measurement runs with
the working directory moved to the mirrored one, so a printed path reads as it
does for the working tree.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import chdir, contextmanager
from dataclasses import dataclass
from pathlib import Path

from languages import MeasureError, _git, find_typescript_package, language_of


def repository_of(path: Path) -> Path:
    anchor = path if path.is_dir() else path.parent
    while not anchor.exists():
        anchor = anchor.parent
    return Path(_git(["rev-parse", "--show-toplevel"], cwd=anchor)).resolve()


def verify_ref(repo: Path, ref: str, flag: str) -> str:
    """The commit a ref names, or a broken run that names the flag it came from."""
    try:
        return _git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=repo)
    except MeasureError as exc:
        raise MeasureError(f"{flag} {ref!r} does not resolve in {repo}. Pass a ref that exists here.") from exc


def merge_base(repo: Path, base: str, ref: str) -> str:
    try:
        return _git(["merge-base", base, ref], cwd=repo)
    except MeasureError as exc:
        raise MeasureError(
            f"base {base!r} does not resolve in {repo}.\nPass --base <ref> that exists here, e.g. --base main"
        ) from exc


def relative_to_repo(repo: Path, paths: list[Path]) -> list[str]:
    try:
        return [path.resolve().relative_to(repo).as_posix() for path in paths]
    except ValueError as exc:
        raise MeasureError(f"{exc}: every path must be inside the repository {repo}") from exc


@dataclass(frozen=True)
class Revision:
    """A commit of a repository, the side of a run that --at and --compare read."""

    repo: Path
    ref: str

    def files(self, pathspecs: list[str]) -> list[str]:
        """The files that exist at ref under the given repository-relative paths."""
        if not pathspecs:
            return []
        return _git(["ls-tree", "-r", "--name-only", self.ref, "--", *pathspecs], cwd=self.repo).splitlines()

    def changed_since(self, base: str, pathspecs: list[str]) -> list[str]:
        """Files committed between the merge-base with base and ref that still exist at ref."""
        since = merge_base(self.repo, base, self.ref)
        changed = _git(["diff", "--name-only", since, self.ref, "--", *pathspecs], cwd=self.repo).splitlines()
        return self.files(changed)

    def archive(self, relatives: list[str]) -> bytes:
        command = ["git", "archive", "--format=tar", self.ref, "--", *relatives]
        proc = subprocess.run(command, cwd=self.repo, capture_output=True)
        if proc.returncode != 0:
            raise MeasureError(f"git archive {self.ref} failed in {self.repo}:\n{proc.stderr.decode().strip()}")
        return proc.stdout


# --compare with no ref: read the before side at the merge-base with --base.
MERGE_BASE = "<merge-base>"


def add_revision_flags(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument("--at", metavar="REF", help=f"measure {what} as committed at REF, not the working tree")
    parser.add_argument(
        "--compare",
        nargs="?",
        const=MERGE_BASE,
        metavar="REF",
        help=f"also measure {what} at REF (default: the merge-base with --base) and judge the difference",
    )


def before_ref(repo: Path, args: argparse.Namespace) -> tuple[str, str]:
    """The commit --compare reads the before side at, and how the report names it."""
    if args.compare != MERGE_BASE:
        return verify_ref(repo, args.compare, "--compare"), args.compare
    commit = merge_base(repo, args.base, args.at or "HEAD")
    return commit, f"merge-base {commit[:7]}"


@dataclass(frozen=True)
class Snapshot:
    """A revision's files under `root`, laid out as they are under the repository."""

    revision: Revision
    root: Path

    def mirror(self, path: Path) -> Path:
        return self.root / path.resolve().relative_to(self.revision.repo)

    @contextmanager
    def entered(self) -> Iterator[None]:
        """Run the block from the mirrored working directory, or the mirror's root from outside the repository."""
        cwd = Path.cwd().resolve()
        mirrored = self.mirror(cwd) if cwd.is_relative_to(self.revision.repo) else self.root
        mirrored.mkdir(parents=True, exist_ok=True)
        with chdir(mirrored):
            yield

    def extract(self, relatives: list[str]) -> None:
        if not relatives:
            return
        with tarfile.open(fileobj=io.BytesIO(self.revision.archive(relatives)), mode="r:") as archive:
            archive.extractall(self.root, filter="data")


def _link_typescript(taken: Snapshot, relatives: list[str]) -> None:
    """Point the mirror at the working tree's node_modules; git does not carry them."""
    repo = taken.revision.repo
    for relative in relatives:
        package = find_typescript_package(repo / relative) if language_of(Path(relative)) == "ts" else None
        if package is None:
            continue
        modules = package.parent
        link = taken.mirror(modules) if modules.is_relative_to(repo) else taken.root / "node_modules"
        if not link.exists():
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(modules, link)


@contextmanager
def snapshot(revision: Revision, relatives: list[str]) -> Iterator[Snapshot]:
    """Mirror `relatives` as they are at the revision; a path that does not exist there is left out."""
    with tempfile.TemporaryDirectory(prefix="clean-code-") as tmp:
        taken = Snapshot(revision=revision, root=Path(tmp).resolve())
        present = revision.files(relatives)
        taken.extract(present)
        _link_typescript(taken, present)
        yield taken
