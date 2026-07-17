import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "skills" / "model-router"


class SymlinkTests(unittest.TestCase):
    def test_router_is_canonical_under_skills(self):
        self.assertTrue((CANONICAL / "SKILL.md").is_file())
        self.assertTrue((CANONICAL / "agents" / "openai.yaml").is_file())
        self.assertFalse((ROOT / "SKILL.md").exists())

        for base in (".codex", ".claude"):
            link = ROOT / base / "skills" / "model-router"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), CANONICAL.resolve())
            self.assertNotEqual(
                os.path.commonpath((link, link.resolve())), str(link.resolve())
            )

    def test_install_and_reject_ancestor_pointing_link(self):
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
            installed = target / ".codex" / "skills" / "model-router"
            self.assertEqual(installed.resolve(), CANONICAL.resolve())

            scan = subprocess.run(
                ["find", "-L", target, "-type", "f"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertNotIn("loop", scan.stderr.lower())

            installed.unlink()
            installed.symlink_to(target, target_is_directory=True)
            check = subprocess.run(
                [ROOT / "scripts" / "check-symlinks", "--target", target],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("ancestor-pointing", check.stdout + check.stderr)


if __name__ == "__main__":
    unittest.main()
