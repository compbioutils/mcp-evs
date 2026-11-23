"""Model-fragment adapters: client-supplied GDC JSON / GDC YAML / MDF YAML -> ModelProperty.

Fragments are parsed, never fetched or stored (proposal 8.1). Adapters are tolerant of the
common shapes: a GDC entity schema (``{"id": ..., "properties": {...}}``, as returned by the
Submission API ``_dictionary/{entity}``), a dictionary of entities, a ``_terms.yaml``-style
mapping of property names to ``termDef`` blocks, a single property block, and Bento MDF
``PropDefinitions`` with ``Term: [{Origin: caDSR, Code, Version}]`` at property level.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from ...core.errors import invalid_request
from ..models import ModelEnumValue, ModelFragment, ModelProperty

_MAX_FRAGMENT_BYTES = 4 * 1024 * 1024


def parse_fragment(fragment: ModelFragment) -> list[ModelProperty]:
    if len(fragment.content.encode("utf-8", "ignore")) > _MAX_FRAGMENT_BYTES:
        raise invalid_request("fragment exceeds 4 MiB")
    try:
        doc = json.loads(fragment.content) if fragment.format == "gdc_json" else yaml.safe_load(fragment.content)
    except (ValueError, yaml.YAMLError) as exc:
        raise invalid_request(f"fragment is not valid {'JSON' if fragment.format == 'gdc_json' else 'YAML'}", detail=type(exc).__name__) from exc
    if not isinstance(doc, dict):
        raise invalid_request("fragment must be a JSON/YAML object")
    props = mdf_properties(doc) if fragment.format == "mdf_yaml" else gdc_properties(doc)
    if fragment.entity:
        props = [p for p in props if (p.entity or "").lower() == fragment.entity.lower()] or props
    if fragment.property:
        props = [p for p in props if p.name == fragment.property]
        if not props:
            raise invalid_request(f"property '{fragment.property}' not found in fragment")
    if not props:
        raise invalid_request("no properties recognised in fragment")
    return props


# ---------------------------------------------------------------------- GDC
def gdc_properties(doc: dict[str, Any]) -> list[ModelProperty]:
    out: list[ModelProperty] = []
    if isinstance(doc.get("properties"), dict):  # one entity schema
        entity = doc.get("id") or doc.get("title")
        for name, block in doc["properties"].items():
            if isinstance(block, dict):
                out.append(_gdc_property(name, block, entity))
        return out
    if any(k in doc for k in ("termDef", "enum", "enumDef")):  # one property block
        return [_gdc_property(str(doc.get("id") or doc.get("name") or "property"), doc, None)]
    # dictionary of entities, or a _terms.yaml-style map of property name -> block
    for key, val in doc.items():
        if not isinstance(val, dict):
            continue
        if isinstance(val.get("properties"), dict):
            for name, block in val["properties"].items():
                if isinstance(block, dict):
                    out.append(_gdc_property(name, block, val.get("id") or key))
        elif any(k in val for k in ("termDef", "enum", "enumDef", "description")):
            out.append(_gdc_property(key, val, None))
    return out


def _gdc_property(name: str, block: dict[str, Any], entity: str | None) -> ModelProperty:
    td = block.get("termDef") if isinstance(block.get("termDef"), dict) else {}
    cde_id = td.get("cde_id")
    cde_version = td.get("cde_version")
    source = td.get("source")
    enum_values: list[ModelEnumValue] = []
    enum_def = block.get("enumDef") if isinstance(block.get("enumDef"), dict) else {}
    raw_enum = block.get("enum")
    values = list(raw_enum) if isinstance(raw_enum, list) else list(enum_def.keys())
    for v in values:
        ed = enum_def.get(v) if isinstance(enum_def.get(v), dict) else {}
        etd = ed.get("termDef") if isinstance(ed.get("termDef"), dict) else ed
        enum_values.append(
            ModelEnumValue(
                value=str(v),
                conceptCode=_ncit_code(etd.get("term_id")) if etd else None,
                cdeId=str(etd["cde_id"]) if etd and etd.get("cde_id") is not None else None,
                cdeVersion=_ver(etd.get("cde_version")) if etd else None,
                source=etd.get("source") if etd else None,
            )
        )
    return ModelProperty(
        model="gdc",
        entity=entity,
        name=name,
        description=block.get("description"),
        cdeId=str(cde_id) if cde_id is not None else None,
        cdeVersion=_ver(cde_version),
        cdeSource=source,
        termConceptCode=_ncit_code(td.get("term_id")) if str(source or "").lower() == "ncit" else None,
        enum=enum_values,
        required=None,
        type=_type(block.get("type")),
    )


# ---------------------------------------------------------------------- MDF
def mdf_properties(doc: dict[str, Any]) -> list[ModelProperty]:
    defs = doc.get("PropDefinitions")
    if not isinstance(defs, dict):
        raise invalid_request("MDF fragment needs a PropDefinitions mapping")
    owners: dict[str, str] = {}
    nodes = doc.get("Nodes")
    if isinstance(nodes, dict):
        for node, nd in nodes.items():
            for p in (nd or {}).get("Props") or []:
                owners.setdefault(str(p), str(node))
    out = []
    for name, block in defs.items():
        if not isinstance(block, dict):
            continue
        cde_id = cde_version = cde_source = ncit = None
        terms = block.get("Term") or block.get("Terms") or []
        if isinstance(terms, dict):
            terms = [terms]
        for t in terms:
            if not isinstance(t, dict):
                continue
            origin = str(t.get("Origin") or "").lower()
            if origin == "cadsr" and cde_id is None:
                cde_id, cde_version, cde_source = str(t.get("Code")), _ver(t.get("Version")), "caDSR"
            elif origin in ("ncit", "nci thesaurus") and ncit is None:
                ncit = _ncit_code(t.get("Code"))
        enum_raw = block.get("Enum")
        typ = block.get("Type")
        if enum_raw is None and isinstance(typ, dict):
            enum_raw = typ.get("Enum")
        if enum_raw is None and isinstance(typ, list):
            enum_raw = typ
        enum_values = []
        for item in enum_raw or []:
            if isinstance(item, dict):
                val = str(item.get("Value") or item.get("value") or "")
                code = None
                for t in item.get("Term") or []:
                    if isinstance(t, dict) and str(t.get("Origin") or "").lower() in ("ncit", "nci thesaurus"):
                        code = _ncit_code(t.get("Code"))
                enum_values.append(ModelEnumValue(value=val, conceptCode=code))
            else:
                enum_values.append(ModelEnumValue(value=str(item)))
        out.append(
            ModelProperty(
                model="mdf", entity=owners.get(name), name=name, description=block.get("Desc") or block.get("Description"),
                cdeId=cde_id, cdeVersion=cde_version, cdeSource=cde_source, termConceptCode=ncit, enum=enum_values,
                required=_req(block.get("Req")), type=_type(typ if not isinstance(typ, (dict, list)) else (typ.get("value_type") if isinstance(typ, dict) else "enum")),
            )
        )
    return out


# ------------------------------------------------------------------ helpers
def _ncit_code(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    return s if s[:1] == "C" and s[1:].isdigit() else None


def _ver(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    try:
        f = float(s)
        return f"{f:.1f}" if f == int(f) else f"{f:g}"
    except ValueError:
        return s


def _type(v: Any) -> str | None:
    if v is None:
        return None
    return ",".join(map(str, v)) if isinstance(v, list) else str(v)


def _req(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("yes", "true", "required", "preferred")
