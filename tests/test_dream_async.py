"""Background-agent report parsing for the dream extractor.

Split from test_dream.py (module tripwire); reuses its fixture builders.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import dream  # noqa: E402
from test_dream import DreamTestBase, assistant, dispatch, human, verdict_text  # noqa: E402, F401


def async_launch(uid, agent_id):
    """The tool_result of a background Agent dispatch: no report, only an agentId."""
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": uid, "content": "launched"}]},
        "toolUseResult": {"agentId": agent_id, "isAsync": True, "status": "async_launched"},
    }


def indent(text):
    return "\n".join("    " + ln for ln in text.splitlines())


def hand_back(agent_id, text, **extra):
    body = f'<agent-message from="{agent_id}">\n[Subagent hand-back]\n{indent(text)}\n</agent-message>'
    return {"type": "user", "message": {"content": body}, **extra}


def task_note(agent_id, result):
    body = f"<task-notification>\n<task-id>{agent_id}</task-id>\n<result>{result}</result>\n</task-notification>"
    return {"type": "user", "message": {"content": body}}


class AsyncReportTest(DreamTestBase):
    def _launch(self, uid, agent, agent_id):
        return [dispatch(uid, agent), async_launch(uid, agent_id)]

    def test_handback_attributed_to_dispatched_agent_type(self):
        s = self.parse("a", [
            *self._launch("d1", "builder-standard", "ag1"),
            hand_back("ag1", verdict_text("COMPLETE")),
        ])
        self.assertEqual([(r["agent"], r["verdict"]) for r in s["reports"]], [("builder-standard", "COMPLETE")])
        agg = dream.aggregate([s])
        self.assertEqual((agg["agent_reports"], agg["agent_dispatches"]), (1, 1))

    def test_unknown_agent_id_is_unknown(self):
        s = self.parse("a", [hand_back("nope", verdict_text("BLOCKED"))])
        self.assertEqual(s["reports"][0]["agent"], "unknown")

    def test_indented_verdict_and_flags_parsed(self):
        dev = "- Inverted pin: test_x state S via path P"
        s = self.parse("a", [*self._launch("d1", "builder", "ag1"), hand_back("ag1", verdict_text("PARTIAL", deviations=dev, oos="- Split foo.py"))])
        rep = s["reports"][0]
        self.assertEqual(rep["verdict"], "PARTIAL")
        self.assertEqual(rep["flags"], ["Inverted pin: test_x state S via path P"])
        self.assertEqual(rep["out_of_scope"], ["Split foo.py"])

    def test_resumed_agent_two_handbacks_are_two_reports(self):
        s = self.parse("a", [
            *self._launch("d1", "builder", "ag1"),
            hand_back("ag1", verdict_text("PARTIAL")),
            hand_back("ag1", verdict_text("COMPLETE")),
            hand_back("ag1", verdict_text("COMPLETE")),  # replayed verbatim: deduped
        ])
        self.assertEqual([r["verdict"] for r in s["reports"]], ["PARTIAL", "COMPLETE"])

    def test_task_notification_without_verdict_not_counted(self):
        s = self.parse("a", [
            *self._launch("d1", "builder", "ag1"),
            task_note("ag1", "Report delivered as a message."),
        ])
        self.assertEqual(s["reports"], [])

    def test_task_notification_with_verdict_counted_once_alongside_handback(self):
        text = verdict_text("COMPLETE", oos="- Tidy bar.py")
        s = self.parse("a", [
            *self._launch("d1", "builder", "ag1"),
            task_note("ag1", text),
            hand_back("ag1", text),
        ])
        self.assertEqual(len(s["reports"]), 1)
        self.assertEqual(s["reports"][0]["agent"], "builder")

    def test_handbacks_are_not_corrections(self):
        text = verdict_text("COMPLETE")
        s = self.parse("a", [
            *self._launch("d1", "builder", "ag1"),
            hand_back("ag1", "No, that is wrong\n" + text),  # isMeta absent
            hand_back("ag1", "Stop\n" + text, isMeta=True),
            task_note("ag1", "No result for you"),
        ])
        self.assertEqual(s["corrections"], 0)

    def test_escalation_via_background_handbacks(self):
        s = self.parse("a", [
            *self._launch("d1", "builder-simple", "ag1"),
            hand_back("ag1", verdict_text("BLOCKED")),
            *self._launch("d2", "builder-standard", "ag2"),
            hand_back("ag2", verdict_text("COMPLETE")),
        ])
        self.assertEqual(s["escalations"], [("builder", 0, 1)])

    def test_private_bookkeeping_not_in_summary(self):
        s = self.parse("a", [*self._launch("d1", "builder", "ag1")])
        self.assertFalse([k for k in s if k.startswith("_")])


if __name__ == "__main__":
    unittest.main()
