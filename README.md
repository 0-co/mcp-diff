# mcp-diff

Schema lockfile and breaking-change detector for MCP servers.

**The problem:** MCP servers serve tool schemas at runtime. When a description changes, agent behavior changes silently — no diff, no CI failure, no warning.

**The solution:** Commit a `mcp-schema.lock` to git. Fail CI on breaking changes.

## Install

```bash
pip install mcp-diff
```

## Usage

```bash
# Snapshot your server's current schema
mcp-diff snapshot python3 my_server.py

# Check for breaking changes (exits 1 if found)
mcp-diff check python3 my_server.py

# Human-readable report (always exits 0)
mcp-diff report python3 my_server.py
```

## Example output

```
mcp-diff check python3 my_server.py

[BREAKING]  read_file: Tool 'read_file' was removed.
[BREAKING]  search_files.pattern: Parameter 'pattern' type changed: 'string' → 'array' in tool 'search_files'.
[WARNING]   search_files: Tool description changed.
              was: 'Search for files matching a pattern.'
              now: 'Search files. Use glob patterns.'
[INFO]      write_file: Tool 'write_file' was added.

Found 2 breaking, 1 warning, 1 info changes.
```

## Change severity

| Severity | When | CI impact |
|---|---|---|
| **breaking** | Tool removed, required param added/removed, param type changed | exits 1 |
| **warning** | Tool or param description changed (descriptions are behavioral contracts for LLMs) | exits 0 |
| **info** | Tool added, optional param added | exits 0 |

## CI integration (GitHub Actions)

```yaml
- name: Snapshot MCP schema
  run: mcp-diff snapshot python3 my_server.py
  # Commit mcp-schema.lock to your repo

- name: Check for breaking changes
  run: mcp-diff check python3 my_server.py
  # Exits 1 and fails the build if breaking changes are detected
```

## Lockfile format

```json
{
  "version": "1",
  "created_at": "2026-03-22T03:00:00Z",
  "command": "python3 my_server.py",
  "tools": [
    {
      "name": "search_files",
      "description": "Search for files matching a pattern",
      "inputSchema": { "..." : "..." }
    }
  ]
}
```

Commit `mcp-schema.lock` to git. The diff in your PR is the schema diff.

## Options

```
mcp-diff snapshot [--output PATH] <command...>
mcp-diff check    [--lockfile PATH] [--json] [--no-color] <command...>
mcp-diff report   [--lockfile PATH] [--no-color] <command...>
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Clean (no breaking changes) |
| 1 | Breaking changes detected |
| 2 | Error (missing lockfile, server failed to start) |

## Part of the MCP developer toolkit

- [agent-friend](https://github.com/0-co/agent-friend) — schema quality linter
- [mcp-patch](https://github.com/0-co/mcp-patch) — AST security scanner
- [mcp-pytest](https://github.com/0-co/mcp-test) — testing framework
- [mcp-snoop](https://github.com/0-co/mcp-snoop) — stdio debugger
- **mcp-diff** — schema lockfile and breaking-change detector

Source: [github.com/0-co/mcp-diff](https://github.com/0-co/mcp-diff)
