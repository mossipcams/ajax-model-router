#!/usr/bin/env python3
"""Cross-harness DELEGATE transaction: safety stages only."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TRANSACTION = ROOT / "scripts" / "run-transaction"

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
            "caller_harness": "cursor",
            "target_transport": "pi",
            "model": "opencode-go/minimax-m3",
            "tool": "pi",
            "allowed_files": ["src/example.py"],
            "acceptance": ["example.py exposes VALUE = 2"],
            "verification": ["true"],
            "stop_if": ["scope expansion required"],
            "working_directory": str(repo),
            "snapshot_directory": str(snap),
            "task": "Change VALUE to 2 in src/example.py",
            "requested_harness": "pi",
            "outcome_log": str(snap / "outcome.tsv"),
            "_transport_which": lambda cmd: f"/fake/{cmd}",
        }
        data.update(overrides)
        return data

    def write_context(self, path, data):
        # Drop non-JSON callables before write.
        payload = {k: v for k, v in data.items() if not callable(v)}
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path

    def validated(self, repo, snap, **overrides):
        ctx = ctxlib.validate_context(self.base_context(repo, snap, **overrides))
        ctx["_transport_which"] = lambda cmd: f"/fake/{cmd}"
        return ctx

    def test_stage_plan_is_delegate_lifecycle_only(self):
        plan = run_transaction.stage_slice("before_execute", "after_execute")
        self.assertEqual(
            plan,
            ["before_execute", "snapshot", "execute", "after_execute"],
        )
        self.assertNotIn("build_dispatch", plan)
        self.assertNotIn("validate_dispatch", plan)
        self.assertNotIn("before_review", plan)
        self.assertEqual(
            run_transaction.stage_slice("log_outcome", "log_outcome"),
            ["log_outcome"],
        )

    def test_context_rejects_bad_harness(self):
        with self.assertRaises(ctxlib.ContextError):
            ctxlib.validate_context(
                {
                    "task_id": "t",
                    "caller_harness": "cursor",
                    "target_transport": "opencode",
                    "model": "m",
                    "task": "t",
                    "allowed_files": ["a.py"],
                    "acceptance": ["ok"],
                    "verification": [],
                    "stop_if": [],
                    "working_directory": "/",
                    "snapshot_directory": "/tmp",
                }
            )

    def test_before_execute_rejects_same_harness_and_empty_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(
                repo,
                snap,
                caller_harness="pi",
                target_transport="pi",
                model="opencode-go/minimax-m3",
            )
            with self.assertRaises(hooks.HookError) as raised:
                hooks.before_execute(ctx)
            self.assertIn("USE_NATIVE", str(raised.exception))

            ctx = self.validated(repo, snap)
            ctx["allowed_files"] = []
            with self.assertRaises(hooks.HookError):
                hooks.before_execute(ctx)

    def test_claude_caller_can_delegate_to_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(
                repo,
                snap,
                caller_harness="claude",
                target_transport="cursor",
                model="composer-2.5",
                tool="cursor",
            )
            ctx = hooks.before_execute(ctx)
            self.assertEqual(ctx["artifacts"]["routing_decision"]["ACTION"], "DELEGATE")
            self.assertEqual(
                ctx["artifacts"]["routing_decision"]["CALLER_HARNESS"], "claude"
            )

    def test_before_execute_builds_delegate_prompt_not_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(repo, snap)
            ctx = hooks.before_execute(ctx)
            prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
            self.assertIn("Task:", prompt)
            self.assertIn("Stop if:", prompt)
            self.assertIn("Investigate the repository as needed.", prompt)
            self.assertIn("src/example.py", prompt)
            self.assertIn("STEPS:", prompt)
            self.assertNotIn("Code anchors", prompt)
            self.assertNotIn("PACKET_STATUS", prompt)
            self.assertEqual(
                ctx["artifacts"]["routing_decision"]["ACTION"], "DELEGATE"
            )

    def test_worktree_must_be_git_toplevel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            nested = repo / "src"
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(repo, snap)
            ctx["working_directory"] = str(nested)
            with self.assertRaises(hooks.HookError) as raised:
                hooks.before_execute(ctx)
            self.assertIn("git toplevel", str(raised.exception))

    def test_scope_violation_recorded_in_after_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(repo, snap)
            ctx = hooks.before_execute(ctx)
            ctx = hooks.snapshot(ctx)

            (repo / "outside.py").write_text("oops\n")
            (repo / "src" / "example.py").write_text("VALUE = 2\n")
            run_dir = Path(ctx["snapshot_directory"]) / "run"
            report = run_dir / "report.yaml"
            report.write_text(
                "DELEGATE_REPORT:\n"
                "  STATUS: COMPLETE\n"
                "  CHANGED_FILES: [src/example.py, outside.py]\n"
                "  VERIFICATION:\n"
                "    - TYPE: other\n"
                "      COMMAND: NONE\n"
                "      STEPS: []\n"
                "      RESULT: pass\n"
                "      DETAILS: ok\n"
                "  CONCERNS: []\n"
            )
            ctx["artifacts"]["report_path"] = str(report)
            ctx["status"] = "EXECUTED"
            ctx = hooks.after_execute(ctx)
            self.assertTrue(ctx["artifacts"]["scope_violations"])
            self.assertIn("outside.py", ctx["artifacts"]["scope_violations"])

    def test_log_outcome_does_not_block_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = self.validated(
                repo, snap, outcome_log="/no/such/dir/log.tsv"
            )
            ctx["gate_result"] = "ACCEPT"
            with mock.patch("lifecycle_hooks.subprocess.run") as mocked:
                mocked.return_value = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr="boom"
                )
                ctx = hooks.log_outcome(ctx)
            self.assertIn("outcome_log_warning", ctx)
            self.assertEqual(ctx["status"], "COMPLETE")

    def test_dry_run_plan_lists_thin_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx_path = self.write_context(
                Path(tmp) / "context.json", self.base_context(repo, snap)
            )
            result = run(
                TRANSACTION,
                "--context",
                ctx_path,
                "--dry-run-plan",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(
                plan["stages"],
                [
                    "before_execute",
                    "snapshot",
                    "execute",
                    "after_execute",
                ],
            )

    def test_same_harness_transaction_writes_decision_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx_path = self.write_context(
                Path(tmp) / "context.json",
                self.base_context(
                    repo,
                    snap,
                    caller_harness="cursor",
                    target_transport="cursor",
                    model="composer-2.5",
                    tool="cursor",
                ),
            )
            result = run(TRANSACTION, "--context", ctx_path, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "USE_NATIVE")
            self.assertEqual(payload["executed_stages"], [])
            self.assertTrue((snap / "routing_decision.json").is_file())
            self.assertFalse((snap / "pre.json").exists())
            self.assertFalse((snap / "post.json").exists())
            self.assertFalse((snap / "delta.json").exists())
            self.assertFalse((snap / "context.json").exists())


if __name__ == "__main__":
    unittest.main()
