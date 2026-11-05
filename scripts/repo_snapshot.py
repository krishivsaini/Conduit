"""Extract one commit of this repository into a directory, for recording and replay.

Conduit changes with every commit, so a recorded run against it is only
meaningful against the exact tree it saw. ``git archive`` gives that tree and
nothing else: tracked files only, so a local .env, untracked notes or ignored
build output can never end up in a recording.

Used by scripts/record_transcripts.py (record against a commit) and
tests/test_replay.py (replay against the same commit).
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve(commit: str = "HEAD", repo: Path = PROJECT_ROOT) -> str:
    """The full sha for ``commit``; raises if it isn't in this clone's history."""
    out = subprocess.run(
        ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
        cwd=repo, capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise LookupError(f"commit {commit!r} is not in this clone (a shallow clone? fetch more history)")
    return out.stdout.strip()


def extract(commit: str, dest: Path, repo: Path = PROJECT_ROOT) -> Path:
    """Write the tree at ``commit`` into ``dest`` (created) and return ``dest``."""
    sha = resolve(commit, repo)
    archive = subprocess.run(["git", "archive", "--format=tar", sha], cwd=repo, capture_output=True, check=True)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        try:
            tar.extractall(dest, filter="data")  # refuses absolute paths, links out of dest
        except TypeError:  # Python < 3.12 has no filter argument
            tar.extractall(dest)
    return dest


def is_pushed(sha: str, repo: Path = PROJECT_ROOT) -> bool:
    """True if a remote-tracking branch contains ``sha`` (so a link to it works)."""
    out = subprocess.run(["git", "branch", "-r", "--contains", sha], cwd=repo, capture_output=True, text=True)
    return out.returncode == 0 and bool(out.stdout.strip())
