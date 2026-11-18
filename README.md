# Wing

Wing is a Python terminal coding agent. LangGraph Deep Agents handles planning,
repository search, and edits. The OpenAI Python SDK sends model requests to
Azure OpenAI.

## Start a session

Install Wing with Python 3.11 or later.

```bash
uv sync
```

Set the Azure resource endpoint and the name of a deployment that supports the
Responses API and function calling. Set `AZURE_OPENAI_API_KEY` in your shell or
secret manager.

```bash
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
export AZURE_OPENAI_DEPLOYMENT=your-deployment-name
uv run wing --workspace /path/to/project
```

Ask Wing to inspect, edit, or explain the project. Use `/diff` for tracked
changes, `/skills` to list skills, and `/new` to start a fresh conversation.
Run a single task by passing the prompt on the command line.

```bash
uv run wing --workspace /path/to/project "Fix the parser and verify the change."
```

Wing can edit workspace files. It asks before deleting a file or running a
command and declines those actions when standard input is noninteractive.
Approved commands run with your local user privileges. The command environment
does not inherit your Azure credentials.

## Use skills in a project

Wing loads `AGENTS.md` from the workspace root. It ships pstack-derived skills
for architecture, debugging, verification, and investigation. Poteto mode
routes tasks through these workflows. Add a project skill at
`.wing/skills/<name>/SKILL.md` with `name` and `description` in its YAML
frontmatter. A project skill can override a bundled skill with the same name.
Use `uv run wing --skills` to list skills without Azure credentials.

The bundled skills adapt [pstack](https://github.com/cursor/plugins/tree/main/pstack)
under its [MIT license](src/wing/skills/LICENSE).

## Data and credentials

Wing disables LangSmith tracing and OpenTelemetry exports and removes SDK
diagnostic headers from model requests. Conversation state lives in memory.
Azure requests use `store=false`. Azure still receives prompts and tool results
needed for inference. Wing authenticates with an Azure API key.
