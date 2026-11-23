"""Transport-independent caDSR handlers (proposal Section 7.2). One method per tool."""

from __future__ import annotations

from typing import Any

from ..core.config import Settings
from ..core.context import Invocation
from ..core.cursor import decode_cursor, encode_cursor
from ..core.envelopes import Envelope, Page
from ..core.errors import EvsMcpError, invalid_request, not_found
from . import normalise
from .client import CadsrClient, norm_version, pick, public_id
from .models import (
    BatchDataElements,
    Context,
    CrdcMapEntry,
    DataElement,
    DataElementConcept,
    DataElementSummary,
    FindDataElementsResult,
    Form,
    FormUsage,
    MatchBackend,
    MatchEntity,
    MatchResult,
    PermissibleValue,
    RegistryStatus,
    ValueDomain,
    ValueMatch,
    VersionSummary,
)
from .search import FanOutSearch

INCLUDE_SECTIONS = ("valueDomain", "permissibleValues", "dataElementConcept", "alternateNames", "classificationSchemes", "referenceDocuments")
DEFAULT_INCLUDE = {"valueDomain", "dataElementConcept"}
ITEM_TYPES = ("ObjectClass", "Property", "RepresentationTerm", "ValueMeaning")


class CadsrService:
    def __init__(self, settings: Settings, client: CadsrClient) -> None:
        self.settings = settings
        self.client = client
        self.search = FanOutSearch(settings, client)

    # ------------------------------------------------------------------ CDEs
    async def _raw_de(self, inv: Invocation, public_id_: str, version: str | None) -> dict:
        raw = await self.client.data_element(inv, public_id_, version)
        if raw is None:
            raise not_found(f"data element {public_id_}" + (f" v{version}" if version else "") + " not found", publicId=public_id_, version=version)
        return raw

    def _uri(self, public_id_: str, version: str | None) -> str:
        return self.client.http.public_url(f"{self.settings.cadsr_nciapi_path}/DataElement/{public_id_}", {"version": norm_version(version)} if version else None)

    async def get_data_element(self, inv: Invocation, public_id_: str, version: str | None, include: list[str] | None) -> Envelope[DataElement]:
        inc = set(include) if include else set(DEFAULT_INCLUDE)
        bad = [i for i in inc if i not in INCLUDE_SECTIONS]
        if bad:
            raise invalid_request("unknown include section(s)", unknown=bad, allowed=list(INCLUDE_SECTIONS))
        raw = await self._raw_de(inv, public_id_, version)
        return inv.envelope(normalise.data_element(raw, include=inc, source_uri=self._uri(public_id_, version)))

    async def get_data_elements(self, inv: Invocation, ids: list[dict[str, Any]]) -> Envelope[BatchDataElements]:
        if not ids:
            raise invalid_request("ids must not be empty")
        if len(ids) > self.settings.cadsr_max_batch:
            raise invalid_request("too many ids; caDSR has no batch endpoint, so each id is one call", limit=self.settings.cadsr_max_batch, given=len(ids))
        found: list[DataElement] = []
        missing: list[str] = []
        for item in ids:
            pid = str(item.get("publicId"))
            ver = item.get("version")
            try:
                raw = await self._raw_de(inv, pid, ver)
            except EvsMcpError as exc:
                if exc.code == "not_found":
                    missing.append(f"{pid}" + (f" v{ver}" if ver else ""))
                    continue
                raise
            found.append(normalise.data_element(raw, include=set(DEFAULT_INCLUDE), source_uri=self._uri(pid, ver)))
        inv.warn("one upstream call per id (no caDSR batch endpoint)")
        return inv.envelope(BatchDataElements(dataElements=found, missing=missing))

    async def get_data_element_versions(self, inv: Invocation, public_id_: str) -> Envelope[list[VersionSummary]]:
        raws = await self.client.data_element_versions(inv, public_id_)
        if not raws:
            raise not_found(f"no versions found for {public_id_}", publicId=public_id_)
        out = [normalise.version_summary(r) for r in raws]
        out.sort(key=lambda v: _vkey(v.version), reverse=True)
        return inv.envelope(out)

    async def get_permissible_values(self, inv: Invocation, public_id_: str, version: str | None, *, limit: int, cursor: str | None) -> Envelope[list[PermissibleValue]]:
        limit = max(1, min(limit, 1000))
        raw = await self._raw_de(inv, public_id_, version)
        pin = _pin(raw, public_id_, version)
        offset = decode_cursor(cursor, release=pin)[0] if cursor else 0
        pvs = normalise.permissible_values(pick(raw, "ValueDomain", "valueDomain"))
        pvs.sort(key=lambda p: (p.displayOrder is None, p.displayOrder or 0))
        window = pvs[offset : offset + limit]
        more = offset + len(window) < len(pvs)
        page = Page(limit=limit, offset=offset, total=len(pvs), returned=len(window), nextCursor=encode_cursor(release=pin, offset=offset + len(window)) if more and window else None)
        vd_type = pick(pick(raw, "ValueDomain", "valueDomain") or {}, "type", "Type")
        if not pvs and vd_type and "non" in str(vd_type).lower():
            inv.warn("value domain is non-enumerated; it has no permissible values")
        return inv.envelope(window, page=page)

    async def get_value_domain(self, inv: Invocation, public_id_: str, version: str | None) -> Envelope[ValueDomain]:
        raw = await self._raw_de(inv, public_id_, version)
        vd = normalise.value_domain(pick(raw, "ValueDomain", "valueDomain"), include_pvs=False)
        if vd is None:
            raise not_found(f"data element {public_id_} has no value domain in the payload", publicId=public_id_)
        return inv.envelope(vd)

    async def get_data_element_concept(self, inv: Invocation, public_id_: str, version: str | None) -> Envelope[DataElementConcept]:
        raw = await self._raw_de(inv, public_id_, version)
        dec = normalise.data_element_concept(pick(raw, "DataElementConcept", "dataElementConcept"))
        if dec is None:
            raise not_found(f"data element {public_id_} has no data element concept in the payload", publicId=public_id_)
        return inv.envelope(dec)

    # --------------------------------------------------------------- lookups
    async def find_data_elements_by_concept(
        self, inv: Invocation, concept_code: str, *, item_type: str | None, workflow_status: str | None, limit: int, cursor: str | None,
    ) -> Envelope[list[DataElementSummary]]:
        if item_type and item_type not in ITEM_TYPES:
            raise invalid_request("itemType must be one of " + ", ".join(ITEM_TYPES))
        limit = max(1, min(limit, 100))
        pin = f"cadsr:concept:{concept_code}:{item_type or '*'}:{workflow_status or '*'}"
        offset = decode_cursor(cursor, release=pin)[0] if cursor else 0
        raws = await self.client.data_elements_by_concept(inv, concept_code, item_type=item_type, workflow_status=workflow_status)
        items = [normalise.summary(r, matched_role=item_type) for r in raws]  # role known only when filtered upstream
        items.sort(key=lambda s: (_ikey(s.publicId), _vkey(s.version)))
        window = items[offset : offset + limit]
        more = offset + len(window) < len(items)
        page = Page(limit=limit, offset=offset, total=len(items), returned=len(window), nextCursor=encode_cursor(release=pin, offset=offset + len(window)) if more and window else None)
        if not item_type:
            inv.warn("matchedRole is unknown unless itemType is given; caDSR reports annotation in any role")
        return inv.envelope(window, page=page)

    async def find_data_elements(
        self, inv: Invocation, query: str, *, by: list[str], exact: bool, context: str | None, scheme_id: str | None, scheme_version: str | None,
        limit: int, cursor: str | None,
    ) -> Envelope[FindDataElementsResult]:
        limit = max(1, min(limit, 100))
        pin = f"cadsr:find:{query}:{','.join(by)}:{exact}:{context}:{scheme_id}"
        offset = decode_cursor(cursor, release=pin)[0] if cursor else 0
        result = await self.search.find(inv, query, by=by, exact=exact, context=context, classification_scheme_public_id=scheme_id, classification_scheme_version=scheme_version)
        items = sorted(result.dataElements, key=lambda s: (_ikey(s.publicId), _vkey(s.version)))
        window = items[offset : offset + limit]
        more = offset + len(window) < len(items)
        page = Page(limit=limit, offset=offset, total=len(items), returned=len(window), nextCursor=encode_cursor(release=pin, offset=offset + len(window)) if more and window else None)
        inv.warn(result.coverage.note)
        for s in result.coverage.routesSkipped:
            inv.warn(f"route skipped: {s}")
        return inv.envelope(FindDataElementsResult(dataElements=window, coverage=result.coverage), page=page)

    # ----------------------------------------------------------------- forms
    async def get_form(self, inv: Invocation, public_id_: str, version: str | None, *, include_modules: bool) -> Envelope[Form]:
        raw = await self.client.form(inv, public_id_, version)
        if raw is None:
            raise not_found(f"form {public_id_} not found", publicId=public_id_)
        return inv.envelope(normalise.form(raw, include_modules=include_modules))

    async def get_forms_for_data_element(self, inv: Invocation, public_id_: str, version: str) -> Envelope[list[FormUsage]]:
        rows = await self.client.forms_for_data_element(inv, public_id_, version)
        usages = [normalise.form_usage(r) for r in rows]
        seen: set[tuple] = set()
        out = []
        for u in usages:
            key = (u.formPublicId, u.formVersion, u.modulePublicId, u.questionText)
            if key not in seen:
                seen.add(key)
                out.append(u)
        inv.warn("served by the legacy caDSR query DSL (the only route for forms-by-CDE)")
        return inv.envelope(out)

    async def list_contexts(self, inv: Invocation) -> Envelope[list[Context]]:
        rows = await self.client.contexts(inv)
        return inv.envelope([normalise.context(r) for r in rows])

    # -------------------------------------------------------------- matching
    async def list_match_backends(self, inv: Invocation) -> Envelope[list[MatchBackend]]:
        cred = self.client.credential is not None
        ai = self.client.ai_http is not None
        variants = await self.client.ai_variants(inv) if ai else None
        return inv.envelope([
            MatchBackend(name="cde_match", available=cred, reason=None if cred else "no caDSR Basic credential configured (ECM_CADSR_USERNAME and ECM_CADSR_PASSWORD, or ECM_CADSR_CREDENTIAL)"),
            MatchBackend(name="ai_engine", available=ai, reason=None if ai else "CDE AI Match API not configured (ECM_CADSR_AI_MATCH_URL)", variants=variants),
            MatchBackend(name="vm_match", available=True),
        ])

    async def match_data_elements(
        self, inv: Invocation, entities: list[MatchEntity], *, match_limit: int, contexts: list[str] | None, backend: str,
    ) -> Envelope[list[MatchResult]]:
        if not entities or len(entities) > 10:
            raise invalid_request("entities must contain 1..10 items")
        payload = [{"name": e.name, **({"userTip": e.userTip} if e.userTip else {}), **({"permissibleValues": e.permissibleValues} if e.permissibleValues else {})} for e in entities]
        if backend == "cde_match":
            data = await self.client.cde_match(inv, payload, match_limit=match_limit, contexts=contexts)
        elif backend == "ai_engine":
            data = await self.client.ai_match(inv, payload, match_limit=match_limit, contexts=contexts)
        else:
            raise invalid_request("backend must be cde_match or ai_engine")
        results = _match_results(data, backend, [e.name for e in entities])
        # Returned ids are resolved against NCI API 1.0 before being cited (proposal 7.1), budget permitting.
        resolved = 0
        for r in results:
            if r.publicId and inv.budget.remaining > 1:
                try:
                    raw = await self.client.data_element(inv, r.publicId, r.version)
                except EvsMcpError:
                    raw = None
                if raw is not None:
                    # CDE Match's longName is often the short name (e.g. RACE_CAT_TXT); cite NCI API 1.0's.
                    r.longName = pick(raw, "longName", "LongName") or r.longName
                    resolved += 1
        if resolved < len([r for r in results if r.publicId]):
            inv.warn("some match candidates were not resolved against NCI API 1.0 (budget); cite them with care")
        return inv.envelope(results)

    async def match_value_meanings(self, inv: Invocation, values: list[str], *, strictness: str | None, scope: list[str] | None) -> Envelope[list[ValueMatch]]:
        if not values or len(values) > 10:
            raise invalid_request("values must contain 1..10 items")
        data = await self.client.vm_match(inv, values, strictness=strictness, scope=scope)
        return inv.envelope(_value_matches(data, values))

    # --------------------------------------------------------- CRDC / status
    async def get_crdc_code_map(self, inv: Invocation, data_element_id: str | None, *, limit: int, cursor: str | None) -> Envelope[list[CrdcMapEntry]]:
        limit = max(1, min(limit, 1000))
        pin = f"cadsr:crdc:{data_element_id or '*'}"
        offset = decode_cursor(cursor, release=pin)[0] if cursor else 0
        rows = [normalise.crdc_entry(r) for r in await self.client.crdc_list(inv)]
        if data_element_id:
            rows = [r for r in rows if r.dataElementPublicId == str(data_element_id)]
        window = rows[offset : offset + limit]
        more = offset + len(window) < len(rows)
        page = Page(limit=limit, offset=offset, total=len(rows), returned=len(window), nextCursor=encode_cursor(release=pin, offset=offset + len(window)) if more and window else None)
        return inv.envelope(window, page=page)

    async def get_registry_status(self, inv: Invocation) -> Envelope[RegistryStatus]:
        export_date = None
        url = self.settings.cadsr_export_listing_url
        if url:
            try:
                res = await self.client.http.get_json(url, budget=inv.budget, correlation_id=inv.correlation_id, not_found_ok=True)
                export_date = _export_date(res.data)
            except EvsMcpError as exc:
                inv.warn(f"export listing unavailable: {exc.code}")
        else:
            inv.warn("no export listing configured (ECM_CADSR_EXPORT_LISTING_URL); exportDate unknown")
        return inv.envelope(RegistryStatus(published=False, exportDate=export_date))


# ------------------------------------------------------------------ helpers
def _pin(raw: dict, public_id_: str, version: str | None) -> str:
    return f"cadsr:{public_id(raw) or public_id_}:{pick(raw, 'version', 'Version') or norm_version(version) or 'latest'}"


def _vkey(v: str | None) -> float:
    try:
        return float(v) if v is not None else -1.0
    except ValueError:
        return -1.0


def _ikey(pid: str) -> tuple[int, Any]:
    return (0, int(pid)) if pid.isdigit() else (1, pid)


def _match_results(data: Any, backend: str, names: list[str]) -> list[MatchResult]:
    """Flatten either backend's response into MatchResult rows (tolerant; shapes [verify])."""
    out: list[MatchResult] = []
    rows: list[tuple[str, dict]] = []
    if isinstance(data, dict):
        container = data.get("matchResults") or data.get("results") or data.get("matches") or data.get("entities") or data.get("data") or []
        if isinstance(container, dict):
            container = [container]
    else:
        container = data or []
    for i, item in enumerate(container):
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or item.get("name") or item.get("source_entity") or (names[i] if i < len(names) else ""))
        cands = item.get("matches") or item.get("candidates") or item.get("cdes") or item.get("results")
        if isinstance(cands, list):
            for c in cands:
                if isinstance(c, dict):
                    rows.append((entity, c))
        else:
            rows.append((entity, item))
    for entity, c in rows:
        de = c.get("DataElement") or c.get("dataElement") or c
        score = c.get("score") or c.get("similarity") or c.get("confidence")
        out.append(
            MatchResult(
                backend=backend,  # type: ignore[arg-type]
                entity=entity,
                publicId=public_id(de) or (str(c.get("cde_id")) if c.get("cde_id") else None),
                version=norm_version(pick(de, "version", "Version") or c.get("cde_version")),
                longName=pick(de, "longName", "LongName") or c.get("cde_long_name"),
                score=float(score) if isinstance(score, (int, float)) else None,
                matchedField=c.get("matchedField") or c.get("matched_field") or c.get("ruleDescription"),
                pvAnalysis=c.get("pvAnalysis") or c.get("pv_analysis") if isinstance(c.get("pvAnalysis") or c.get("pv_analysis"), dict) else None,
                raw={k: v for k, v in list(c.items())[:30] if not isinstance(v, (dict, list))},
            )
        )
    return out


def _value_matches(data: Any, values: list[str]) -> list[ValueMatch]:
    out: list[ValueMatch] = []
    container = (data.get("results") or data.get("matches") or data.get("values") or []) if isinstance(data, dict) else (data or [])
    by_value: dict[str, list[dict]] = {}
    for item in container:
        if not isinstance(item, dict):
            continue
        v = str(item.get("value") or item.get("input") or "")
        cands = item.get("matches") or item.get("candidates") or item.get("valueMeanings") or []
        by_value.setdefault(v, []).extend(c for c in cands if isinstance(c, dict))
    for v in values:
        out.append(ValueMatch(value=v, candidates=[{k: x for k, x in c.items() if not isinstance(x, (dict, list))} for c in by_value.get(v, [])]))
    return out


def _export_date(data: Any) -> str | None:
    if isinstance(data, dict):
        for k in ("exportDate", "date", "lastModified"):
            if data.get(k):
                return str(data[k])
    return None
