#!/usr/bin/env python3
"""Thin execute transaction: safety stages only."""

import json
import subprocess
import tempfile
import unittest
from io import StringIO
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
    def setUp(self):
        # Never read/write the real route-health cache or run real probe CLIs.
        cache_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cache_dir.cleanup)
        self.health_cache = Path(cache_dir.name) / "route-health.json"
        patcher = mock.patch.dict("os.environ", {"AJAX_ROUTER_HEALTH_CACHE": str(self.health_cache)})
        patcher.start()
        self.addCleanup(patcher.stop)
        probe = mock.patch("route_health.probe", return_value=(True, "ok"))
        self.probe = probe.start()
        self.addCleanup(probe.stop)

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
            "agent": "pi",
            "model": "test-model",
            "risk": "low",
            "tool": "pi",
            "allowed_files": ["src/example.py"],
            "acceptance": ["example.py exposes VALUE = 2"],
            "working_directory": str(repo),
            "snapshot_directory": str(snap),
            "user_request": "Change VALUE to 2 in src/example.py",
            "verify": ["true"],
            "requested_agent": "pi",
            "outcome_log": str(snap / "outcome.tsv"),
        }
        data.update(overrides)
        return data

    def write_context(self, path, data):
        path.write_text(json.dumps(data, indent=2) + "\n")
        return path

    def test_stage_plan_is_route_execute_verify_only(self):
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

    def test_context_rejects_bad_agent(self):
        with self.assertRaises(ctxlib.ContextError):
            ctxlib.validate_context(
                {
                    "task_id": "t",
                    "agent": "opencode",
                    "model": "m",
                    "risk": "low",
                    "allowed_files": ["a.py"],
                    "acceptance": ["ok"],
                    "working_directory": "/",
                    "snapshot_directory": "/tmp",
                }
            )

    def test_before_execute_rejects_parent_and_empty_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap, agent="parent"))
            with self.assertRaises(hooks.HookError):
                hooks.before_execute(ctx)

            ctx = ctxlib.validate_context(
                self.base_context(repo, snap, allowed_files=["src/example.py"])
            )
            ctx["allowed_files"] = []
            with self.assertRaises(hooks.HookError):
                hooks.before_execute(ctx)

    def test_before_execute_builds_outcome_prompt_not_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            ctx = hooks.before_execute(ctx)
            prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
            self.assertIn("Implement the requested outcome.", prompt)
            self.assertIn("Investigate the repository as needed.", prompt)
            self.assertIn("You are already the selected implementation worker. Implement in-process.", prompt)
            self.assertIn("Never spawn native Cursor Task, best-of-n, or any other subagent.", prompt)
            self.assertIn("src/example.py", prompt)
            self.assertNotIn("Code anchors", prompt)
            self.assertNotIn("PACKET_STATUS", prompt)

    def test_worktree_must_be_git_toplevel(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            nested = repo / "src"
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, working_directory=str(nested))
            # validate_context resolves paths; force nested by patching after.
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            ctx["working_directory"] = str(nested)
            with self.assertRaises(hooks.HookError) as raised:
                hooks.before_execute(ctx)
            self.assertIn("git toplevel", str(raised.exception))

    def test_scope_violation_recorded_in_after_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            ctx = hooks.before_execute(ctx)
            ctx = hooks.snapshot(ctx)

            # Simulate delegate writing outside scope without invoking a model.
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
            ctx = ctxlib.validate_context(
                self.base_context(repo, snap, outcome_log="/no/such/dir/log.tsv")
            )
            ctx["gate_result"] = "ACCEPT"
            # Force logger path that cannot be created by mocking subprocess.
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

    def test_transaction_result_includes_log_paths_and_delegate_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx_path = self.write_context(
                Path(tmp) / "context.json", self.base_context(repo, snap)
            )
            run_dir = snap / "run"
            run_dir.mkdir(parents=True)

            def fake_execute(ctx):
                raw_log = run_dir / "raw.log"
                debug_log = run_dir / "debug.log"
                report = run_dir / "report.yaml"
                raw_log.write_text("raw\n")
                debug_log.write_text("[ajax-router] start\n")
                report.write_text(
                    "DELEGATE_REPORT:\n"
                    "  STATUS: COMPLETE\n"
                    "  CHANGED_FILES: [src/example.py]\n"
                    "  VERIFICATION:\n"
                    "    - TYPE: other\n"
                    "      COMMAND: NONE\n"
                    "      RESULT: pass\n"
                    "      DETAILS: ok\n"
                    "  CONCERNS: []\n"
                )
                ctx["artifacts"]["raw_log"] = str(raw_log.resolve())
                ctx["artifacts"]["debug_log"] = str(debug_log.resolve())
                ctx["artifacts"]["report_path"] = str(report.resolve())
                ctx["status"] = "EXECUTED"
                return ctx

            stdout = StringIO()
            with mock.patch.dict(run_transaction.HOOKS, execute=fake_execute):
                with mock.patch("sys.stdout", stdout):
                    exit_code = run_transaction.main(["--context", str(ctx_path)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                Path(payload["raw_log"]).resolve(),
                (run_dir / "raw.log").resolve(),
            )
            self.assertEqual(
                Path(payload["debug_log"]).resolve(),
                (run_dir / "debug.log").resolve(),
            )
            self.assertEqual(
                Path(payload["report_path"]).resolve(),
                (run_dir / "report.yaml").resolve(),
            )
            self.assertEqual(payload["delegate_status"], "COMPLETE")

    def test_transaction_hook_error_includes_log_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx_path = self.write_context(
                Path(tmp) / "context.json", self.base_context(repo, snap)
            )
            run_dir = snap / "run"
            run_dir.mkdir(parents=True)
            raw_log = run_dir / "raw.log"
            debug_log = run_dir / "debug.log"
            raw_log.write_text("raw\n")
            debug_log.write_text("[ajax-router] start\n")

            def failing_execute(ctx):
                ctx["artifacts"]["raw_log"] = str(raw_log.resolve())
                ctx["artifacts"]["debug_log"] = str(debug_log.resolve())
                ctx["artifacts"]["report_path"] = str((run_dir / "report.yaml").resolve())
                raise hooks.HookError("delegate transport failed (1): boom")

            stderr = StringIO()
            with mock.patch.dict(run_transaction.HOOKS, execute=failing_execute):
                with mock.patch("sys.stderr", stderr):
                    exit_code = run_transaction.main(["--context", str(ctx_path)])
            self.assertEqual(exit_code, 1)
            err = stderr.getvalue()
            self.assertIn("delegate transport failed (1): boom", err)
            self.assertIn(f"debug_log={debug_log.resolve()}", err)
            self.assertIn(f"raw_log={raw_log.resolve()}", err)

    def test_execute_forwards_subagent_status_via_readline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            ctx = hooks.before_execute(ctx)
            run_dir = Path(ctx["snapshot_directory"]) / "run"
            status_line = (
                json.dumps(
                    {
                        "type": "subagent_status",
                        "runId": "run_1",
                        "state": "running",
                        "detail": "Active",
                    }
                )
                + "\n"
            )
            report_tail = "ROUTER_REPORT_BEGIN\nDELEGATE_REPORT:\n"

            class FakeStdout:
                def __init__(self, lines):
                    self._lines = list(lines)
                    self.readline_calls = 0

                def readline(self):
                    self.readline_calls += 1
                    if self._lines:
                        return self._lines.pop(0)
                    return ""

                def close(self):
                    pass

            fake_stdout = FakeStdout([status_line, report_tail])
            fake_process = mock.Mock()
            fake_process.stdout = fake_stdout
            fake_process.poll.return_value = 0
            fake_process.returncode = 0
            fake_process.wait.return_value = 0

            captured = StringIO()
            with mock.patch("lifecycle_hooks.subprocess.Popen", return_value=fake_process) as popen:
                with mock.patch("sys.stdout", captured):
                    ctx = hooks.execute(ctx)

            _, popen_kwargs = popen.call_args
            self.assertEqual(popen_kwargs.get("bufsize"), 1)
            self.assertGreaterEqual(fake_stdout.readline_calls, 2)
            self.assertIn("subagent_status", captured.getvalue())
            self.assertIn(report_tail, ctx["artifacts"]["provider_metadata"]["stdout_tail"])
            self.assertNotIn("subagent_status", ctx["artifacts"]["provider_metadata"]["stdout_tail"])

    def test_execute_kills_child_when_forwarding_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(self.base_context(repo, snap))
            ctx = hooks.before_execute(ctx)

            class FakeStdout:
                def readline(self):
                    return json.dumps({"type": "subagent_status", "state": "running"}) + "\n"

                def close(self):
                    pass

            fake_process = mock.Mock()
            fake_process.stdout = FakeStdout()
            fake_process.poll.side_effect = [None, 0]
            fake_process.returncode = 0

            with mock.patch("lifecycle_hooks.subprocess.Popen", return_value=fake_process):
                with mock.patch("sys.stdout.write", side_effect=OSError("forward failed")):
                    with self.assertRaises(OSError):
                        hooks.execute(ctx)

            fake_process.kill.assert_called_once()
            fake_process.wait.assert_called()

    def test_task_label_uses_task_id_not_user_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = ctxlib.validate_context(
                self.base_context(
                    repo,
                    snap,
                    task_id="chip-abc",
                    user_request="A very long user request " * 50,
                )
            )
            ctx = hooks.before_execute(ctx)

            fake_process = mock.Mock()
            fake_process.stdout = mock.Mock()
            fake_process.stdout.readline.return_value = ""
            fake_process.poll.return_value = 0
            fake_process.returncode = 0

            with mock.patch("lifecycle_hooks.subprocess.Popen", return_value=fake_process) as popen:
                hooks.execute(ctx)

            command = popen.call_args[0][0]
            task_index = command.index("--task")
            self.assertEqual(command[task_index + 1], "chip-abc")
            self.assertNotIn("very long user request", command[task_index + 1])


    def test_prompt_includes_instructions_and_revision_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(
                repo,
                snap,
                instructions="Keep the public name VALUE.",
                revision_findings=["Round 1 renamed VALUE; restore it."],
            )
            ctx = hooks.before_execute(ctxlib.validate_context(data))
            prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
            self.assertIn("Additional instructions:\nKeep the public name VALUE.", prompt)
            self.assertIn("Revision findings", prompt)
            self.assertIn("- Round 1 renamed VALUE; restore it.", prompt)

    def test_context_rejects_caller_prompt_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            for field in ("prompt", "prompt_path", "prompt_file"):
                data = self.base_context(repo, snap, **{field: "/tmp/detailed.md"})
                with self.assertRaisesRegex(ctxlib.ContextError, field):
                    ctxlib.validate_context(data)

    def test_prompt_defers_to_repository_pr_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            ctx = hooks.before_execute(ctxlib.validate_context(self.base_context(repo, snap)))
            prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
            self.assertIn("repository's documented PR command", prompt)
            self.assertIn("scripts/gh-pr-create", prompt)
            self.assertNotIn("push, and run `gh pr create` after", prompt)

    def _fake_attempts(self, outcomes, touch=None):
        """Return an _execute_once stand-in writing one report per call."""
        calls = []

        def fake(ctx):
            status, concern = outcomes[len(calls)]
            calls.append((ctx["agent"], ctx["model"]))
            if touch:
                touch()
            run_dir = Path(ctx["snapshot_directory"]) / "run"
            run_dir.mkdir(parents=True, exist_ok=True)
            report = run_dir / "report.yaml"
            report.write_text(
                f"DELEGATE_REPORT:\n  STATUS: {status}\n  CHANGED_FILES: []\n"
                f"  VERIFICATION: []\n  CONCERNS:\n    - TYPE: {concern}\n"
            )
            ctx["artifacts"]["report_path"] = str(report)

        return fake, calls

    def test_execute_walks_fallback_chain_when_tool_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(
                repo, snap, fallback_chain=["codex/model-b", "cursor/model-c"]
            )
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "TOOL_UNAVAILABLE"), ("FAILED", "MISSING_TOOL"), ("COMPLETE", "NONE")]
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                with mock.patch("sys.stderr", StringIO()):
                    ctx = hooks.execute(ctx)
            self.assertEqual(
                calls, [("pi", "test-model"), ("codex", "model-b"), ("cursor", "model-c")]
            )
            self.assertEqual((ctx["agent"], ctx["model"], ctx["tool"]), ("cursor", "model-c", "cursor"))
            self.assertEqual(ctx["requested_agent"], "pi")
            attempts = ctx["artifacts"]["fallback_attempts"]
            self.assertEqual([a["reason"] for a in attempts], ["TOOL_UNAVAILABLE", "MISSING_TOOL"])
            self.assertTrue(Path(attempts[0]["report_path"]).is_file())
            self.assertEqual(ctx["fallback_chain"], [])

    def test_execute_does_not_fall_back_after_tree_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "TOOL_UNAVAILABLE")],
                touch=lambda: (repo / "src" / "example.py").write_text("VALUE = 9\n"),
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model")])
            self.assertEqual(ctx["artifacts"]["fallback_attempts"], [])
            self.assertEqual(ctx["fallback_chain"], ["codex/model-b"])

    def test_execute_does_not_fall_back_on_ordinary_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts([("FAILED", "MISSING_STRUCTURED_REPORT")])
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model")])


    def test_silent_failure_probed_and_falls_back_when_route_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            self.probe.return_value = (False, "429 usage limit")
            fake, calls = self._fake_attempts(
                [("FAILED", "MISSING_STRUCTURED_REPORT"), ("COMPLETE", "NONE")]
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                with mock.patch("sys.stderr", StringIO()):
                    ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model"), ("codex", "model-b")])
            self.probe.assert_called_once_with("pi/test-model")
            cache = json.loads(self.health_cache.read_text())
            self.assertFalse(cache["pi/test-model"]["ok"])
            self.assertTrue(cache["codex/model-b"]["ok"])

    def test_fallback_skips_routes_recently_marked_down(self):
        import route_health

        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            route_health.record("codex/model-b", False, "401")
            data = self.base_context(
                repo, snap, fallback_chain=["codex/model-b", "cursor/model-c"]
            )
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "TOOL_UNAVAILABLE"), ("COMPLETE", "NONE")]
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                with mock.patch("sys.stderr", StringIO()):
                    ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model"), ("cursor", "model-c")])

    def test_provider_error_retries_same_route_once_with_resume_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "PROVIDER_ERROR"), ("COMPLETE", "NONE")],
                touch=lambda: (repo / "src" / "example.py").write_text("VALUE = 9\n"),
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                with mock.patch("sys.stderr", StringIO()):
                    ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model")] * 2)
            self.assertIn("Resume:", Path(ctx["artifacts"]["prompt_path"]).read_text())
            self.assertEqual(ctx["fallback_chain"], ["codex/model-b"])
            self.probe.assert_not_called()

    def test_second_provider_error_marks_route_down_and_falls_back_if_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "PROVIDER_ERROR"), ("FAILED", "PROVIDER_ERROR"), ("COMPLETE", "NONE")]
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                with mock.patch("sys.stderr", StringIO()):
                    ctx = hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model")] * 2 + [("codex", "model-b")])
            self.assertNotIn("Resume:", Path(ctx["artifacts"]["prompt_path"]).read_text())
            self.assertFalse(json.loads(self.health_cache.read_text())["pi/test-model"]["ok"])

    def test_timeout_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts(
                [("FAILED", "TIMEOUT")],
                touch=lambda: (repo / "src" / "example.py").write_text("VALUE = 9\n"),
            )
            with mock.patch("lifecycle_hooks._execute_once", side_effect=fake):
                hooks.execute(ctx)
            self.assertEqual(calls, [("pi", "test-model")])

    def test_budget_note_only_for_local_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            for model, expected in (("local/swift", True), ("test-model", False)):
                data = self.base_context(repo, snap, model=model)
                ctx = hooks.before_execute(ctxlib.validate_context(data))
                prompt = Path(ctx["artifacts"]["prompt_path"]).read_text()
                self.assertEqual("tool calls" in prompt and "report BLOCKED" in prompt, expected)
                self.assertIn("Investigate the repository as needed.", prompt)

    def test_delegate_authored_failed_report_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            snap = Path(tmp) / "snap"
            snap.mkdir()
            data = self.base_context(repo, snap, fallback_chain=["codex/model-b"])
            ctx = hooks.snapshot(hooks.before_execute(ctxlib.validate_context(data)))
            fake, calls = self._fake_attempts([("FAILED", "PROVIDER_ERROR")])
            def clean_exit(c):
                fake(c)
                c["artifacts"]["provider_metadata"] = {"exit_code": 0}
            with mock.patch("lifecycle_hooks._execute_once", side_effect=clean_exit):
                hooks.execute(ctx)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
