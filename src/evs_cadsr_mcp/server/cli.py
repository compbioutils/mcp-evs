"""Command-line entry point: ``evs-cadsr-mcp serve --transport stdio|http``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ..core.config import get_settings
from .mcp_app import build_mcp_server, configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evs-cadsr-mcp", description="EVS + caDSR MCP server (prototype)")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--profile", choices=["evs-only", "cadsr-only", "unified"], default=None)
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    sub.add_parser("tools", help="print the tool list as JSON and exit")
    sub.add_parser("releases", help="print the live NCIt releases and exit")

    icdo = sub.add_parser("icdo", help="EVS ICD-O-3.1 mapping files used by map_map_icdo_to_ncit")
    icdo.add_argument("action", choices=["sync", "status"])
    icdo.add_argument("--force", action="store_true", help="download every file even if EVS reports no change")
    icdo.add_argument("--from-dir", default=None, help="install files copied by hand (offline hosts) instead of downloading")

    base = sub.add_parser("baseline", help="interface baseline (SOW-S16): export the frozen contract or check drift against it")
    base.add_argument("action", choices=["export", "check"])
    base.add_argument("--root", default="spec/interface-baseline", help="baseline root directory")
    base.add_argument("--fixtures", default="tests/fixtures", help="fixture root for the conformance-mock manifest (export)")

    args = parser.parse_args(argv)
    settings = get_settings()
    if getattr(args, "profile", None):
        settings = settings.model_copy(update={"profile": args.profile})
    if getattr(args, "host", None):
        settings = settings.model_copy(update={"http_host": args.host})
    if getattr(args, "port", None):
        settings = settings.model_copy(update={"http_port": args.port})
    configure_logging(settings)

    if args.command == "serve":
        if args.transport == "stdio":
            if settings.audit_sink == "stdout":
                parser.error("ECM_AUDIT_SINK=stdout would corrupt the stdio MCP stream; use stderr or a file path")
            mcp, _ = build_mcp_server(settings)
            mcp.run(transport="stdio")
            return 0
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(settings), host=settings.http_host, port=settings.http_port, log_level=settings.log_level.lower())
        return 0

    if args.command == "icdo":
        from pathlib import Path

        from ..map.icdo_map import IcdoMapStore
        from ..map.icdo_sync import IcdoSyncer

        if args.action == "status":
            json.dump(IcdoMapStore.from_settings(settings).status(), sys.stdout, indent=2)
            print()
            return 0
        syncer = IcdoSyncer.from_settings(settings)
        if args.from_dir:
            result = syncer.install_from_dir(Path(args.from_dir).expanduser())
        else:
            result = asyncio.run(syncer.sync(force=args.force))
        json.dump({**result.to_dict(), "cacheDir": str(syncer.cache_dir)}, sys.stdout, indent=2)
        print()
        return 1 if result.status in ("failed", "busy") else 0

    if args.command == "tools":
        mcp, services = build_mcp_server(settings)

        async def _list():
            try:
                tools = await mcp.get_tools()
                return [{"name": t.name, "description": (t.description or "").split("\n")[0]} for t in tools.values()]
            finally:
                await services.aclose()

        json.dump(asyncio.run(_list()), sys.stdout, indent=2)
        print()
        return 0

    if args.command == "releases":
        _, services = build_mcp_server(settings)

        async def _rel():
            try:
                live = await services.registry.live_releases(settings.default_terminology)
                active = await services.registry.active_release(settings.default_terminology)
                return {"active": active.version, "live": [r.version for r in live]}
            finally:
                await services.aclose()

        json.dump(asyncio.run(_rel()), sys.stdout, indent=2)
        print()
        return 0

    if args.command == "baseline":
        from pathlib import Path

        from .. import INTERFACE_VERSION
        from .baseline import (
            collect_all,
            compare,
            conformance_mock_manifest,
            read_baseline,
            write_baseline,
        )

        root = Path(args.root)
        snapshot = asyncio.run(collect_all())
        if args.action == "export":
            out = write_baseline(snapshot, root)
            mock = conformance_mock_manifest(Path(args.fixtures))
            (out / "conformance-mock.json").write_text(json.dumps(mock, indent=2, sort_keys=True) + "\n")
            n_tools = sum(len(p["tools"]) for p in snapshot["profiles"].values())
            print(f"wrote interface baseline v{INTERFACE_VERSION} to {out} ({n_tools} tool schemas across {len(snapshot['profiles'])} profiles)")
            return 0
        baseline = read_baseline(root, INTERFACE_VERSION)
        if baseline is None:
            print(f"no baseline found under {root}/v{INTERFACE_VERSION}; run `evs-cadsr-mcp baseline export` to freeze one", file=sys.stderr)
            return 3
        drift = compare(baseline, snapshot)
        print(drift.summary())
        return 0 if drift.ok else 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
