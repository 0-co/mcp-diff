"""CLI entry point for mcp-diff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .diff import (
    classify_changes,
    deserialize_lockfile,
    format_changes_json,
    format_changes_text,
    has_breaking,
    serialize_lockfile,
)

DEFAULT_LOCKFILE = "mcp-schema.lock"


def _load_lockfile(path: str) -> dict:
    """Load and parse a lockfile. Exits with code 2 on failure."""
    p = Path(path)
    if not p.exists():
        print(
            f"Error: lockfile not found: {path}\n"
            "Run 'mcp-diff snapshot <command...>' first.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        print(f"Error: invalid lockfile JSON: {exc}", file=sys.stderr)
        sys.exit(2)


def _fetch_tools(command: list[str]) -> list[dict]:
    """Start the MCP server and fetch its tool list. Exits with code 2 on failure."""
    from .client import MCPClient, MCPError

    try:
        with MCPClient(command) as client:
            return client.list_tools()
    except MCPError as exc:
        print(f"Error: failed to connect to MCP server: {exc}", file=sys.stderr)
        sys.exit(2)
    except FileNotFoundError:
        print(
            f"Error: command not found: {command[0]!r}. Check your command.",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: unexpected failure starting server: {exc}", file=sys.stderr)
        sys.exit(2)


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Snapshot the current schema to a lockfile."""
    if not args.command:
        print("Error: no command given. Usage: mcp-diff snapshot <command...>", file=sys.stderr)
        return 2

    tools = _fetch_tools(args.command)
    lockfile = serialize_lockfile(tools, args.command)

    out_path = args.output or DEFAULT_LOCKFILE
    Path(out_path).write_text(json.dumps(lockfile, indent=2) + "\n")
    print(f"Snapshot saved: {len(tools)} tool{'s' if len(tools) != 1 else ''} \u2192 {out_path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Check for breaking changes against the lockfile."""
    if not args.command:
        print("Error: no command given. Usage: mcp-diff check <command...>", file=sys.stderr)
        return 2

    lockfile_path = args.lockfile or DEFAULT_LOCKFILE
    lock_data = _load_lockfile(lockfile_path)
    old_tools = deserialize_lockfile(lock_data)

    new_tools = _fetch_tools(args.command)
    changes = classify_changes(old_tools, new_tools)

    use_color = not args.no_color and sys.stderr.isatty()

    if args.json:
        print(format_changes_json(changes))
    else:
        output = format_changes_text(changes, color=use_color)
        print(output, file=sys.stderr)

        if changes:
            breaking = [c for c in changes if c.severity == "breaking"]
            warnings = [c for c in changes if c.severity == "warning"]
            info = [c for c in changes if c.severity == "info"]
            summary_parts = []
            if breaking:
                label = "\033[31mbreaking\033[0m" if use_color else "breaking"
                summary_parts.append(f"{len(breaking)} {label}")
            if warnings:
                label = "\033[33mwarning\033[0m" if use_color else "warning"
                summary_parts.append(f"{len(warnings)} {label}")
            if info:
                label = "\033[32minfo\033[0m" if use_color else "info"
                summary_parts.append(f"{len(info)} {label}")
            print(f"\nFound {', '.join(summary_parts)} change{'s' if len(changes) != 1 else ''}.",
                  file=sys.stderr)
        else:
            ok = "\033[32mOK\033[0m" if use_color else "OK"
            print(f"{ok} No changes detected.", file=sys.stderr)

    return 1 if has_breaking(changes) else 0


def cmd_report(args: argparse.Namespace) -> int:
    """Generate a verbose report; always exits 0."""
    if not args.command:
        print("Error: no command given. Usage: mcp-diff report <command...>", file=sys.stderr)
        return 2

    lockfile_path = args.lockfile or DEFAULT_LOCKFILE
    lock_data = _load_lockfile(lockfile_path)
    old_tools = deserialize_lockfile(lock_data)

    new_tools = _fetch_tools(args.command)
    changes = classify_changes(old_tools, new_tools)

    use_color = not args.no_color and sys.stdout.isatty()

    # Header
    print("mcp-diff report")
    print("=" * 60)
    print(f"Lockfile : {lockfile_path}")
    print(f"Created  : {lock_data.get('created_at', 'unknown')}")
    print(f"Command  : {lock_data.get('command', 'unknown')}")
    print(f"Baseline : {len(old_tools)} tool{'s' if len(old_tools) != 1 else ''}")
    print(f"Current  : {len(new_tools)} tool{'s' if len(new_tools) != 1 else ''}")
    print()

    if not changes:
        ok = "\033[32m\u2713 No changes detected.\033[0m" if use_color else "OK No changes detected."
        print(ok)
        return 0

    breaking = [c for c in changes if c.severity == "breaking"]
    warnings = [c for c in changes if c.severity == "warning"]
    info = [c for c in changes if c.severity == "info"]

    if breaking:
        hdr = "\033[31mBreaking changes\033[0m" if use_color else "Breaking changes"
        print(f"{hdr} ({len(breaking)})")
        print("-" * 40)
        for c in breaking:
            loc = f"{c.tool}" + (f".{c.param}" if c.param else "")
            print(f"  [{c.kind}] {loc}")
            for line in c.detail.splitlines():
                print(f"    {line}")
        print()

    if warnings:
        hdr = "\033[33mWarnings\033[0m" if use_color else "Warnings"
        print(f"{hdr} ({len(warnings)})")
        print("-" * 40)
        for c in warnings:
            loc = f"{c.tool}" + (f".{c.param}" if c.param else "")
            print(f"  [{c.kind}] {loc}")
            for line in c.detail.splitlines():
                print(f"    {line}")
        print()

    if info:
        hdr = "\033[32mInformational\033[0m" if use_color else "Informational"
        print(f"{hdr} ({len(info)})")
        print("-" * 40)
        for c in info:
            loc = f"{c.tool}" + (f".{c.param}" if c.param else "")
            print(f"  [{c.kind}] {loc}")
            for line in c.detail.splitlines():
                print(f"    {line}")
        print()

    print("=" * 60)
    parts = []
    if breaking:
        parts.append(f"{len(breaking)} breaking")
    if warnings:
        parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
    if info:
        parts.append(f"{len(info)} info")
    print(f"Summary: {', '.join(parts)}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-diff",
        description="Schema lockfile and breaking-change detector for MCP servers.",
    )
    parser.add_argument(
        "--version", action="version", version="mcp-diff 0.1.0"
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<command>")

    # ---- snapshot ----
    snap = sub.add_parser(
        "snapshot",
        help="Snapshot an MCP server's schema to a lockfile.",
        description="Start the MCP server, fetch its tool list, and save to a lockfile.",
    )
    snap.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="command",
        help="Command to start the MCP server (e.g. python3 my_server.py).",
    )
    snap.add_argument(
        "--output", "-o",
        metavar="PATH",
        help=f"Output lockfile path (default: {DEFAULT_LOCKFILE}).",
    )

    # ---- check ----
    chk = sub.add_parser(
        "check",
        help="Check for breaking changes (exits 1 if found).",
        description=(
            "Compare the live MCP server schema against the lockfile. "
            "Exits 1 if breaking changes are found, 0 if clean."
        ),
    )
    chk.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="command",
        help="Command to start the MCP server.",
    )
    chk.add_argument(
        "--lockfile", "-l",
        metavar="PATH",
        help=f"Lockfile path (default: {DEFAULT_LOCKFILE}).",
    )
    chk.add_argument(
        "--json",
        action="store_true",
        help="Output changes as JSON to stdout.",
    )
    chk.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output.",
    )

    # ---- report ----
    rep = sub.add_parser(
        "report",
        help="Verbose change report (always exits 0).",
        description="Same as check but always exits 0 and prints a detailed report.",
    )
    rep.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="command",
        help="Command to start the MCP server.",
    )
    rep.add_argument(
        "--lockfile", "-l",
        metavar="PATH",
        help=f"Lockfile path (default: {DEFAULT_LOCKFILE}).",
    )
    rep.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "snapshot":
        sys.exit(cmd_snapshot(args))
    elif args.subcommand == "check":
        sys.exit(cmd_check(args))
    elif args.subcommand == "report":
        sys.exit(cmd_report(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
