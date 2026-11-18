import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

HELP = """Terminal commands
  /skills   List bundled and project skills
  /diff     Show tracked changes
  /new      Start a fresh conversation
  /help     Show these commands
  /quit     Exit"""


def disable_telemetry() -> None:
    for prefix in ("LANGCHAIN", "LANGSMITH"):
        for setting in ("TRACING", "TRACING_V2", "OTEL_ENABLED", "OTEL_ONLY"):
            os.environ[f"{prefix}_{setting}"] = "false"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ.pop("OPENAI_LOG", None)


def terminal_text(value: str) -> str:
    return "".join(
        char for char in value
        if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) <= 159)
    )


def run_turn(agent, config, prompt: str, interactive: bool) -> str:
    from langgraph.types import Command

    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config)
    while interrupts := result.get("__interrupt__"):
        resumes = {}
        for pause in interrupts:
            decisions = []
            for action in pause.value["action_requests"]:
                print(f"Review {action['name']} {json.dumps(action['args'], ensure_ascii=True)}",
                      file=sys.stderr)
                answer = ""
                if interactive:
                    print("Approve? [y/N] ", file=sys.stderr, end="", flush=True)
                    answer = sys.stdin.readline().strip().lower()
                if answer == "y":
                    decisions.append({"type": "approve"})
                else:
                    decisions.append({"type": "reject", "message": "The user did not approve this action."})
            resumes[pause.id] = {"decisions": decisions}
        config = {**config, "configurable": {"thread_id": config["configurable"]["thread_id"]}}
        result = agent.invoke(Command(resume=resumes), config)

    message = result["messages"][-1]
    if message.type == "ai" and message.text:
        return terminal_text(message.text)
    return "The model returned no text."


def show_skills(root: Path) -> None:
    from wing.agent import BUILTIN_SKILLS, workspace_skills

    names = {}
    for label, path in (("bundled", BUILTIN_SKILLS), ("project", workspace_skills(root))):
        if path is not None:
            for entry in path.glob("*/SKILL.md"):
                if entry.resolve().is_relative_to(path):
                    names[entry.parent.name] = label
    for name, label in sorted(names.items()):
        print(terminal_text(f"{name} ({label})"))


def show_diff(root: Path) -> None:
    try:
        head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=root,
                              capture_output=True)
        base = "HEAD"
        if head.returncode == 1:
            base = subprocess.check_output(["git", "hash-object", "-t", "tree", "--stdin"],
                                           cwd=root, input=b"").decode().strip()
        result = subprocess.run(
            ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", base, "--", "."],
            cwd=root, capture_output=True, text=True, errors="replace", check=False,
        )
        print(terminal_text(result.stdout or result.stderr or "No tracked changes."), end="\n")
    except OSError as error:
        print(f"Could not show changes: {error}", file=sys.stderr)


def new_conversation() -> dict:
    return {"configurable": {"thread_id": uuid4().hex}, "recursion_limit": 80}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Code in a local project with Azure OpenAI and Deep Agents.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Project directory")
    parser.add_argument("--model", metavar="DEPLOYMENT", help="Azure OpenAI deployment name")
    parser.add_argument("--skills", action="store_true", help="List available skills and exit")
    parser.add_argument("prompt", nargs="?", help="Run one task and exit")
    args = parser.parse_args(argv)
    root = args.workspace.resolve()
    if not root.is_dir():
        parser.error("--workspace must be an existing directory")

    disable_telemetry()
    if args.skills:
        show_skills(root)
        return 0

    from langsmith import tracing_context
    from openai import APIConnectionError, APIStatusError
    from wing.agent import ResponseStatusError, build_agent
    from wing.provider import AzureConfig, azure_model

    try:
        azure = AzureConfig.from_env(args.model)
    except ValueError as error:
        parser.error(str(error))

    interactive = sys.stdin.isatty()
    if args.prompt is None and not interactive:
        parser.error("Pass a prompt when standard input is not a terminal.")

    def reply(agent, config, prompt: str) -> int:
        try:
            print(run_turn(agent, config, prompt, interactive), flush=True)
            return 0
        except ResponseStatusError as error:
            print(terminal_text(str(error)), file=sys.stderr)
        except APIStatusError as error:
            print(f"Azure OpenAI returned HTTP {error.status_code}. Check the key, endpoint, and deployment.",
                  file=sys.stderr)
        except APIConnectionError:
            print("Could not connect to Azure OpenAI. Check the endpoint and network connection.", file=sys.stderr)
        except Exception as error:
            print(f"Task stopped ({type(error).__name__}).", file=sys.stderr)
        return 1

    try:
        with tracing_context(enabled=False), azure_model(azure) as model:
            agent = build_agent(model, root)
            config = new_conversation()
            checkpoint = None
            if args.prompt is not None:
                return reply(agent, config, args.prompt)

            print(f"Wing | {root} | {terminal_text(azure.deployment)} | /help")
            while True:
                try:
                    prompt = input("wing> ").strip()
                except EOFError:
                    return 0
                if not prompt:
                    continue
                if prompt == "/quit":
                    return 0
                if prompt == "/help":
                    print(HELP)
                elif prompt == "/skills":
                    show_skills(root)
                elif prompt == "/diff":
                    show_diff(root)
                elif prompt == "/new":
                    config = new_conversation()
                    checkpoint = None
                    print("New conversation.")
                elif reply(agent, checkpoint or config, prompt) == 0:
                    checkpoint = {**config, "configurable": agent.get_state(config).config["configurable"]}
                elif checkpoint is None:
                    config = new_conversation()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
