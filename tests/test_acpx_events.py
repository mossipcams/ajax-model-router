import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))

from acpx_events import normalize_record, parse_jsonl_line
from subagent_status import map_acp_record


class AcpxEventsTests(unittest.TestCase):
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
