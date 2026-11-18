import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage

from wing.agent import build_agent, command_tool
from wing.cli import disable_telemetry, main, new_conversation, show_diff
from wing.provider import AzureConfig, azure_model


def response(status="completed"):
    return httpx.Response(200, json={
        "id": "resp_fixture", "created_at": 1, "object": "response", "model": "fixture",
        "status": status, "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"type": "message", "id": "msg_fixture", "status": status, "role": "assistant",
                    "content": [{"type": "output_text", "text": "fixture reply", "annotations": []}]}],
    })


class RegressionTest(unittest.TestCase):
    def setUp(self):
        disable_telemetry()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = AzureConfig("fixture", "https://example.invalid/openai/v1/", "dummy")

    def run_cli(self, replies, *args):
        self.requests = []
        replies = iter(replies)

        def respond(request):
            self.requests.append(json.loads(request.content))
            return next(replies)

        stdout, stderr = io.StringIO(), io.StringIO()
        with (patch.object(AzureConfig, "from_env", return_value=self.config),
              patch("wing.provider.azure_model", lambda config: azure_model(config, transport=httpx.MockTransport(respond))),
              redirect_stdout(stdout), redirect_stderr(stderr)):
            code = main(["--workspace", str(self.root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_automatic_reads_skip_protected_targets(self):
        private = self.root / ".aws/config"
        private.parent.mkdir()
        private.write_text("---\nname: hidden\ndescription: private fixture marker\n---\n")
        skill = self.root / ".wing/skills/hidden/SKILL.md"
        skill.parent.mkdir(parents=True)
        for entry in (self.root / "AGENTS.md", skill):
            entry.symlink_to(private)
        code, _, stderr = self.run_cli([response()], "hello")
        self.assertEqual(code, 0, stderr)
        self.assertNotIn("private fixture marker", json.dumps(self.requests))

    def test_archive_in_checkpoint_not_workspace(self):
        messages = []
        for _ in range(34):
            messages.extend([HumanMessage("archive marker " + "sample placeholder " * 2700), AIMessage("ok")])
        with azure_model(self.config, transport=httpx.MockTransport(lambda request: response())) as model:
            agent = build_agent(model, self.root)
            result = agent.invoke({"messages": messages + [HumanMessage("summarize")]}, new_conversation())
        self.assertFalse(list(self.root.iterdir()))
        self.assertIn("archive marker", str(result["files"]))

    def test_failed_turn_branches_from_last_success(self):
        with (patch("sys.stdin.isatty", return_value=True),
              patch("builtins.input", side_effect=["remember apples", "bad prompt", "continue", "/quit"])):
            self.run_cli([response(), httpx.Response(400, json={"error": {"message": "invalid"}}), response()])
        self.assertEqual(len(self.requests), 3)
        contents = json.dumps(self.requests[-1]["input"])
        self.assertIn("remember apples", contents)
        self.assertNotIn("bad prompt", contents)

    def test_incomplete_is_failure(self):
        code, stdout, stderr = self.run_cli([response("incomplete")], "hello")
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("max_output_tokens", stderr)

    def test_timeout_stops_child(self):
        child = "import time,pathlib; pathlib.Path('ready').touch(); time.sleep(1); pathlib.Path('late').touch()"
        parent = f"import subprocess,sys; subprocess.run([sys.executable, '-c', {child!r}])"
        with patch("wing.agent.COMMAND_TIMEOUT", 0.5):
            self.assertIn("timeout", command_tool(self.root)([sys.executable, "-c", parent]))
        self.assertTrue((self.root / "ready").exists())
        time.sleep(1)
        self.assertFalse((self.root / "late").exists())

    def test_diff_before_first_commit(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        sample = self.root / "sample"
        sample.write_text("staged\n")
        subprocess.run(["git", "add", "sample"], cwd=self.root, check=True)
        sample.write_text("working tree\n")
        with redirect_stdout(io.StringIO()) as output:
            show_diff(self.root)
        self.assertIn("+working tree", output.getvalue())
