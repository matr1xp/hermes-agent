# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
# Clone with submodules (required for terminal backends and RL training)
git clone --recurse-submodules https://github.com/matr1xp/hermes-agent.git
cd hermes-agent

# Install with uv (fast Python package manager)
uv venv venv --python 3.11
source venv/bin/activate
uv pip install -e ".[all,dev]"
uv pip install -e "./mini-swe-agent"
uv pip install -e "./tinker-atropos"  # RL training only

# Run tests
python -m pytest tests/ -q
```

## Common Commands

```bash
# Run all tests (~3000 tests, ~3 min)
python -m pytest tests/ -q

# Run specific test files
python -m pytest tests/test_model_tools.py -q    # Toolset resolution
python -m pytest tests/test_cli_init.py -q       # CLI config loading
python -m pytest tests/gateway/ -q               # Gateway tests
python -m pytest tests/tools/ -q                 # Tool tests

# Run agent locally
hermes                          # Interactive CLI
hermes setup                    # Full setup wizard
hermes gateway start            # Start messaging gateway
```

## Architecture Overview

### Core Agent Loop (`run_agent.py`)

The `AIAgent` class runs the conversation loop:

1. Build system prompt (prompt_builder.py)
2. Call LLM via OpenAI-compatible API
3. Execute tool calls via registry dispatch
4. Loop until text response or max iterations

```
User message → AIAgent._run_agent_loop()
  → Build system prompt (prompt_builder.py)
  → Call LLM (OpenAI-compatible API)
  → If tool_calls: execute via registry → loop
  → If text: persist session → return
```

### File Dependency Chain

```
tools/registry.py         # Central registry (no deps)
       ↑
tools/*.py                # Self-registering tools
       ↑
model_tools.py            # Orchestration layer
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

### Key Components

| File                     | Purpose                                                           |
| ------------------------ | ----------------------------------------------------------------- |
| `run_agent.py`           | `AIAgent` class — core conversation loop, tool dispatch           |
| `model_tools.py`         | Tool orchestration, `_discover_tools()`, `handle_function_call()` |
| `toolsets.py`            | Tool groupings (`_HERMES_CORE_TOOLS`, platform presets)           |
| `tools/registry.py`      | Central tool registry (schemas, handlers, dispatch)               |
| `cli.py`                 | `HermesCLI` class — interactive TUI, prompt_toolkit               |
| `hermes_state.py`        | SQLite session DB with FTS5 search                                |
| `hermes_cli/main.py`     | Entry point — all `hermes` subcommands                            |
| `hermes_cli/commands.py` | Central slash command registry (`COMMAND_REGISTRY`)               |
| `gateway/run.py`         | Messaging gateway lifecycle, slash commands, cron                 |

### User Configuration

Stored in `~/.hermes/`:

- `config.yaml` — Settings (model, toolsets, compression, etc.)
- `.env` — API keys
- `skills/` — Active skills
- `state.db` — SQLite session database
- `sessions/` — JSON session logs

## Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `hermes_cli/commands.py`:

```python
CommandDef("mycommand", "Description", "Session", aliases=("mc",), args_hint="[arg]")
```

1. Add handler in `HermesCLI.process_command()` in `cli.py`:

```python
elif canonical == "mycommand":
    self._handle_mycommand(cmd_original)
```

1. If gateway-accessible, add handler in `gateway/run.py`

## Adding a Tool

1. Create `tools/your_tool.py`:

```python
from tools.registry import registry

def your_tool(param: str, **kwargs) -> str:
    result = do_work(param)
    return json.dumps(result)

registry.register(
    name="your_tool",
    toolset="your_toolset",
    schema={...},
    handler=lambda args, **kw: your_tool(**args, **kw),
    check_fn=check_requirements,
)
```

1. Add import to `model_tools.py` `_modules` list
2. Add to `toolsets.py` `_HERMES_CORE_TOOLS` or a toolset

## Adding a Skill

Skills live in `skills/<category>/<name>/`:

```
skills/research/arxiv/
├── SKILL.md          # Main instructions (required)
└── scripts/          # Helper scripts (optional)
```

### SKILL.md Frontmatter

```yaml
---
name: my-skill
description: Brief description
version: 1.0.0
platforms: [macos, linux] # Optional — hide on other platforms
required_environment_variables: # Optional — secure setup-on-load
  - name: MY_API_KEY
    prompt: API key
    required_for: full functionality
metadata:
  hermes:
    fallback_for_toolsets: [web] # Show when unavailable
    requires_toolsets: [terminal] # Show when available
---
```

## Skin/Theme System

Skins are data-driven YAML files in `~/.hermes/skins/<name>.yaml`:

```yaml
name: mytheme
colors:
  banner_border: "#HEX"
  response_border: "#HEX"
spinner:
  thinking_verbs: ["forging", "plotting"]
branding:
  agent_name: "My Agent"
```

Activate with `/skin mytheme` or `display.skin: mytheme` in config.yaml.

## Critical Policies

### Prompt Caching

Do NOT break prompt caching:

- Never alter past context mid-conversation
- Never change toolsets mid-conversation
- Never reload memories mid-conversation
  Cache-breaking forces full context rebuild → higher costs.

### Working Directory

- **CLI**: Uses `.` (current directory)
- **Messaging**: Uses `MESSAGING_CWD` env var (default: home)

### Tool Handlers

All tool handlers MUST return a JSON string.

### Cross-Platform Rules

- `termios`/`fcntl` are Unix-only — catch `ImportError` and `NotImplementedError`
- Use `pathlib.Path` for paths
- Use `shlex.quote()` for shell interpolation
- Windows `.env` may be `cp1252` — handle encoding errors

### Security

- Always use `shlex.quote()` when interpolating user input into shell commands
- Resolve symlinks with `os.path.realpath()` before access control
- Don't log secrets (API keys, tokens, passwords)
- Tests must not write to `~/.hermes/` (uses `_isolate_hermes_home` fixture)

## Known Pitfalls

1. **`simple_term_menu`** — rendering bugs in tmux/iTerm2. Use `curses` pattern from `hermes_cli/tools_config.py`.

2. **`\033[K` ANSI escape** — leaks under `prompt_toolkit`. Use space-padding: `f"\r{line}{' ' * pad}"`.

3. **`_last_resolved_tool_names`** — process-global in `model_tools.py`. Subagent code saves/restores it.

4. **Tool schema descriptions** — don't hardcode cross-tool references. Tools may be unavailable. Add cross-refs dynamically in `model_tools.get_tool_definitions()`.

## Testing

```bash
source venv/bin/activate
python -m pytest tests/ -q          # Full suite (~3000 tests)
python -m pytest tests/test_model_tools.py -q   # Toolset resolution
python -m pytest tests/test_cli_init.py -q       # CLI config loading
python -m pytest tests/gateway/ -q               # Gateway tests
python -m pytest tests/tools/ -q                 # Tool tests
```

## Documentation

Full docs: [hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)
