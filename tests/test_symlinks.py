import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "model-router"
CURSOR_ADAPTER = ROOT / "skills" / "model-router-cursor"
CODEX_ADAPTER = ROOT / "skills" / "model-router-codex"
CLAUDE_ADAPTER = ROOT / "skills" / "model-router-claude"


class SymlinkTests(unittest.TestCase):
    def test_adapters_and_shared_exist(self):
        self.assertTrue((SHARED / "SKILL.md").is_file())
        self.assertTrue((CURSOR_ADAPTER / "SKILL.md").is_file())
        self.assertTrue((CODEX_ADAPTER / "SKILL.md").is_file())
        self.assertTrue((CLAUDE_ADAPTER / "SKILL.md").is_file())
        self.assertTrue((CURSOR_ADAPTER / "shared-rules.md").is_symlink())
        self.assertTrue((CLAUDE_ADAPTER / "shared-rules.md").is_symlink())
        self.assertIn(
            "CALLER_HARNESS is always `cursor`",
            (CURSOR_ADAPTER / "SKILL.md").read_text(),
        )
        self.assertIn(
            "CALLER_HARNESS is always `codex`",
            (CODEX_ADAPTER / "SKILL.md").read_text(),
        )
        self.assertIn(
            "CALLER_HARNESS is always `claude`",
            (CLAUDE_ADAPTER / "SKILL.md").read_text(),
        )
        self.assertIn("never emits `USE_NATIVE`", (CLAUDE_ADAPTER / "SKILL.md").read_text())
        self.assertFalse((ROOT / "SKILL.md").exists())

    def test_install_binds_harness_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            install = subprocess.run(
                [ROOT / "scripts" / "install-symlinks", "--target", target],
                text=True,
                capture_output=True,
            )
            self.assertEqual(install.returncode, 0, install.stderr)

            check = subprocess.run(
                [ROOT / "scripts" / "check-symlinks", "--target", target],
                text=True,
                capture_output=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

            cursor_link = target / ".cursor" / "skills" / "model-router"
            codex_link = target / ".codex" / "skills" / "model-router"
            agents_link = target / ".agents" / "skills" / "model-router"
            claude_link = target / ".claude" / "skills" / "model-router"

            self.assertEqual(cursor_link.resolve(), CURSOR_ADAPTER.resolve())
            self.assertEqual(codex_link.resolve(), CODEX_ADAPTER.resolve())
            self.assertEqual(agents_link.resolve(), CODEX_ADAPTER.resolve())
            self.assertEqual(claude_link.resolve(), CLAUDE_ADAPTER.resolve())

            self.assertIn(
                "CALLER_HARNESS is always `claude`",
                (claude_link / "SKILL.md").read_text(),
            )

            for name in (
                "route",
                "run-delegate",
                "run-transaction",
                "delegate-snapshot",
                "delegate-delta",
                "check-report",
                "router-log",
            ):
                script = target / "scripts" / name
                self.assertTrue(script.is_symlink(), name)
                self.assertEqual(
                    script.resolve(), (ROOT / "scripts" / name).resolve(), name
                )

            help_run = subprocess.run(
                [target / "scripts" / "run-delegate", "--help"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(help_run.returncode, 0, help_run.stderr)

            codex_link.unlink()
            codex_link.symlink_to(target, target_is_directory=True)
            check = subprocess.run(
                [ROOT / "scripts" / "check-symlinks", "--target", target],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("ancestor-pointing", check.stdout + check.stderr)


if __name__ == "__main__":
    unittest.main()
