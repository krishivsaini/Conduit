"""Proves repo-root confinement: path-traversal attempts are refused (§8.1).

Each test attempts a violation and asserts it fails. This is the differentiator
made real — the boundary is not asserted, it is tested against attacks.
"""

from __future__ import annotations

import pytest

from conduit.server.security.boundary import PathOutsideRootError, resolve_within_root


# --- Attacks that MUST be refused ------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "../../etc/passwd",
        "src/../../../etc/passwd",
        "..",
        "../",
        "../sample-repo/../../etc/hosts",
    ],
)
def test_dotdot_traversal_is_refused(sample_repo, evil):
    """`..` escapes out of the root are refused."""
    with pytest.raises(PathOutsideRootError):
        resolve_within_root(sample_repo, evil)


@pytest.mark.parametrize("evil", ["/etc/passwd", "/", "/Users", "/etc/../etc/passwd"])
def test_absolute_path_outside_root_is_refused(sample_repo, evil):
    """Absolute paths are refused outright."""
    with pytest.raises(PathOutsideRootError):
        resolve_within_root(sample_repo, evil)


def test_symlink_escape_is_refused(tmp_path):
    """A symlink INSIDE the root pointing OUTSIDE it must not be followed out.

    This is the case a lexical `..` check alone would miss.
    """
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret")

    # A symlink living inside the root whose target escapes the root.
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathOutsideRootError):
        resolve_within_root(root, "escape/secret.txt")


def test_sibling_prefix_is_not_mistaken_for_inside(tmp_path):
    """A sibling dir sharing a name prefix ('<root>-evil') must be refused,
    proving containment uses path ancestry, not string prefixing."""
    root = tmp_path / "repo"
    root.mkdir()
    evil = tmp_path / "repo-evil"
    evil.mkdir()
    (evil / "x.txt").write_text("nope")

    with pytest.raises(PathOutsideRootError):
        resolve_within_root(root, "../repo-evil/x.txt")


# --- Legitimate paths that MUST be allowed (no over-blocking) ---------------


def test_valid_nested_path_is_allowed(sample_repo):
    resolved = resolve_within_root(sample_repo, "src/auth.py")
    assert resolved == (sample_repo / "src" / "auth.py").resolve()
    assert sample_repo.resolve() in resolved.parents


def test_root_itself_is_allowed(sample_repo):
    assert resolve_within_root(sample_repo, ".") == sample_repo.resolve()


def test_symlink_that_stays_inside_root_is_allowed(tmp_path):
    """A symlink whose target is inside the root is fine — we block escapes,
    not symlinks per se."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "real.txt").write_text("hi")
    (root / "alias").symlink_to(root / "real.txt")

    assert resolve_within_root(root, "alias") == (root / "real.txt").resolve()
