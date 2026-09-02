import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from acpx_events import (
    classify_connection_closed,
    is_active_turn_activity,
    is_connection_closed_message,
    normalize_record,
    parse_jsonl_line,
)
from subagent_status import map_acp_record


class AcpxEventsTests(unittest.TestCase):
    def test_connection_closed_helpers(self):
        self.assertTrue(is_connection_closed_message("ACP connection closed"))
        self.assertEqual(classify_connection_closed(saw_activity=False), "ACP_CONNECTION_CLOSED_INIT")
        self.assertEqual(classify_connection_closed(saw_activity=True), "ACP_CONNECTION_CLOSED_ACTIVE")

    def test_is_active_turn_activity(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        self.assertFalse(is_active_turn_activity(init))
        chunk = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionUpdate": "agent_message_chunk", "content": {"text": "x"}},
        }
        self.assertTrue(is_active_turn_activity(chunk))
        tool = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionUpdate": "tool_call", "status": "pending"},
        }
        self.assertTrue(is_active_turn_activity(tool))
        prompt = {"jsonrpc": "2.0", "method": "session/prompt", "params": {}}
        self.assertTrue(is_active_turn_activity(prompt))

    def test_parse_jsonl_rejects_non_objects(self):
        self.assertIsNone(parse_jsonl_line("not json"))
        self.assertIsNone(parse_jsonl_line("[1,2]\n"))

    def test_normalize_maps_terminal_and_error(self):
        done = json.dumps({"jsonrpc": "2.0", "id": "1", "result": {"stopReason": "end_turn"}})
        event = normalize_record(parse_jsonl_line(done))
        self.assertEqual(event.kind, "completed")

        err = json.dumps({"jsonrpc": "2.0", "id": "1", "error": {"message": "boom"}})
        event = normalize_record(parse_jsonl_line(err))
        self.assertEqual(event.kind, "failed")
        self.assertEqual(event.error, "boom")

    def test_status_mapper_aligns_with_normalize_tool_events(self):
        started = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "tool_call",
                        "status": "pending",
                        "title": "Edit file",
                    },
                },
            }
        )
        record = parse_jsonl_line(started)
        event = normalize_record(record)
        state, detail = map_acp_record(record)
        self.assertEqual(event.kind, "activity/tool started")
        self.assertEqual(state, "tool_call")
        self.assertIn("Edit file", detail)


if __name__ == "__main__":
    unittest.main()
