"""The release preview applies release-please's rules the way release-please does."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import next_version as nv  # noqa: E402

PRE = {"bump-minor-pre-major": True}                      # this repository's setting


def test_each_kind_of_commit():
    assert nv.classify("fix: a bug") == "patch" and nv.classify("perf(core): faster") == "patch"
    assert nv.classify("feat: a thing") == "minor" and nv.classify("feat(ui): a thing") == "minor"
    assert nv.classify("feat!: a thing") == "major" and nv.classify("fix(api)!: break") == "major"
    assert nv.classify("fix: x", "details\n\nBREAKING CHANGE: it changed") == "major"
    for subject in ("chore: x", "docs: x", "style: x", "refactor: x", "test: x", "build: x", "ci: x", "just a sentence", "Merge branch 'x'"):
        assert nv.classify(subject) is None, subject


def test_the_biggest_change_wins_and_zero_versions_never_jump_to_one():
    c = lambda *subjects: [(s, "") for s in subjects]    # noqa: E731
    assert nv.next_version("0.1.0", c("fix: a", "chore: b"), PRE)[0] == "0.1.1"
    assert nv.next_version("0.1.0", c("fix: a", "feat: b"), PRE)[0] == "0.2.0"
    assert nv.next_version("0.1.0", c("feat: a", "feat!: b"), PRE)[0] == "0.2.0"     # breaking is a minor while 0.x
    assert nv.next_version("1.4.2", c("feat!: b"), PRE)[0] == "2.0.0"
    assert nv.next_version("1.4.2", c("feat: a"), PRE)[0] == "1.5.0"
    assert nv.next_version("1.4.2", c("fix: a"), PRE)[0] == "1.4.3"
    assert nv.next_version("0.1.0", c("chore: a", "docs: b"), PRE)[0] is None        # no release at all
    assert nv.next_version("0.1.0", c("feat: a"), {**PRE, "bump-patch-for-minor-pre-major": True})[0] == "0.1.1"


def test_release_as_forces_the_version():
    commits = [("feat: big", ""), ("fix: small", "More text.\n\nRelease-As: 0.1.1\n")]
    assert nv.next_version("0.1.0", commits, PRE) == ("0.1.1", "minor", "0.1.1")
    assert nv.next_version("0.1.0", [("chore: x", "Release-As: v2.0.0")], PRE)[0] == "2.0.0"
    older_and_newer = [("a: x", "Release-As: 0.5.0"), ("fix: y", "Release-As: 0.1.1")]
    assert nv.next_version("0.1.0", older_and_newer, PRE)[2] == "0.1.1"                # the latest footer wins
