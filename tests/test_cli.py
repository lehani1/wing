import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

from wing.cli import main
from wing.provider import azure_model


def tool_call(name, call_id, **arguments):
    return dict(
        type="function_call", id=f"fc_{call_id}", call_id=call_id,
        name=name, arguments=json.dumps(arguments), status="completed",
    )


def message(text):
    return dict(
        type="message", id="msg_final", status="completed", role="assistant",
        content=[dict(type="output_text", text=text, annotations=[])],
    )


class CodingSessionTest(unittest.TestCase):
    def run_session(self, terminal, expected_command):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hello.py").write_text('print("before")\n')
            (root / "AGENTS.md").write_text("Keep the sample small.")
            (root / "keep.txt").write_text("Keep this file.")
            (root / ".env").write_text("PRIVATE_VALUE=should-not-leak")
            (root / "alias").symlink_to(".env")
            custom_skill = root / ".wing/skills/project-workflow/SKILL.md"
            custom_skill.parent.mkdir(parents=True)
            custom_skill.write_text(
                "---\nname: project-workflow\n"
                "description: Project-specific verification steps.\n---\nRun the sample.\n"
            )

            outputs = iter([
                [
                    tool_call("read_file", "skill", file_path="/__wing_skills__/poteto-mode/SKILL.md"),
                    tool_call("read_file", "sample", file_path="/hello.py"),
                    tool_call("read_file", "private", file_path="/alias"),
                ],
                [tool_call(
                    "edit_file", "edit", file_path="/hello.py",
                    old_string='print("before")', new_string='print("after")',
                )],
                [tool_call("run_command", "command", argv=[sys.executable, "-c",
                    "import os, runpy; assert 'AZURE_OPENAI_API_KEY' not in os.environ; "
                    "runpy.run_path('hello.py')"])],
                [tool_call("delete", "delete", file_path="/keep.txt")],
                [message("Updated hello.py.")],
            ])
            requests = []

            def respond(request):
                self.assertEqual(str(request.url), "https://example.openai.azure.com/openai/v1/responses")
                self.assertEqual(request.headers["authorization"], "Bearer fixture-key")
                self.assertEqual(
                    {name for name in request.headers if name.startswith("x-stainless-")},
                    {"x-stainless-raw-response"},
                )
                self.assertNotIn("traceparent", request.headers)
                body = json.loads(request.content)
                requests.append(body)
                self.assertEqual(body["model"], "fixture-deployment")
                self.assertIs(body["store"], False)
                self.assertNotIn("previous_response_id", body)
                return httpx.Response(200, json=dict(
                    id=f"resp_{len(requests)}", created_at=1, object="response",
                    model="fixture-deployment", status="completed", output=next(outputs),
                    usage=dict(
                        input_tokens=10, output_tokens=4, total_tokens=14,
                        input_tokens_details=dict(cached_tokens=0),
                        output_tokens_details=dict(reasoning_tokens=0),
                    ),
                ))

            def mock_azure(config):
                return azure_model(config, transport=httpx.MockTransport(respond))

            stdout, stderr = io.StringIO(), io.StringIO()
            env = {
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "fixture-deployment",
                "AZURE_OPENAI_API_KEY": "fixture-key",
                "LANGSMITH_TRACING": "true",
                "LANGCHAIN_TRACING_V2": "true",
                "LANGSMITH_OTEL_ENABLED": "true",
                "OPENAI_CUSTOM_HEADERS": "Traceparent: fixture-trace",
            }
            with (
                patch.dict(os.environ, env, clear=False),
                patch("wing.provider.azure_model", mock_azure),
                patch("sys.stdin", terminal), redirect_stdout(stdout), redirect_stderr(stderr),
            ):
                exit_code = main(["--workspace", directory, "Update the sample and run it."])
                self.assertEqual(os.environ["LANGSMITH_TRACING"], "false")
                self.assertEqual(os.environ["LANGCHAIN_TRACING_V2"], "false")
                self.assertEqual(os.environ["LANGSMITH_OTEL_ENABLED"], "false")

            self.assertEqual(exit_code, 0, stderr.getvalue())
            self.assertEqual(len(requests), 5)
            self.assertEqual(stdout.getvalue().strip(), "Updated hello.py.")
            self.assertIn("Review run_command", stderr.getvalue())
            self.assertIn("Review delete", stderr.getvalue())
            self.assertEqual((root / "keep.txt").read_text(), "Keep this file.")
            self.assertEqual((root / "hello.py").read_text(), 'print("after")\n')
            first_request = json.dumps(requests[0])
            self.assertIn("Keep the sample small.", first_request)
            self.assertIn("project-workflow", first_request)
            tools = {tool["name"] for tool in requests[0]["tools"]}
            self.assertTrue({"write_todos", "grep", "read_file", "edit_file"}.issubset(tools), tools)
            self.assertFalse({"task", "execute"} & tools)
            self.assertNotIn("should-not-leak", json.dumps(requests))
            self.assertIn("State the user's intended outcome", json.dumps(requests[1]))
            command_result = next(
                entry["output"] for entry in requests[-1]["input"]
                if entry.get("call_id") == "command" and entry["type"] == "function_call_output"
            )
            self.assertIn(expected_command, command_result)

    def test_interactive_approval_runs_command_with_filtered_environment(self):
        terminal = io.StringIO("y\nn\n")
        terminal.isatty = lambda: True
        self.run_session(terminal, "Exit code 0\nafter")

    def test_noninteractive_session_rejects_command(self):
        self.run_session(io.StringIO(), "did not approve")


if __name__ == "__main__":
    unittest.main()
