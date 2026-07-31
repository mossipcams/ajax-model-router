#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION = ROOT / "scripts" / "run-transaction"
CHECK_DISPATCH = ROOT / "scripts" / "check-dispatch"

import sys

sys.path.insert(0, str(ROOT / "libexec"))
import lifecycle_context as ctxlib
import lifecycle_hooks as hooks
import run_transaction


def run(*args, cwd=None, check=True, env=None):
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


class LifecycleTransactionTests(unittest.TestCase):
    def make_repo(self, tmp):
        repo = Path(tmp) / "repo"
        repo.mkdir()
        run("git", "init", "-q", cwd=repo)
        run("git", "config", "user.email", "test@example.com", cwd=repo)
        run("git", "config", "user.name", "Test", cwd=repo)
        (repo / "src").mkdir()
        (repo / "src" / "example.py").write_text("VALUE = 1\n")
        run("git", "add", ".", cwd=repo)
        run("git", "commit", "-qm", "fixture", cwd=repo)
        return repo

    def base_context(self, repo, snap, **overrides):
        data = {
            "task_id": "task-1",
            "dispatch_level": "direct",
            "risk": "low",
            "provider": "pi",
            "model": "test-model",
            "tool": "pi",
            "allowed_files": ["src/example.py"],
            "acceptance": ["example.py exposes VALUE = 2"],
            "working_directory": str(repo),
            "snapshot_directory": str(snap),
            "user_request": "Change VALUE to 2 in src/example.py",
            "verification_commands": ["true"],
            "stop_conditions": ["Edit outside allowed files"],
            "repository_id": "test-repo",
            "route_rule_id": "R-DELEGATE",
            "task_kind": "mechanical",
            "lane": "pi-delegate",
            "calibration_log": str(snap / "log.tsv"),
        }
        data.update(overrides)
        return data

    def write_context(self, path, data):
        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    def test_stage_plan_is_ordered(self):
        plan = run_transaction.stage_slice("before_dispatch", "before_review")
        self.assertEqual(plan[0], "before_dispatch")
        self.assertEqual(plan[-1], "before_review")
        self.assertIn("delegate", plan)
        self.assertNotIn("after_review", plan)
        self.assertEqual(
            run_transaction.stage_slice("after_review", "log_calibration"),
            ["after_review", "log_calibration"],
        )

    def test_context_rejects_bad_dispatch_level(self):
        with self.assertRaises(ctxlib.ContextError):
            ctxlib.validate_context(
                {
                    "task_id": "t",
                    "dispatch_level": "mega",
                    "risk": "low",
                    "provider": "pi",
                    "model": "m",
                    "allowed_files": ["a.py"],
                    "acceptance": ["ok"],
                    "working_directory": "/",
                    "snapshot_directory": "/tmp",
                }
            )

    def test_check_dispatch_direct_and_compact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            direct = tmp / "direct.md"
            direct.write_text(
                "DISPATCH_LEVEL: direct\n"
                "## User request\n\ndo the thing\n"
                "## Allowed files\n\n- a.py\n"
                "## Acceptance criteria\n\n- done\n"
                "## Stop conditions\n\n- stop\n"
            )
            result = run(CHECK_DISPATCH, "direct", direct, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

            compact = tmp / "compact.md"
            compact.write_text(
                "PACKET_STATUS: READY\n"
                "UNRESOLVED_UNCERTAINTY: NONE\n"
                "BLOCKERS: []\n"
                "DISPATCH_LEVEL: compact\n"
                "## Task\n\ngoal\n"
                "## Allowed files\n\n- a.py\n"
                "## Forbidden changes\n\n- none\n"
                "## Acceptance\n\n- ok\n"
                "## Constraints\n\n- NONE\n"
                "## Verification\n\nmethods:\n  - type: other\n    command: true\n    expected: exit 0\nreason: smoke\n"
                "## Stop if\n\n- stop\n"
            )
            result = run(CHECK_DISPATCH, "compact", compact, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

            compact.write_text(compact.read_text() + "\n## Context evidence\n\nleak\n")
            result = run(CHECK_DISPATCH, "compact", compact, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Context evidence", result.stderr)

    def test_invalid_dispatch_fails_before_delegate_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            context_path = Path(tmp) / "context.json"
            # Missing user_request → before_dispatch fails before any transport.
            self.write_context(
                context_path,
                self.base_context(repo, snap, user_request=""),
            )
            called = {"delegate": False}

            def boom(ctx):
                called["delegate"] = True
                raise AssertionError("delegate must not run")

            with mock.patch.dict(hooks.HOOKS, {"delegate": boom}):
                result = run(
                    TRANSACTION,
                    "--context",
                    context_path,
                    "--until-stage",
                    "before_review",
                    check=False,
                )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(called["delegate"])
            self.assertIn("user_request", result.stderr)

    def test_direct_build_does_not_read_implementation_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            opened = []
            real_open = open

            def tracking_open(path, *args, **kwargs):
                text = str(path)
                if text.endswith("example.py") or text.endswith("src/example.py"):
                    opened.append(text)
                return real_open(path, *args, **kwargs)

            with mock.patch("builtins.open", tracking_open):
                hooks.before_dispatch(ctx)
                hooks.build_dispatch(ctx)
                hooks.validate_dispatch(ctx)
            self.assertEqual(opened, [])
            prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
            self.assertIn("DISPATCH_LEVEL: direct", prompt)
            self.assertIn("Change VALUE to 2", prompt)
            self.assertNotIn("## Context evidence", prompt)

    def test_snapshot_evidence_reuse_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            hooks.before_dispatch(ctx)
            hooks.build_dispatch(ctx)
            hooks.validate_dispatch(ctx)
            hooks.snapshot(ctx)
            self.assertEqual(ctx["status"], "SNAPSHOT_OK")
            first_mtime = (snap / "pre.json").stat().st_mtime_ns
            hooks.snapshot(ctx)
            self.assertEqual(ctx["status"], "SNAPSHOT_REUSED")
            self.assertEqual((snap / "pre.json").stat().st_mtime_ns, first_mtime)

    def test_review_bundle_is_minimal(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            hooks.before_dispatch(ctx)
            hooks.build_dispatch(ctx)
            hooks.validate_dispatch(ctx)
            hooks.snapshot(ctx)

            # Simulate delegate write without spending tokens.
            (repo / "src" / "example.py").write_text("VALUE = 2\n")
            report = snap / "run" / "report.yaml"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                "DELEGATE_REPORT:\n"
                "  STATUS: COMPLETE\n"
                "  CHANGED_FILES: [src/example.py]\n"
                "  VERIFICATION:\n"
                "    - TYPE: test\n"
                "      COMMAND: true\n"
                "      STEPS: []\n"
                "      RESULT: pass\n"
                "      DETAILS: ok\n"
                "  CONCERNS: [watch nearby callers]\n"
            )
            ctx["artifacts"]["report_path"] = str(report)
            hooks.after_delegate(ctx)
            hooks.run_verification(ctx)
            hooks.before_review(ctx)

            bundle_path = Path(ctx["artifacts"]["review_bundle_path"])
            bundle = json.loads(bundle_path.read_text())
            self.assertEqual(bundle["dispatch_level"], "direct")
            self.assertEqual(bundle["acceptance"], ctx["acceptance"])
            self.assertIn("src/example.py", bundle["changed_files"])
            self.assertIn("watch nearby callers", bundle["delegate_concerns"])
            self.assertIn("delta_hunks", bundle)
            for banned in (
                "transcript",
                "raw_log",
                "packet",
                "repository_summary",
                "reasoning",
                "full_prompt",
            ):
                self.assertNotIn(banned, bundle)
            # Full packet / prompt must not be embedded.
            blob = json.dumps(bundle)
            self.assertNotIn("ROUTER_REPORT_BEGIN", blob)
            self.assertNotIn("You are a bounded implementation worker", blob)

    def test_after_review_and_calibration_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            log = snap / "log.tsv"
            ctx = ctxlib.validate_context(self.base_context(repo, snap, calibration_log=str(log)))
            hooks.before_dispatch(ctx)
            hooks.build_dispatch(ctx)
            ctx["artifacts"]["review_bundle_path"] = str(snap / "run" / "review_bundle.json")
            (snap / "run").mkdir(parents=True, exist_ok=True)
            (snap / "run" / "review_bundle.json").write_text("{}\n")
            ctx["gate_result"] = "ACCEPT"
            hooks.after_review(ctx)
            hooks.log_calibration(ctx)
            self.assertTrue(log.is_file())
            self.assertIn("ACCEPT", log.read_text())
            self.assertEqual(ctx["status"], "COMPLETE")

    def test_cli_dry_run_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            context_path = Path(tmp) / "context.json"
            self.write_context(context_path, self.base_context(repo, snap))
            result = run(
                TRANSACTION,
                "--context",
                context_path,
                "--until-stage",
                "validate_dispatch",
                "--dry-run-plan",
            )
            plan = json.loads(result.stdout)
            self.assertEqual(
                plan["stages"],
                [
                    "before_dispatch",
                    "build_dispatch",
                    "validate_dispatch",
                ],
            )

    def test_cli_runs_until_validate_without_delegate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            context_path = Path(tmp) / "context.json"
            self.write_context(context_path, self.base_context(repo, snap))
            result = run(
                TRANSACTION,
                "--context",
                context_path,
                "--until-stage",
                "snapshot",
            )
            payload = json.loads(result.stdout)
            self.assertIn(payload["status"], {"SNAPSHOT_OK", "SNAPSHOT_REUSED"})
            self.assertEqual(
                payload["executed_stages"],
                [
                    "before_dispatch",
                    "build_dispatch",
                    "validate_dispatch",
                    "snapshot",
                ],
            )
            self.assertTrue((snap / "pre.json").is_file())
            self.assertTrue((snap / "run" / "prompt.txt").is_file())


if __name__ == "__main__":
    unittest.main()
