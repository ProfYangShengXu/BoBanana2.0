# Drop-in tool plugins (`.bobanana/tools/`)

BoBanana loads **extra executor tools** from this directory at runtime.

## Do NOT confuse with

- `bobanana/tools/` — **Python package** (core registry code)
- This folder — **your workspace data** (plugins you add)

## How to discover tools (for humans and agents)

1. In the REPL: `/tools` or ask the agent to call **`describe_tool_registry`**
2. Terminal: `python -m bobanana --selfcheck` (shows registry path + plugin load status)
3. **Do not** infer the registry by running `dir .bobanana\tools` alone — that only lists files here.

## File types

| File | Purpose |
|------|---------|
| `*.yaml` | Declarative manifest (`handler: echo` or `handler: shell`) |
| `*.py` | Python plugin using `@register_tool` from `bobanana.tools` |

After adding/editing files, run `/reload-tools` in the REPL or restart the agent.

## YAML manifest (semver + permissions)

```yaml
name: my_ping
version: 1.0.0
description: Health-check plugin
permissions:
  - read
handler: echo
message: "pong from {name} v{version}"
parameters:
  name:
    type: string
    default: bobanana
```

Shell example:

```yaml
name: py_version
version: 1.0.0
description: Print Python version in workspace
permissions:
  - shell
handler: shell
command: "python --version"
```

## Python plugin

See `example_greet.py` in this folder.

## Permissions

| Permission | Meaning |
|------------|---------|
| `read` | Read/list files, pure info |
| `write` | Write workspace files |
| `shell` | Run allowlisted shell commands |
| `network` | HTTP / git / web |
| `admin` | Elevated (load skill repos) |

Configure grants via env: `BOBANANA_TOOL_PERMISSIONS=read,write,shell,network`

## Versioning

Every tool must declare semver `MAJOR.MINOR.PATCH` in YAML or `@register_tool(version=...)`.
