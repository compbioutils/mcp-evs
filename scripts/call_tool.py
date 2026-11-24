#!/usr/bin/env python
"""Call any MCP tool directly and print the response envelope (no LLM involved).

Use this to reproduce or debug a single call an agent made, or to explore the tools.

    python scripts/call_tool.py --list
    python scripts/call_tool.py --describe evs_lookup_concept
    python scripts/call_tool.py evs_lookup_concept '{"identifier": "non-small cell lung carcinoma"}'
    python scripts/call_tool.py evs_get_paths '{"code": "C2926", "kind": "toRoot"}'
    python scripts/call_tool.py evs_get_concept code=C2926 include=summary,parents
    python scripts/call_tool.py evs_get_concept code=C2926 'include=["summary","parents"]'
    python scripts/call_tool.py --mode fixtures evs_lookup_concept identifier=NSCLC

Arguments are either one JSON object or key=value pairs; a value that parses as JSON is
used as JSON, otherwise as a string. For a list argument (such as ``include``), a plain
word or comma-separated words become a list. In zsh, quote any value containing ``[``.
Default mode spawns the server over stdio; see
``--mode`` for fixtures / live / http. Exit status: 0 on success, 1 on a tool error,
2 on a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mcp_target import add_target_args, call, error_payload, open_client  # noqa: E402


def parse_args_list(items: list[str]) -> dict[str, Any]:
    if len(items) == 1 and items[0].lstrip().startswith("{"):
        obj = json.loads(items[0])
        if not isinstance(obj, dict):
            raise ValueError("JSON arguments must be an object")
        return obj
    out: dict[str, Any] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise ValueError(f"expected key=value, got {item!r}")
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw
    return out


def _schema_types(prop: dict[str, Any]) -> set[str]:
    types = {prop["type"]} if isinstance(prop.get("type"), str) else set(prop.get("type") or [])
    for option in prop.get("anyOf", []) + prop.get("oneOf", []):
        types |= _schema_types(option)
    return types


def coerce_list_args(tool_args: dict[str, Any], input_schema: dict[str, Any]) -> dict[str, Any]:
    """Turn ``include=summary,parents`` into a list where the tool expects a list, not a string."""
    props = input_schema.get("properties", {})
    out = dict(tool_args)
    for key, value in tool_args.items():
        types = _schema_types(props.get(key, {}))
        if isinstance(value, str) and "array" in types and "string" not in types:
            out[key] = [part.strip() for part in value.split(",") if part.strip()]
    return out


async def run(args, tool_args: dict[str, Any]) -> int:
    async with open_client(args.mode, profile=args.profile, url=args.url, python=args.python) as client:
        tools = await client.list_tools()
        if args.list or args.describe:
            if args.list:
                for t in sorted(tools, key=lambda t: t.name):
                    first = ((t.description or "").strip().splitlines() or [""])[0]
                    print(f"{t.name:<34} {first}")
                return 0
            match = next((t for t in tools if t.name == args.describe), None)
            if match is None:
                print(f"no tool named {args.describe!r}", file=sys.stderr)
                return 2
            print(json.dumps({"name": match.name, "title": match.title, "description": match.description,
                              "inputSchema": match.inputSchema}, indent=2, default=str))
            return 0
        match = next((t for t in tools if t.name == args.tool), None)
        if match is not None:
            tool_args = coerce_list_args(tool_args, match.inputSchema or {})
        try:
            env = await call(client, args.tool, tool_args)
        except Exception as e:  # ToolError: message is the server's JSON error envelope
            print(f"{type(e).__name__}:", file=sys.stderr)
            print(json.dumps(error_payload(e), indent=2, default=str))
            return 1
        print(json.dumps(env, indent=2, default=str))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_target_args(parser)
    parser.add_argument("--list", action="store_true", help="list the tools and exit")
    parser.add_argument("--describe", metavar="TOOL", help="print one tool's description and input schema")
    parser.add_argument("tool", nargs="?", help="tool name, e.g. evs_lookup_concept")
    parser.add_argument("arguments", nargs="*", help="one JSON object, or key=value pairs")
    args = parser.parse_args(argv)

    if not (args.list or args.describe or args.tool):
        parser.error("give a tool name, --list or --describe TOOL")
    try:
        tool_args = parse_args_list(args.arguments) if args.tool else {}
    except ValueError as e:
        parser.error(str(e))
    return asyncio.run(run(args, tool_args))


if __name__ == "__main__":
    raise SystemExit(main())
