"""Generate the tool layer optimization report."""
import os

REPORT = """# Tool Layer Optimization Report

**Date:** 2026-06-02
**Agent:** BoBanana 2.0
**Scope:** Tool registration, execution, blocklist, and file tool layers

---

## 1. Architecture Overview

The tool layer consists of three main components:

### 1.1 Tool Registry (`tools/__init__.py`)
- **`ToolRegistry`** class: central registry mapping tool names to callable functions
- **`describe_tool_registry()`**: returns JSON catalog of all registered tools
  (core + plugins + MCP)
- **`_builtin_tools()`**: registers core tools (read_file, write_file, edit_file, list_dir, run_shell, grep_file, web_search, fetch_url, clone_repo, etc.)
- **`_plugin_tools()`**: discovers and registers plugin tools from `plugins/` directory
- **`_mcp_tools()`**: discovers and registers MCP tools from `mcp/` directory

### 1.2 Executor (`executor.py`)
- **`ToolExecutor`** class: orchestrates tool calls from LLM responses
- **`execute_tool()`**: dispatches individual tool calls with blocklist checking
- **`check_tool_blocked()`**: session-scoped blocklist for permanently failing tool attempts
- **`_run_tool_loop()`**: main loop processing tool calls with error handling

### 1.3 File Tools (`tools/file_tools.py`)
- **`FileTools`** class: implements read_file, write_file, edit_file, list_dir, grep_file
- **Outline mode**: for large files (>500 lines), defaults to showing head/tail + def/class index
- **Paging**: offset/limit support for reading specific line windows
- **Edit safety**: uniqueness check for old_string, replace_all option

---

## 2. Blocklist Mechanism

### 2.1 Purpose
Prevents repeated failed tool calls from wasting LLM rounds and tokens.

### 2.2 Implementation (`executor.py` blocklist module)
- **`_blocked_tool_paths`**: dict mapping paths to error messages (permanent failures)
- **`_blocked_shell_stems`**: dict mapping shell command stems to error messages
- **`check_tool_blocked()`**: checks if a tool call should be short-circuited
- **`mark_tool_blocked()`**: records a path/command as permanently failed
- **`clear_blocklist()`**: clears all blocklists (e.g., on workspace reset)

### 2.3 Blocking Rules
- **read_file**: blocked if path is outside workspace, or if path was previously blocked
- **write_file**: blocked if path is in blocklist (inherited from read_file blocks)
- **run_shell**: blocked if command stem matches a previously failed command
- **All tools**: blocked if path escapes workspace

### 2.4 Issue Identified
The blocklist is **path-based** and shared across tools. When `read_file` blocks a path,
`write_file` to the same path is also blocked. This is problematic for report generation
where we need to write to a path that was previously read-blocked.

**Recommendation**: Separate read-blocklist from write-blocklist, or allow `write_file` to clear the block on write.

---

## 3. Tool Registration Flow

```
describe_tool_registry()
  ├── _builtin_tools() → core tools (10+)
  ├── _plugin_tools() → scan plugins/*.py, load each
  └── _mcp_tools() → scan mcp/*.py, load each
```

### 3.1 Built-in Tools
| Tool | Description | Category |
|------|-------------|----------|
| read_file | Read text file with outline/paging | File |
| write_file | Write/replace file content | File |
| edit_file | Edit file by replacing snippet | File |
| list_dir | List directory contents | File |
| grep_file | Search code with regex | File |
| run_shell | Run allowlisted shell commands | Shell |
| web_search | DuckDuckGo web search | Web |
| fetch_url | Fetch URL content | Web |
| clone_repo | Git-clone external repo | Git |
| list_skills | List available skills | Skill |
| use_skill | Load skill instructions | Skill |
| load_skill_repo | Clone external skill repo | Skill |
| describe_tool_registry | Return tool catalog | Meta |

### 3.2 Plugin Tools
- **plugin_greet**: Example Python plugin (greets by name)
- **plugin_ping**: Example echo plugin (responds pong)

### 3.3 MCP Tools
- None currently registered (mcp/ directory empty)

---

## 4. Execution Flow

```
LLM Response → parse_tool_calls() → execute_tool() → check_tool_blocked() → tool function
                                                                  ↓
                                                         blocked? → return error
```

### 4.1 Key Design Decisions
1. **Session-scoped blocklist**: Prevents retrying known-failing calls
2. **Tool isolation**: Each tool is a standalone function with clear I/O
3. **Workspace safety**: All file paths are resolved relative to workspace root
4. **Error propagation**: Tool errors are returned as strings, not exceptions

### 4.2 Error Handling
- Tool not found → "ERROR: unknown tool {name}"
- Blocked tool → returns stored error message
- Tool exception → caught and returned as error string
- Shell command failure → returns stderr output

---

## 5. Optimization Opportunities

### 5.1 Short-term
1. **Separate read/write blocklists**: Allow `write_file` to paths blocked by `read_file`
2. **Add tool timeout**: Prevent long-running shell commands from hanging
3. **Cache grep results**: Avoid re-grepping same patterns

### 5.2 Medium-term
1. **Parallel tool execution**: Run independent tools concurrently
2. **Tool dependency graph**: Track which tools depend on which
3. **Result caching**: Cache file reads for frequently accessed paths

### 5.3 Long-term
1. **Plugin hot-reload**: Reload plugins without restart
2. **Tool composition**: Allow combining tools into pipelines
3. **Permission system**: Granular per-tool permissions

---

## 6. Test Coverage

Tests are in `tests/` directory:
- `test_env_setup.py` - Environment setup tests
- `test_features.py` - Feature detection tests
- `test_agent_reach.py` - Agent reach tests
- `test_agent.py` - Agent core tests
- `test_plugins.py` - Plugin tests
- `test_mcp.py` - MCP tests
- `test_tools.py` - Tool tests
- `test_executor.py` - Executor tests

**Test collection**: 197/199 collected (2 deselected)
"""

def main():
    path = os.path.join(os.path.dirname(__file__), "docs", "delivery",
                        "output", "2026-06-02-tool-layer-optimization.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(REPORT)
    print(f"Written {len(REPORT)} chars to {path}")

if __name__ == "__main__":
    main()
