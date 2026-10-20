"""Tests for the .githooks/post-checkout main-branch guard.

Everything runs inside pytest tmp_path temp repos; git is invoked via
subprocess with cwd set to those temp dirs only.
"""

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SRC = REPO_ROOT / ".githooks" / "post-checkout"


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("hello\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    (repo / ".githooks").mkdir()
    shutil.copy(HOOK_SRC, repo / ".githooks" / "post-checkout")
    git(repo, "config", "core.hooksPath", ".githooks")
    return repo


def test_detach_in_main_repo_returns_to_main(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "checkout", "--detach")
    assert git(repo, "branch", "--show-current").stdout.strip() == "main"


def test_new_branch_in_main_repo_returns_to_main(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-b", "other")
    assert git(repo, "branch", "--show-current").stdout.strip() == "main"


def test_linked_worktree_is_left_alone(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-b", "wt", str(wt))
    git(wt, "checkout", "--detach")
    assert git(wt, "branch", "--show-current").stdout.strip() == ""


def test_file_checkout_on_main_does_nothing(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "file.txt").write_text("modified\n")
    git(repo, "checkout", "--", "file.txt")
    assert (repo / "file.txt").read_text() == "hello\n"
    assert git(repo, "branch", "--show-current").stdout.strip() == "main"
