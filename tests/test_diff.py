"""Tests for mcp-diff — minimal stdlib test runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# Make sure the package is importable from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_diff.diff import (
    Change,
    SEVERITY_BREAKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    classify_changes,
    deserialize_lockfile,
    format_changes_json,
    format_changes_text,
    has_breaking,
    serialize_lockfile,
)
from mcp_diff.cli import build_parser, DEFAULT_LOCKFILE

# ---------------------------------------------------------------------------
# Minimal test runner
# ---------------------------------------------------------------------------

_TESTS: list[tuple[str, callable]] = []
_PASSED = 0
_FAILED = 0


def test(fn):
    """Decorator: register a test function."""
    _TESTS.append((fn.__name__, fn))
    return fn


def run_all():
    global _PASSED, _FAILED
    for name, fn in _TESTS:
        try:
            fn()
            print(f"  PASS  {name}")
            _PASSED += 1
        except AssertionError as exc:
            print(f"  FAIL  {name}: {exc}")
            _FAILED += 1
        except Exception as exc:
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
            _FAILED += 1
    print(f"\n{_PASSED} passed, {_FAILED} failed out of {len(_TESTS)} tests.")
    return _FAILED == 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOOL_SEARCH = {
    "name": "search_files",
    "description": "Search for files matching a pattern.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match."},
            "max_results": {"type": "integer", "description": "Maximum results.", "default": 50},
        },
        "required": ["pattern"],
    },
}

TOOL_READ = {
    "name": "read_file",
    "description": "Read a file from disk.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
        },
        "required": ["path"],
    },
}

TOOL_WRITE = {
    "name": "write_file",
    "description": "Write content to a file.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path."},
            "content": {"type": "string", "description": "Content to write."},
        },
        "required": ["path", "content"],
    },
}

TOOL_NO_PARAMS = {
    "name": "get_version",
    "description": "Return the server version.",
    "inputSchema": {"type": "object", "properties": {}},
}


# ---------------------------------------------------------------------------
# Tests: classify_changes — tool-level
# ---------------------------------------------------------------------------

@test
def test_no_changes():
    tools = [TOOL_SEARCH, TOOL_READ]
    changes = classify_changes(tools, tools)
    assert changes == [], f"Expected no changes, got {changes}"


@test
def test_tool_removed_is_breaking():
    old = [TOOL_SEARCH, TOOL_READ]
    new = [TOOL_SEARCH]
    changes = classify_changes(old, new)
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "removed"
    assert c.tool == "read_file"
    assert c.severity == SEVERITY_BREAKING
    assert c.param is None


@test
def test_tool_added_is_info():
    old = [TOOL_SEARCH]
    new = [TOOL_SEARCH, TOOL_READ]
    changes = classify_changes(old, new)
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "added"
    assert c.tool == "read_file"
    assert c.severity == SEVERITY_INFO


@test
def test_tool_description_changed_is_warning():
    old_tool = dict(TOOL_SEARCH, description="Old description.")
    new_tool = dict(TOOL_SEARCH, description="New description.")
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "description_changed"
    assert c.severity == SEVERITY_WARNING
    assert c.param is None
    assert "Old description." in c.detail
    assert "New description." in c.detail


@test
def test_empty_tool_lists():
    changes = classify_changes([], [])
    assert changes == []


@test
def test_all_tools_removed():
    old = [TOOL_SEARCH, TOOL_READ, TOOL_WRITE]
    changes = classify_changes(old, [])
    assert len(changes) == 3
    assert all(c.kind == "removed" for c in changes)
    assert all(c.severity == SEVERITY_BREAKING for c in changes)


@test
def test_all_tools_added():
    new = [TOOL_SEARCH, TOOL_READ, TOOL_WRITE]
    changes = classify_changes([], new)
    assert len(changes) == 3
    assert all(c.kind == "added" for c in changes)
    assert all(c.severity == SEVERITY_INFO for c in changes)


# ---------------------------------------------------------------------------
# Tests: classify_changes — param-level
# ---------------------------------------------------------------------------

@test
def test_required_param_added_is_breaking():
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
            },
            "required": ["a", "b"],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "param_added_required"
    assert c.param == "b"
    assert c.severity == SEVERITY_BREAKING


@test
def test_optional_param_added_is_info():
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},  # optional (not in required)
            },
            "required": ["a"],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "param_added_optional"
    assert c.param == "b"
    assert c.severity == SEVERITY_INFO


@test
def test_param_removed_is_breaking():
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
            },
            "required": ["a"],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "param_removed"
    assert c.param == "b"
    assert c.severity == SEVERITY_BREAKING


@test
def test_param_type_changed_is_breaking():
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"count": {"type": "string"}},
            "required": [],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": [],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "param_type_changed"
    assert c.param == "count"
    assert c.severity == SEVERITY_BREAKING
    assert "string" in c.detail
    assert "integer" in c.detail


@test
def test_param_description_changed_is_warning():
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path."},
            },
            "required": ["path"],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path."},
            },
            "required": ["path"],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "param_description_changed"
    assert c.severity == SEVERITY_WARNING
    assert c.param == "path"


@test
def test_tool_no_params_no_change():
    changes = classify_changes([TOOL_NO_PARAMS], [TOOL_NO_PARAMS])
    assert changes == []


# ---------------------------------------------------------------------------
# Tests: severity ordering
# ---------------------------------------------------------------------------

@test
def test_changes_sorted_breaking_first():
    old = [TOOL_SEARCH, TOOL_READ]
    # remove read_file (breaking) and change search description (warning)
    new_search = dict(TOOL_SEARCH, description="Updated description.")
    changes = classify_changes(old, [new_search])
    assert changes[0].severity == SEVERITY_BREAKING
    assert changes[1].severity == SEVERITY_WARNING


@test
def test_has_breaking_true():
    old = [TOOL_SEARCH, TOOL_READ]
    new = [TOOL_SEARCH]
    changes = classify_changes(old, new)
    assert has_breaking(changes) is True


@test
def test_has_breaking_false():
    old = [TOOL_SEARCH]
    new_search = dict(TOOL_SEARCH, description="Updated.")
    changes = classify_changes(old, [new_search])
    assert has_breaking(changes) is False


# ---------------------------------------------------------------------------
# Tests: lockfile serialization
# ---------------------------------------------------------------------------

@test
def test_serialize_lockfile_structure():
    tools = [TOOL_SEARCH, TOOL_READ]
    lock = serialize_lockfile(tools, ["python3", "my_server.py"])
    assert lock["version"] == "1"
    assert "created_at" in lock
    assert lock["command"] == "python3 my_server.py"
    assert len(lock["tools"]) == 2
    # Tools should be sorted by name
    assert lock["tools"][0]["name"] == "read_file"
    assert lock["tools"][1]["name"] == "search_files"


@test
def test_deserialize_lockfile():
    tools = [TOOL_SEARCH, TOOL_READ]
    lock = serialize_lockfile(tools, ["python3", "server.py"])
    recovered = deserialize_lockfile(lock)
    assert len(recovered) == 2
    names = {t["name"] for t in recovered}
    assert "search_files" in names
    assert "read_file" in names


@test
def test_lockfile_roundtrip_no_changes():
    tools = [TOOL_SEARCH, TOOL_READ, TOOL_WRITE]
    lock = serialize_lockfile(tools, ["python3", "server.py"])
    recovered = deserialize_lockfile(lock)
    changes = classify_changes(recovered, tools)
    assert changes == [], f"Expected no changes after roundtrip, got {changes}"


# ---------------------------------------------------------------------------
# Tests: formatting
# ---------------------------------------------------------------------------

@test
def test_format_changes_text_no_color():
    old = [TOOL_SEARCH, TOOL_READ]
    new = [TOOL_SEARCH]
    changes = classify_changes(old, new)
    text = format_changes_text(changes, color=False)
    assert "[BREAKING]" in text
    assert "read_file" in text
    assert "\033[" not in text  # no ANSI codes


@test
def test_format_changes_json():
    old = [TOOL_SEARCH, TOOL_READ]
    new = [TOOL_SEARCH]
    changes = classify_changes(old, new)
    output = format_changes_json(changes)
    parsed = json.loads(output)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["kind"] == "removed"
    assert parsed[0]["tool"] == "read_file"
    assert parsed[0]["severity"] == "breaking"


@test
def test_format_no_changes_text():
    text = format_changes_text([], color=False)
    assert "No changes" in text


# ---------------------------------------------------------------------------
# Tests: CLI argument parsing
# ---------------------------------------------------------------------------

@test
def test_cli_snapshot_parses_command():
    parser = build_parser()
    args = parser.parse_args(["snapshot", "python3", "server.py"])
    assert args.subcommand == "snapshot"
    assert args.command == ["python3", "server.py"]
    assert args.output is None


@test
def test_cli_snapshot_output_flag():
    parser = build_parser()
    args = parser.parse_args(["snapshot", "--output", "custom.lock", "python3", "server.py"])
    assert args.output == "custom.lock"
    assert args.command == ["python3", "server.py"]


@test
def test_cli_check_parses_lockfile_flag():
    parser = build_parser()
    args = parser.parse_args(["check", "--lockfile", "my.lock", "python3", "server.py"])
    assert args.subcommand == "check"
    assert args.lockfile == "my.lock"
    assert args.command == ["python3", "server.py"]
    assert args.json is False
    assert args.no_color is False


@test
def test_cli_check_json_flag():
    parser = build_parser()
    args = parser.parse_args(["check", "--json", "python3", "server.py"])
    assert args.json is True


@test
def test_cli_report_parses_command():
    parser = build_parser()
    args = parser.parse_args(["report", "uvx", "my-server"])
    assert args.subcommand == "report"
    assert args.command == ["uvx", "my-server"]


@test
def test_cli_no_color_flag():
    parser = build_parser()
    args = parser.parse_args(["check", "--no-color", "python3", "server.py"])
    assert args.no_color is True


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

@test
def test_nested_object_param_no_crash():
    """Tools with nested object schemas should not crash the differ."""
    tool = {
        "name": "complex_tool",
        "description": "Has nested params.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "description": "Config object.",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                }
            },
            "required": ["config"],
        },
    }
    changes = classify_changes([tool], [tool])
    assert changes == []


@test
def test_multiple_changes_same_tool():
    """Multiple param changes on one tool should all be reported."""
    old_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "Old A desc."},
                "b": {"type": "string"},
            },
            "required": ["a"],
        },
    }
    new_tool = {
        "name": "my_tool",
        "description": "A tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "New A desc."},
                # b removed
                "c": {"type": "integer"},  # new optional
            },
            "required": ["a"],
        },
    }
    changes = classify_changes([old_tool], [new_tool])
    kinds = {c.kind for c in changes}
    assert "param_removed" in kinds        # b removed — breaking
    assert "param_description_changed" in kinds  # a desc — warning
    assert "param_added_optional" in kinds  # c added — info


@test
def test_schema_missing_inputschema():
    """Tools with no inputSchema should not crash."""
    tool = {"name": "bare_tool", "description": "No schema."}
    changes = classify_changes([tool], [tool])
    assert changes == []


@test
def test_lockfile_empty_tools():
    lock = serialize_lockfile([], ["python3", "server.py"])
    recovered = deserialize_lockfile(lock)
    assert recovered == []
    changes = classify_changes(recovered, [])
    assert changes == []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Running {len(_TESTS)} tests...\n")
    ok = run_all()
    sys.exit(0 if ok else 1)
