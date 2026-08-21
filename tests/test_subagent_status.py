import json
import sys
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from subagent_status import (
    SubagentStatusTracker,
    emit_ndjson,
    is_subagent_status_line,
    map_acp_record,
)


class SubagentStatusTests(unittest.TestCase):
    def test_state_machine_transitions(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "fix bug",
            emit=emitted.append,
            stall_seconds=999,
        )
        tracker.event("queued", "Waiting")
        tracker.event("starting", "Launching")
        tracker.event("running", "Active")
        self.assertEqual([event["state"] for event in emitted], ["queued", "starting", "running"])
        self.assertEqual(emitted[-1]["runId"], "run_1")
        self.assertEqual(emitted[-1]["parentTaskId"], "task_1")
        self.assertEqual(emitted[-1]["harness"], "cursor")
        self.assertEqual(emitted[-1]["model"], "composer-2.5")
        self.assertEqual(emitted[-1]["task"], "fix bug")
        self.assertIn("timestamp", emitted[-1])

    def test_tool_call_and_permission_mapping(self):
        started = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "status": "in_progress",
                    "title": "Reading src/chat/MessageList.tsx",
                },
            },
        }
        state, detail = map_acp_record(started)
        self.assertEqual(state, "tool_call")
        self.assertIn("MessageList.tsx", detail)

        permission = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "permission_request",
                    "title": "Run shell command",
                },
            },
        }
        state, detail = map_acp_record(permission)
        self.assertEqual(state, "waiting_for_permission")

    def test_session_request_permission_jsonrpc_mapping(self):
        record = {
            "jsonrpc": "2.0",
            "method": "session/request_permission",
            "params": {
                "sessionId": "s1",
                "toolCall": {
                    "title": "Reading",
                    "locations": [{"path": "src/chat/MessageList.tsx"}],
                },
                "options": [{"kind": "allow_once"}],
            },
        }
        state, detail = map_acp_record(record)
        self.assertEqual(state, "waiting_for_permission")
        self.assertIn("Reading", detail)
        self.assertIn("MessageList.tsx", detail)

    def test_tool_detail_includes_locations_and_nested_tool_call(self):
        body = {
            "title": "Reading",
            "locations": [{"path": "src/chat/MessageList.tsx"}],
        }
        state, detail = map_acp_record(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call",
                        "status": "in_progress",
                        **body,
                    },
                },
            }
        )
        self.assertEqual(state, "tool_call")
        self.assertEqual(detail, "Reading src/chat/MessageList.tsx")

        nested = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "status": "in_progress",
                    "toolCall": {
                        "title": "Reading",
                        "path": "src/chat/MessageList.tsx",
                    },
                },
            },
        }
        state, detail = map_acp_record(nested)
        self.assertEqual(state, "tool_call")
        self.assertIn("Reading", detail)
        self.assertIn("MessageList.tsx", detail)

    def test_terminal_states_do_not_reopen(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "task",
            emit=emitted.append,
        )
        tracker.terminal("completed", "Done")
        tracker.event("running", "Should not emit")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["state"], "completed")

    def test_stalled_after_silence(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "task",
            emit=emitted.append,
            stall_seconds=5,
        )
        tracker.event("running", "Active")
        tracker.last_event_monotonic = 0
        payload = tracker.maybe_stalled(now=10)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["state"], "stalled")

    def test_emit_ndjson_and_line_detection(self):
        buffer = StringIO()
        payload = {
            "type": "subagent_status",
            "runId": "run_1",
            "state": "running",
        }
        emit_ndjson(payload, stream=buffer)
        line = buffer.getvalue()
        self.assertTrue(is_subagent_status_line(line))
        self.assertFalse(is_subagent_status_line('{"jsonrpc":"2.0"}\n'))

    def test_handle_stdout_line_updates_tracker(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "task",
            emit=emitted.append,
        )
        line = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "hello"},
                    },
                },
            }
        )
        tracker.handle_stdout_line(line + "\n")
        self.assertEqual(emitted[-1]["state"], "running")

    def test_tool_detail_prefers_title_over_kind(self):
        record = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "status": "in_progress",
                    "kind": "read",
                    "title": "Read File",
                },
            },
        }
        state, detail = map_acp_record(record)
        self.assertEqual(state, "tool_call")
        self.assertEqual(detail, "Read File")

    def test_sparse_tool_call_update_does_not_clobber_detail(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "task",
            emit=emitted.append,
        )
        started = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call",
                        "status": "in_progress",
                        "title": "Reading src/chat/MessageList.tsx",
                    },
                },
            }
        )
        sparse = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "status": "in_progress",
                    },
                },
            }
        )
        tracker.handle_stdout_line(started + "\n")
        tool_events = [row for row in emitted if row["state"] == "tool_call"]
        self.assertEqual(len(tool_events), 1)
        self.assertIn("MessageList.tsx", tool_events[0]["detail"])
        tracker.handle_stdout_line(sparse + "\n")
        tool_events = [row for row in emitted if row["state"] == "tool_call"]
        self.assertEqual(len(tool_events), 1)
        self.assertIn("MessageList.tsx", tool_events[0]["detail"])

    def test_failed_overrides_completed_terminal_state(self):
        emitted = []
        tracker = SubagentStatusTracker(
            "run_1",
            "task_1",
            "cursor",
            "composer-2.5",
            "task",
            emit=emitted.append,
        )
        tracker.terminal("completed", "Finished")
        tracker.terminal("failed", "Missing structured report")
        self.assertEqual(emitted[-1]["state"], "failed")
        self.assertEqual(emitted[-1]["detail"], "Missing structured report")
        self.assertEqual(len(emitted), 2)


if __name__ == "__main__":
    unittest.main()
