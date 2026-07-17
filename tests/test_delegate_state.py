import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "scripts" / "delegate-snapshot"
DELTA = ROOT / "scripts" / "delegate-delta"


def run(*args, cwd, check=True):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


class DelegateStateTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        repo.mkdir()
        run("git", "init", "-q", cwd=repo)
        run("git", "config", "user.email", "test@example.com", cwd=repo)
        run("git", "config", "user.name", "Test", cwd=repo)
        (repo / "tracked.txt").write_text("base\n")
        (repo / "delete.txt").write_text("delete me\n")
        (repo / "mode.sh").write_text("#!/bin/sh\n")
        (repo / "untouched.txt").write_text("base untouched\n")
        (repo / "outside.txt").write_text("base outside\n")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "fixture", cwd=repo)
        return repo

    def test_snapshot_captures_complete_preexisting_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snapshot"
            (repo / "tracked.txt").write_text("user change\n")
            (repo / "user.txt").write_text("untracked user file\n")

            run(SNAPSHOT, snap, "pre", cwd=repo)
            manifest = json.loads((snap / "pre.json").read_text())

            self.assertEqual(list(manifest["files"]), sorted(manifest["files"]))
            self.assertEqual(manifest["files"]["tracked.txt"]["type"], "file")
            self.assertEqual(manifest["files"]["tracked.txt"]["mode"], "0644")
            self.assertEqual(
                manifest["preexisting_paths"], ["tracked.txt", "user.txt"]
            )
            digest = manifest["files"]["tracked.txt"]["sha256"]
            self.assertEqual((snap / "objects" / digest).read_text(), "user change\n")

    def test_delta_classifies_delegate_changes_and_writes_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snapshot"
            (repo / "tracked.txt").write_text("user change\n")
            (repo / "untouched.txt").write_text("user untouched change\n")
            run(SNAPSHOT, snap, "pre", cwd=repo)

            (repo / "tracked.txt").write_text("delegate changed user file\n")
            (repo / "created.txt").write_text("delegate-created contents\n")
            (repo / "delete.txt").unlink()
            (repo / "outside.txt").write_text("outside allowed scope\n")
            os.chmod(repo / "mode.sh", 0o755)
            run(SNAPSHOT, snap, "post", cwd=repo)

            result = run(
                DELTA,
                "inspect",
                snap,
                "--allowed",
                "tracked.txt",
                "--allowed",
                "created.txt",
                "--allowed",
                "delete.txt",
                "--allowed",
                "mode.sh",
                cwd=repo,
            )
            delta = json.loads(result.stdout)
            self.assertEqual(delta["created"], ["created.txt"])
            self.assertEqual(delta["deleted"], ["delete.txt"])
            self.assertEqual(delta["mode_changed"], ["mode.sh"])
            self.assertEqual(delta["modified"], ["outside.txt", "tracked.txt"])
            self.assertNotIn("untouched.txt", delta["delegate_paths"])
            self.assertEqual(delta["delegate_touched_preexisting"], ["tracked.txt"])
            self.assertEqual(delta["scope_violations"], ["outside.txt"])

            patch = (snap / "delta.patch").read_text()
            self.assertNotIn(str(snap), patch)
            self.assertIn("diff --git pre/", patch)
            self.assertIn("delegate-created contents", patch)
            self.assertIn("deleted file mode", patch)
            self.assertIn("old mode 100644", patch)
            self.assertIn("new mode 100755", patch)

    def test_restore_preserves_preexisting_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snapshot"
            (repo / "tracked.txt").write_text("user change\n")
            (repo / "untouched.txt").write_text("user untouched change\n")
            run(SNAPSHOT, snap, "pre", cwd=repo)
            (repo / "tracked.txt").write_text("delegate change\n")
            (repo / "created.txt").write_text("created\n")
            (repo / "delete.txt").unlink()
            os.chmod(repo / "mode.sh", 0o755)
            run(SNAPSHOT, snap, "post", cwd=repo)
            run(
                DELTA,
                "inspect",
                snap,
                "--allowed",
                "tracked.txt",
                "--allowed",
                "created.txt",
                "--allowed",
                "delete.txt",
                "--allowed",
                "mode.sh",
                cwd=repo,
            )

            run(DELTA, "restore", snap, cwd=repo)
            self.assertEqual((repo / "tracked.txt").read_text(), "user change\n")
            self.assertEqual(
                (repo / "untouched.txt").read_text(), "user untouched change\n"
            )
            self.assertFalse((repo / "created.txt").exists())
            self.assertEqual((repo / "delete.txt").read_text(), "delete me\n")
            self.assertEqual(os.stat(repo / "mode.sh").st_mode & 0o777, 0o644)

    def test_restore_refuses_any_concurrent_nonignored_edit_without_partial_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snapshot"
            run(SNAPSHOT, snap, "pre", cwd=repo)
            (repo / "tracked.txt").write_text("delegate change\n")
            (repo / "created.txt").write_text("created\n")
            run(SNAPSHOT, snap, "post", cwd=repo)
            run(
                DELTA,
                "inspect",
                snap,
                "--allowed",
                "tracked.txt",
                "--allowed",
                "created.txt",
                cwd=repo,
            )
            (repo / "untouched.txt").write_text("concurrent edit\n")

            result = run(DELTA, "restore", snap, cwd=repo, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("changed after post snapshot", result.stderr)
            self.assertEqual((repo / "tracked.txt").read_text(), "delegate change\n")
            self.assertEqual((repo / "created.txt").read_text(), "created\n")

    def test_restore_rejects_tampered_delta_before_mutating_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snapshot"
            run(SNAPSHOT, snap, "pre", cwd=repo)
            (repo / "tracked.txt").write_text("delegate change\n")
            (repo / "created.txt").write_text("created\n")
            run(SNAPSHOT, snap, "post", cwd=repo)
            run(
                DELTA,
                "inspect",
                snap,
                "--allowed",
                "tracked.txt",
                "--allowed",
                "created.txt",
                cwd=repo,
            )
            delta_path = snap / "delta.json"
            delta = json.loads(delta_path.read_text())
            delta["delegate_paths"].remove("created.txt")
            delta_path.write_text(json.dumps(delta))

            result = run(DELTA, "restore", snap, cwd=repo, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match snapshots", result.stderr)
            self.assertEqual((repo / "tracked.txt").read_text(), "delegate change\n")


if __name__ == "__main__":
    unittest.main()
