"""Schema diff engine for mcp-diff."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


SEVERITY_BREAKING = "breaking"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass
class Change:
    """Represents a single detected change between two schemas."""

    kind: str
    """
    One of: 'removed', 'added', 'description_changed',
    'param_added_required', 'param_removed', 'param_type_changed',
    'param_description_changed', 'param_added_optional'.
    """
    tool: str
    """The tool name this change applies to."""
    param: str | None
    """Param name, or None for tool-level changes."""
    severity: str
    """One of: 'breaking', 'warning', 'info'."""
    detail: str
    """Human-readable description of the change."""


def _normalize_tool(tool: dict) -> dict:
    """Return a canonical dict for comparison (sorted keys, stable repr)."""
    return {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {}),
    }


def _get_params(tool: dict) -> dict[str, dict]:
    """Extract parameters from a tool's inputSchema as {name: schema}."""
    schema = tool.get("inputSchema", {})
    props = schema.get("properties", {})
    return {k: dict(v) for k, v in sorted(props.items())}


def _get_required(tool: dict) -> set[str]:
    """Return the set of required param names for a tool."""
    schema = tool.get("inputSchema", {})
    return set(schema.get("required", []))


def classify_changes(old_tools: list[dict], new_tools: list[dict]) -> list[Change]:
    """Compare two lists of MCP tool schemas and return all detected changes.

    Args:
        old_tools: Tool list from the lockfile (baseline).
        new_tools: Tool list from the live server (current).

    Returns:
        List of Change objects sorted by severity then tool name.
    """
    changes: list[Change] = []

    old_map = {t["name"]: _normalize_tool(t) for t in old_tools}
    new_map = {t["name"]: _normalize_tool(t) for t in new_tools}

    old_names = set(old_map)
    new_names = set(new_map)

    # Removed tools — breaking
    for name in sorted(old_names - new_names):
        changes.append(Change(
            kind="removed",
            tool=name,
            param=None,
            severity=SEVERITY_BREAKING,
            detail=f"Tool '{name}' was removed.",
        ))

    # Added tools — info
    for name in sorted(new_names - old_names):
        changes.append(Change(
            kind="added",
            tool=name,
            param=None,
            severity=SEVERITY_INFO,
            detail=f"Tool '{name}' was added.",
        ))

    # Changed tools — inspect each shared tool
    for name in sorted(old_names & new_names):
        old_tool = old_map[name]
        new_tool = new_map[name]

        # Description changed — warning (description IS the behavioral contract)
        old_desc = old_tool.get("description", "")
        new_desc = new_tool.get("description", "")
        if old_desc != new_desc:
            changes.append(Change(
                kind="description_changed",
                tool=name,
                param=None,
                severity=SEVERITY_WARNING,
                detail=f"Tool description changed.\n  was: {old_desc!r}\n  now: {new_desc!r}",
            ))

        # Param-level diff
        old_params = _get_params(old_tool)
        new_params = _get_params(new_tool)
        old_required = _get_required(old_tool)
        new_required = _get_required(new_tool)

        old_param_names = set(old_params)
        new_param_names = set(new_params)

        # Removed params — breaking
        for pname in sorted(old_param_names - new_param_names):
            changes.append(Change(
                kind="param_removed",
                tool=name,
                param=pname,
                severity=SEVERITY_BREAKING,
                detail=f"Parameter '{pname}' was removed from tool '{name}'.",
            ))

        # Added params
        for pname in sorted(new_param_names - old_param_names):
            if pname in new_required:
                # New required param — breaking (callers must now supply it)
                changes.append(Change(
                    kind="param_added_required",
                    tool=name,
                    param=pname,
                    severity=SEVERITY_BREAKING,
                    detail=(
                        f"Required parameter '{pname}' was added to tool '{name}'. "
                        "Existing callers will now fail."
                    ),
                ))
            else:
                changes.append(Change(
                    kind="param_added_optional",
                    tool=name,
                    param=pname,
                    severity=SEVERITY_INFO,
                    detail=f"Optional parameter '{pname}' was added to tool '{name}'.",
                ))

        # Changed params
        for pname in sorted(old_param_names & new_param_names):
            old_p = old_params[pname]
            new_p = new_params[pname]

            # Type changed — breaking
            old_type = old_p.get("type")
            new_type = new_p.get("type")
            if old_type != new_type:
                changes.append(Change(
                    kind="param_type_changed",
                    tool=name,
                    param=pname,
                    severity=SEVERITY_BREAKING,
                    detail=(
                        f"Parameter '{pname}' type changed: {old_type!r} → {new_type!r} "
                        f"in tool '{name}'."
                    ),
                ))

            # Description changed — warning
            old_pdesc = old_p.get("description", "")
            new_pdesc = new_p.get("description", "")
            if old_pdesc != new_pdesc:
                changes.append(Change(
                    kind="param_description_changed",
                    tool=name,
                    param=pname,
                    severity=SEVERITY_WARNING,
                    detail=(
                        f"Parameter '{pname}' description changed in tool '{name}'.\n"
                        f"  was: {old_pdesc!r}\n  now: {new_pdesc!r}"
                    ),
                ))

    # Sort: breaking first, then warning, then info; then by tool name
    severity_order = {SEVERITY_BREAKING: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}
    changes.sort(key=lambda c: (severity_order.get(c.severity, 9), c.tool, c.param or ""))
    return changes


def has_breaking(changes: list[Change]) -> bool:
    """Return True if any change is severity 'breaking'."""
    return any(c.severity == SEVERITY_BREAKING for c in changes)


def serialize_lockfile(tools: list[dict], command: list[str]) -> dict:
    """Build the lockfile dict from a tool list."""
    import datetime
    return {
        "version": "1",
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "command": " ".join(command),
        "tools": [_normalize_tool(t) for t in sorted(tools, key=lambda t: t.get("name", ""))],
    }


def deserialize_lockfile(data: dict) -> list[dict]:
    """Extract tool list from a parsed lockfile dict."""
    return data.get("tools", [])


def format_changes_text(changes: list[Change], color: bool = True) -> str:
    """Format changes as human-readable colored text."""
    if not changes:
        return _c("No changes detected.", "\033[32m", color)

    lines = []
    for c in changes:
        if c.severity == SEVERITY_BREAKING:
            prefix = _c("[BREAKING]", "\033[31m", color)
        elif c.severity == SEVERITY_WARNING:
            prefix = _c("[WARNING] ", "\033[33m", color)
        else:
            prefix = _c("[INFO]    ", "\033[32m", color)

        loc = f"{c.tool}"
        if c.param:
            loc += f".{c.param}"
        lines.append(f"{prefix} {loc}: {c.detail}")

    return "\n".join(lines)


def format_changes_json(changes: list[Change]) -> str:
    """Format changes as JSON."""
    return json.dumps(
        [
            {
                "kind": c.kind,
                "tool": c.tool,
                "param": c.param,
                "severity": c.severity,
                "detail": c.detail,
            }
            for c in changes
        ],
        indent=2,
    )


def _c(text: str, code: str, color: bool) -> str:
    """Wrap text in ANSI color code if color is enabled."""
    if not color:
        return text
    return f"{code}{text}\033[0m"
