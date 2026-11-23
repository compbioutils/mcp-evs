"""Interface baseline export and drift check (proposal Section 13, SOW-S16).

The baseline is the frozen contract between this server and its clients: per profile, every
tool's name, title, description, annotations, input and output JSON Schema; resources,
resource templates and prompts; the envelope, provenance, truncation, page and error
schemas; and the closed error-code set. ``export`` writes it under
``spec/interface-baseline/<version>/`` with a manifest of SHA-256 checksums; ``compare``
classifies drift between the running server and a frozen baseline as **breaking** (tool,
argument, result field, resource, prompt or error code removed, or a schema changed in a way
that is not a pure addition) or **non-breaking** (additions, description-only changes).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import INTERFACE_VERSION, __version__
from ..core.config import Settings
from ..core.envelopes import Envelope, Meta, Page, Provenance, Truncation
from ..core.errors import RETRYABLE, ErrorCode, ErrorEnvelope
from .mcp_app import build_services

PROFILES = ("evs-only", "cadsr-only", "unified")


# ------------------------------------------------------------------ collect
def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    return obj


async def collect_profile(profile: str) -> dict[str, Any]:
    """Tools, resources, templates and prompts of one profile, as MCP wire objects."""
    from .mcp_app import build_mcp_server

    settings = Settings(_env_file=None, profile=profile, log_level="WARNING")
    services = build_services(settings)
    try:
        mcp, _ = build_mcp_server(settings, services=services)
        tools = await mcp.get_tools()
        resources = await mcp.get_resources()
        templates = await mcp.get_resource_templates()
        prompts = await mcp.get_prompts()
        return {
            "profile": profile,
            "tools": {name: _dump(t.to_mcp_tool()) for name, t in sorted(tools.items())},
            "resources": {str(k): _dump(r.to_mcp_resource()) for k, r in sorted(resources.items())},
            "resourceTemplates": {str(k): _dump(t.to_mcp_template()) for k, t in sorted(templates.items())},
            "prompts": {name: _dump(p.to_mcp_prompt()) for name, p in sorted(prompts.items())},
        }
    finally:
        await services.aclose()


def envelope_schemas() -> dict[str, Any]:
    return {
        "Envelope": Envelope.model_json_schema(),
        "Provenance": Provenance.model_json_schema(),
        "Truncation": Truncation.model_json_schema(),
        "Page": Page.model_json_schema(),
        "Meta": Meta.model_json_schema(),
        "ErrorEnvelope": ErrorEnvelope.model_json_schema(),
    }


def error_codes() -> dict[str, Any]:
    codes = list(ErrorCode.__args__)  # type: ignore[attr-defined]
    return {code: {"retryable": code in RETRYABLE} for code in codes}


async def collect_all() -> dict[str, Any]:
    return {
        "interfaceVersion": INTERFACE_VERSION,
        "serverVersion": __version__,
        "generatedAt": datetime.now(UTC).isoformat(),
        "profiles": {p: await collect_profile(p) for p in PROFILES},
        "envelopes": envelope_schemas(),
        "errorCodes": error_codes(),
    }


# -------------------------------------------------------------------- write
def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_baseline(snapshot: dict[str, Any], root: Path) -> Path:
    out = root / f"v{snapshot['interfaceVersion']}"
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def put(rel: str, obj: Any) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        text = _canon(obj)
        p.write_text(text, encoding="utf-8")
        files[rel] = hashlib.sha256(text.encode()).hexdigest()

    for profile, data in snapshot["profiles"].items():
        for name, tool in data["tools"].items():
            put(f"tools/{profile}/{name}.schema.json", tool)
        put(f"profiles/{profile}.json", {"profile": profile, "tools": sorted(data["tools"]), "resources": sorted(data["resources"]),
                                         "resourceTemplates": sorted(data["resourceTemplates"]), "prompts": sorted(data["prompts"])})
        put(f"resources/{profile}.json", {"resources": data["resources"], "resourceTemplates": data["resourceTemplates"]})
        put(f"prompts/{profile}.json", data["prompts"])
    for name, schema in snapshot["envelopes"].items():
        put(f"envelopes/{name}.schema.json", schema)
    put("error-codes.json", snapshot["errorCodes"])
    manifest = {
        "interfaceVersion": snapshot["interfaceVersion"], "serverVersion": snapshot["serverVersion"], "generatedAt": snapshot["generatedAt"],
        "files": dict(sorted(files.items())),
    }
    (out / "manifest.json").write_text(_canon(manifest), encoding="utf-8")
    return out


def read_baseline(root: Path, version: str) -> dict[str, Any] | None:
    base = root / f"v{version}"
    if not (base / "manifest.json").exists():
        return None
    snap: dict[str, Any] = {"interfaceVersion": version, "profiles": {}, "envelopes": {}, "errorCodes": {}}
    for prof_file in sorted((base / "profiles").glob("*.json")):
        profile = prof_file.stem
        tools = {}
        for tf in sorted((base / "tools" / profile).glob("*.schema.json")):
            tools[tf.name.removesuffix(".schema.json")] = json.loads(tf.read_text())
        res = json.loads((base / "resources" / f"{profile}.json").read_text()) if (base / "resources" / f"{profile}.json").exists() else {"resources": {}, "resourceTemplates": {}}
        prompts = json.loads((base / "prompts" / f"{profile}.json").read_text()) if (base / "prompts" / f"{profile}.json").exists() else {}
        snap["profiles"][profile] = {"profile": profile, "tools": tools, "resources": res["resources"], "resourceTemplates": res["resourceTemplates"], "prompts": prompts}
    for ef in sorted((base / "envelopes").glob("*.schema.json")):
        snap["envelopes"][ef.name.removesuffix(".schema.json")] = json.loads(ef.read_text())
    if (base / "error-codes.json").exists():
        snap["errorCodes"] = json.loads((base / "error-codes.json").read_text())
    return snap


# ------------------------------------------------------------------ compare
@dataclass
class Drift:
    breaking: list[str] = field(default_factory=list)
    nonBreaking: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.breaking

    def summary(self) -> str:
        lines = [f"breaking: {len(self.breaking)}", *[f"  - {b}" for b in self.breaking], f"non-breaking: {len(self.nonBreaking)}", *[f"  + {n}" for n in self.nonBreaking]]
        return "\n".join(lines)


def _strip_descriptions(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_descriptions(v) for k, v in obj.items() if k not in ("description", "title", "examples")}
    if isinstance(obj, list):
        return [_strip_descriptions(v) for v in obj]
    return obj


def _schema_drift(where: str, old: Any, new: Any, drift: Drift) -> None:
    """Classify a JSON-schema change. Pure additions of optional properties are non-breaking;
    everything else that changes structure is breaking."""
    if _strip_descriptions(old) == _strip_descriptions(new):
        if old != new:
            drift.nonBreaking.append(f"{where}: description/title text changed")
        return
    added, removed, changed = _diff_props(old, new)
    if removed or changed:
        drift.breaking.append(f"{where}: removed {sorted(removed)} changed {sorted(changed)}")
    elif added:
        if _required_grew(old, new):
            drift.breaking.append(f"{where}: new required field(s) {sorted(added)}")
        else:
            drift.nonBreaking.append(f"{where}: added optional field(s) {sorted(added)}")
    else:
        drift.breaking.append(f"{where}: schema changed")


def _props(schema: Any) -> dict[str, Any]:
    return dict(schema.get("properties") or {}) if isinstance(schema, dict) else {}


def _diff_props(old: Any, new: Any) -> tuple[set[str], set[str], set[str]]:
    op, np = _props(old), _props(new)
    added = set(np) - set(op)
    removed = set(op) - set(np)
    changed = {k for k in set(op) & set(np) if _strip_descriptions(op[k]) != _strip_descriptions(np[k])}
    # defs changes (nested models) count as changed if any shared $def differs
    od, nd = (old or {}).get("$defs") or {}, (new or {}).get("$defs") or {}
    for k in set(od) & set(nd):
        if _strip_descriptions(od[k]) != _strip_descriptions(nd[k]):
            a2, r2, c2 = _diff_props(od[k], nd[k])
            if r2 or c2 or (a2 and set(nd[k].get("required") or []) - set(od[k].get("required") or [])):
                changed.add(f"$defs.{k}")
            elif a2:
                added.update(f"$defs.{k}.{x}" for x in a2)
    if set(od) - set(nd):
        changed.update(f"$defs.{k}" for k in set(od) - set(nd))
    return added, removed, changed


def _required_grew(old: Any, new: Any) -> bool:
    return bool(set((new or {}).get("required") or []) - set((old or {}).get("required") or []))


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> Drift:
    drift = Drift()
    for profile, old in baseline["profiles"].items():
        new = current["profiles"].get(profile)
        if new is None:
            drift.breaking.append(f"profile {profile} removed")
            continue
        for name in sorted(set(old["tools"]) - set(new["tools"])):
            drift.breaking.append(f"[{profile}] tool {name} removed")
        for name in sorted(set(new["tools"]) - set(old["tools"])):
            drift.nonBreaking.append(f"[{profile}] tool {name} added")
        for name in sorted(set(old["tools"]) & set(new["tools"])):
            ot, nt = old["tools"][name], new["tools"][name]
            _schema_drift(f"[{profile}] {name}.inputSchema", ot.get("inputSchema"), nt.get("inputSchema"), drift)
            if ot.get("outputSchema") is not None:
                _schema_drift(f"[{profile}] {name}.outputSchema", ot.get("outputSchema"), nt.get("outputSchema"), drift)
            if (ot.get("annotations") or {}) != (nt.get("annotations") or {}):
                drift.breaking.append(f"[{profile}] {name}: annotations changed (read-only/idempotent hints are a contract)")
        for kind in ("resources", "resourceTemplates", "prompts"):
            removed = sorted(set(old.get(kind, {})) - set(new.get(kind, {})))
            added = sorted(set(new.get(kind, {})) - set(old.get(kind, {})))
            drift.breaking.extend(f"[{profile}] {kind[:-1]} {r} removed" for r in removed)
            drift.nonBreaking.extend(f"[{profile}] {kind[:-1]} {a} added" for a in added)
    for name, old in baseline.get("envelopes", {}).items():
        new = current.get("envelopes", {}).get(name)
        if new is None:
            drift.breaking.append(f"envelope schema {name} removed")
        else:
            _schema_drift(f"envelope {name}", old, new, drift)
    old_codes, new_codes = set(baseline.get("errorCodes", {})), set(current.get("errorCodes", {}))
    drift.breaking.extend(f"error code {c} removed" for c in sorted(old_codes - new_codes))
    drift.nonBreaking.extend(f"error code {c} added" for c in sorted(new_codes - old_codes))
    return drift


def conformance_mock_manifest(fixture_root: Path) -> dict[str, Any]:
    """Fixture ids and checksums for the conformance mock (proposal 13)."""
    files = {}
    for p in sorted(fixture_root.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".yaml", ".yml"):
            rel = str(p.relative_to(fixture_root))
            doc_note = None
            if p.suffix == ".json":
                try:
                    doc = json.loads(p.read_text())
                    doc_note = doc.get("_note") if isinstance(doc, dict) else None
                except ValueError:
                    pass
            files[rel] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "recorded": bool(doc_note and "Hand-authored" not in doc_note and "synthetic" not in doc_note.lower()), "note": (doc_note or "")[:160]}
    return {"fixtureRoot": str(fixture_root), "files": files}
