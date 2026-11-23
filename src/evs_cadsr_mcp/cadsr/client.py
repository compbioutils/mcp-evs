"""caDSR II clients (proposal Section 7.1).

* NCI API 1.0 (``/rad/NCIAPI/1.0/api``): fully expanded ``DataElement/{publicId}?version=``,
  version lineage, and lookups by concept, context, classification, alternate name and
  reference document; ``getCRDCList``.
* Form API 2.0, the legacy object-graph DSL (only route for "forms that use a CDE"), the
  LOV API (Basic), CDE Match 2.0 (Basic), VM Match, and the CDE AI Match API (internal).

Behaviour handled here, so the rest of the module never sees it:

* errors arrive as **HTTP 200 with ``apiResponse.type == "E"``** -> ``invalid_request`` for
  parameter errors, ``not_found`` for empty payloads;
* field-name drift (``publicId`` / ``publicID`` / ``PublicId``, ``latesetVersionIndicator``,
  "Superceded") is normalised by :func:`pick` and :func:`norm_status`;
* a 45 s read deadline, retries only on connection errors and 5xx (never on 200-with-error),
  ``Accept: application/json`` and ``X-Correlation-ID`` on every request;
* responses cached by ``publicId + version`` (one 7 s fetch serves every derived view);
* credentialed services raise ``capability_unavailable`` with the reason when no credential
  is configured; credentialed results are never cached across invocations.

Endpoint parameter names marked ``[verify]`` were taken from the proposal and the API
Swagger summaries, not from a live call; ``scripts/record_fixtures.py --cadsr`` records them.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import structlog

from ..core.cache import cache_key
from ..core.config import Settings
from ..core.context import Invocation
from ..core.envelopes import Provenance, Registry
from ..core.errors import EvsMcpError, invalid_request
from ..core.http_client import ResilientClient
from ..core.shared_cache import TieredCache

log = structlog.get_logger(__name__)

_PUBLIC_ID_KEYS = ("publicId", "publicID", "PublicId", "PublicID", "public_id")
_LATEST_KEYS = ("latestVersionIndicator", "latesetVersionIndicator", "LatestVersionIndicator")


def pick(d: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Return the first present key (handles upstream casing drift)."""
    if not d:
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v is not None:
            return v
    return default


def public_id(d: dict[str, Any] | None) -> str | None:
    v = pick(d, *_PUBLIC_ID_KEYS)
    return str(v) if v is not None else None


def latest_flag(d: dict[str, Any] | None) -> bool | None:
    v = pick(d, *_LATEST_KEYS)
    if v is None:
        return None
    return str(v).strip().lower() in {"yes", "y", "true", "1"}


def norm_status(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    return "SUPERSEDED" if s.strip().upper() == "SUPERCEDED" else s


def norm_version(v: Any) -> str | None:
    """caDSR versions are decimals ('1.0', '3.0'); callers may pass '1' or 1."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return s
    return f"{f:g}" if "." in f"{f:g}" else f"{f:.1f}"


class CadsrClient:
    def __init__(self, settings: Settings, http: ResilientClient, cache: TieredCache, *, ai_http: ResilientClient | None = None) -> None:
        self.settings = settings
        self.http = http
        self.cache = cache
        self.ai_http = ai_http  # CDE AI Match API lives on its own host (per environment)

    # ------------------------------------------------------------- helpers
    @property
    def credential(self) -> tuple[str, str] | None:
        return self.settings.cadsr_basic_auth()

    def require_credential(self, service: str) -> tuple[str, str]:
        cred = self.credential
        if cred is None:
            raise EvsMcpError(
                "capability_unavailable",
                f"{service} requires caDSR Basic credentials, and none are configured "
                "(ECM_CADSR_USERNAME and ECM_CADSR_PASSWORD, or ECM_CADSR_CREDENTIAL)",
                details={"service": service, "configure": "ECM_CADSR_USERNAME=<user> and ECM_CADSR_PASSWORD=<password>"},
                hint="This tool needs caDSR credentials on the server. Without them, use the anonymous tools: "
                     "cadsr_find_data_elements, cadsr_find_data_elements_by_concept or cadsr_get_data_element.",
            )
        return cred

    def _prov(self, source: str, served: str, uri: str, retrieved_at: datetime | None, cached_at: datetime | None = None,
              registry: Registry | None = None) -> Provenance:
        return Provenance(source=source, servedBy=served, sourceUri=uri, retrievedAt=retrieved_at, cachedAt=cached_at, registry=registry)  # type: ignore[arg-type]

    @staticmethod
    def _check_api_response(data: Any, *, what: str) -> Any:
        """Map caDSR's 200-with-error convention to our closed error set."""
        if isinstance(data, dict):
            api = data.get("apiResponse") or data.get("ApiResponse")
            if isinstance(api, dict) and str(api.get("type", "")).upper() == "E":
                msg = str(api.get("message") or "")
                low = msg.lower()
                if "not found" in low or "no data" in low or "does not exist" in low:
                    raise EvsMcpError("not_found", f"{what} not found in caDSR", details={"upstream": "apiResponse.type=E"})
                raise invalid_request(f"caDSR rejected the request for {what}", upstream="apiResponse.type=E")
        return data

    async def _get(
        self,
        inv: Invocation,
        path: str,
        *,
        params: dict[str, Any] | None,
        source: str,
        what: str,
        cache_cls: str | None = "cadsr",
        registry: Registry | None = None,
        auth: tuple[str, str] | None = None,
        not_found_ok: bool = False,
    ) -> Any:
        uri = self.http.public_url(path, params)
        key = cache_key(path, None, **(params or {}))
        if cache_cls and auth is None:
            entry = await self.cache.aget(cache_cls, key)  # type: ignore[arg-type]
            if entry is not None:
                inv.add_provenance(self._prov(source, "cache", uri, entry.retrieved_at, entry.cached_at, registry))
                return entry.value
        res = await self.http.get_json(path, params=params, budget=inv.budget, correlation_id=inv.correlation_id, auth=auth, not_found_ok=not_found_ok)
        if res.data is None:
            inv.add_provenance(self._prov(source, "live", uri, res.retrieved_at, None, registry))
            return None
        data = self._check_api_response(res.data, what=what)
        if cache_cls and auth is None:
            await self.cache.aput(cache_cls, key, data, retrieved_at=res.retrieved_at)  # type: ignore[arg-type]
        if registry is not None and registry.retrievedAt is None:
            registry = registry.model_copy(update={"retrievedAt": res.retrieved_at})
        inv.add_provenance(self._prov(source, "live", uri, res.retrieved_at, None, registry))
        return data

    # ---------------------------------------------------------- NCI API 1.0
    def _api(self, suffix: str) -> str:
        return f"{self.settings.cadsr_nciapi_path}/{suffix.lstrip('/')}"

    async def data_element(self, inv: Invocation, public_id_: str, version: str | None) -> dict | None:
        """Fully expanded CDE. ``version=None`` resolves to the latest version upstream."""
        params = {"version": norm_version(version)} if version else None
        data = await self._get(
            inv, self._api(f"DataElement/{public_id_}"), params=params, source="cadsr_nciapi",
            what=f"data element {public_id_}", registry=Registry(publicId=public_id_, version=norm_version(version)), not_found_ok=True,
        )
        if data is None:
            return None
        de = pick(data, "DataElement", "dataElement") if isinstance(data, dict) else None
        if de is None and isinstance(data, dict) and public_id(data):
            de = data  # some deployments return the element unwrapped
        return de or None

    async def data_element_versions(self, inv: Invocation, public_id_: str) -> list[dict]:
        data = await self._get(inv, self._api("DataElements"), params={"publicId": public_id_}, source="cadsr_nciapi", what=f"versions of {public_id_}", not_found_ok=True)
        return _elements(data)

    async def data_elements_by_concept(self, inv: Invocation, concept_code: str, *, item_type: str | None, workflow_status: str | None) -> list[dict]:
        params = {"conceptCode": concept_code, "itemTypeFilter": item_type, "workflowStatusFilter": workflow_status, "headerOnly": True}
        data = await self._get(inv, self._api("DataElements/Concept"), params=params, source="cadsr_nciapi", what=f"data elements for concept {concept_code}", not_found_ok=True)
        return _elements(data)

    async def data_elements_by_context(self, inv: Invocation, context: str) -> list[dict]:
        data = await self._get(inv, self._api("DataElements/Context"), params={"context": context, "headerOnly": True}, source="cadsr_nciapi", what=f"data elements in context {context}", not_found_ok=True)  # [verify] param name
        return _elements(data)

    async def data_elements_by_classification(self, inv: Invocation, scheme_public_id: str, version: str | None) -> list[dict]:
        params = {"publicId": scheme_public_id, "version": norm_version(version), "headerOnly": True}  # [verify] param names
        data = await self._get(inv, self._api("DataElements/Classification"), params=params, source="cadsr_nciapi", what="data elements by classification", not_found_ok=True)
        return _elements(data)

    async def data_elements_by_alternate_name(self, inv: Invocation, name: str, *, exact: bool) -> list[dict]:
        params = {"name": name, "exactMatch": exact, "headerOnly": True}  # [verify] param names
        data = await self._get(inv, self._api("DataElements/AlternateName"), params=params, source="cadsr_nciapi", what="data elements by alternate name", not_found_ok=True)
        return _elements(data)

    async def data_elements_by_reference_document(self, inv: Invocation, text: str, *, exact: bool) -> list[dict]:
        params = {"text": text, "exactMatch": exact, "headerOnly": True}  # [verify] param names
        data = await self._get(inv, self._api("DataElements/ReferenceDocument"), params=params, source="cadsr_nciapi", what="data elements by reference document", not_found_ok=True)
        return _elements(data)

    async def crdc_list(self, inv: Invocation) -> list[dict]:
        data = await self._get(inv, self._api("DataElements/getCRDCList"), params=None, source="cadsr_nciapi", what="CRDC list", not_found_ok=True)
        if isinstance(data, dict):
            for k in ("CRDCDataElements", "DataElements", "crdcList", "list"):
                if isinstance(data.get(k), list):
                    return data[k]
        return data if isinstance(data, list) else []

    # ----------------------------------------------------------- Form API 2.0
    async def form(self, inv: Invocation, public_id_: str, version: str | None) -> dict | None:
        params = {"version": norm_version(version)} if version else None
        data = await self._get(
            inv, f"{self.settings.cadsr_formapi_path}/Form/{public_id_}", params=params, source="cadsr_formapi",
            what=f"form {public_id_}", registry=Registry(publicId=public_id_, version=norm_version(version)), not_found_ok=True,
        )
        if data is None:
            return None
        f = pick(data, "Form", "form") if isinstance(data, dict) else None
        return f or (data if isinstance(data, dict) and public_id(data) else None)

    # ------------------------------------------------------------ legacy DSL
    async def forms_for_data_element(self, inv: Invocation, public_id_: str, version: str) -> list[dict]:
        ver = norm_version(version)
        # Values are spliced into the legacy query language, so only plain numbers may pass.
        if not (re.fullmatch(r"[0-9]{1,12}", str(public_id_)) and ver and re.fullmatch(r"[0-9]{1,4}(\.[0-9]{1,4})?", ver)):
            raise EvsMcpError("invalid_request", "publicId and version must be numeric, e.g. 2192199 and 1.0")
        query = f"Question&DataElement[@publicId={public_id_},@version={ver}]"
        data = await self._get(inv, self.settings.cadsr_legacy_path, params={"query": query}, source="cadsr_legacy", what=f"forms using {public_id_}", not_found_ok=True)
        if isinstance(data, dict):
            for k in ("Question", "Questions", "questions", "data"):
                if isinstance(data.get(k), list):
                    return data[k]
            return []
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------ LOV
    async def contexts(self, inv: Invocation) -> list[dict]:
        """Context names from the LOV API: ``{"apiResponse": ..., "contextNames": ["ABTC", ...]}``
        (verified against caDSR stage, 2026-11-20)."""
        cred = self.require_credential("LOV API (contexts)")
        data = await self._get(inv, f"{self.settings.cadsr_lov_path}/getContextNames", params=None, source="cadsr_nciapi", what="contexts", cache_cls=None, auth=cred)
        names = data.get("contextNames") if isinstance(data, dict) else data
        return [{"name": n} if isinstance(n, str) else n for n in names or [] if isinstance(n, (str, dict))]

    # ------------------------------------------------------------- matching
    async def cde_match(self, inv: Invocation, entities: list[dict], *, match_limit: int, contexts: list[str] | None) -> Any:
        """CDE Match 2.0 takes one entity per POST: body ``{entity, entityUserTip?, pvvmData?: [{name}]}``
        with ``matchLimit`` and ``contexts`` (comma-separated) as headers, and answers
        ``{apiResponse, matchResults: {entity, matches: [...]}}`` (published contract; verified on stage)."""
        cred = self.require_credential("CDE Match 2.0")
        headers = {"matchLimit": str(match_limit), **({"contexts": ",".join(contexts)} if contexts else {})}
        results = []
        for e in entities:
            body: dict[str, Any] = {"entity": e["name"]}
            if e.get("userTip"):
                body["entityUserTip"] = e["userTip"]
            if e.get("permissibleValues"):
                body["pvvmData"] = [{"name": v} for v in e["permissibleValues"]]
            res = await self.http.post_json(self.settings.cadsr_cde_match_path, json_body=body, headers=headers,
                                            budget=inv.budget, correlation_id=inv.correlation_id, auth=cred)
            inv.add_provenance(self._prov("cadsr_match", "live", self.http.public_url(self.settings.cadsr_cde_match_path), res.retrieved_at))
            data = self._check_api_response(res.data, what="CDE match")
            match = data.get("matchResults") if isinstance(data, dict) else None
            results.append({"entity": e["name"], **(match if isinstance(match, dict) else {})})
        return {"matchResults": results}

    async def vm_match(self, inv: Invocation, values: list[str], *, strictness: str | None, scope: list[str] | None) -> Any:
        body: dict[str, Any] = {"values": values}
        if strictness:
            body["strictness"] = strictness
        if scope:
            body["terminologyScope"] = scope
        res = await self.http.post_json(self.settings.cadsr_vm_match_path, json_body=body, budget=inv.budget, correlation_id=inv.correlation_id)
        inv.add_provenance(self._prov("cadsr_vmmatch", "live", self.http.public_url(self.settings.cadsr_vm_match_path), res.retrieved_at))
        return self._check_api_response(res.data, what="value meaning match")

    async def ai_match(self, inv: Invocation, entities: list[dict], *, match_limit: int, contexts: list[str] | None) -> Any:
        if self.ai_http is None:
            raise EvsMcpError(
                "capability_unavailable",
                "the CDE AI Match API is not configured for this deployment (ECM_CADSR_AI_MATCH_URL)",
                details={"service": "cde_ai_match"},
                hint="Call cadsr_match_data_elements with backend 'cde_match' instead; "
                     "cadsr_list_match_backends shows what this deployment supports.",
            )
        body: dict[str, Any] = {"source_entities": entities, "match_limit": match_limit}
        if contexts:
            body["context_names"] = contexts
        if self.settings.cadsr_ai_match_variant:
            body["cde_model_variant"] = self.settings.cadsr_ai_match_variant
        res = await self.ai_http.post_json("/match", json_body=body, budget=inv.budget, correlation_id=inv.correlation_id)
        inv.add_provenance(
            Provenance(source="cadsr_cde_ai", servedBy="live", sourceUri=self.ai_http.public_url("/match"), retrievedAt=res.retrieved_at,
                       attribution=f"engine={self.ai_http.base_url} variant={self.settings.cadsr_ai_match_variant or 'default'}")
        )
        return res.data

    async def ai_variants(self, inv: Invocation) -> list[str]:
        if self.ai_http is None:
            return []
        res = await self.ai_http.get_json("/embedding_variants", budget=inv.budget, correlation_id=inv.correlation_id, not_found_ok=True)
        data = res.data
        if isinstance(data, dict):
            data = data.get("variants") or data.get("embedding_variants") or []
        return [str(v.get("name") if isinstance(v, dict) else v) for v in (data or [])]


def _elements(data: Any) -> list[dict]:
    """Unwrap the list from NCI API 1.0 responses, tolerating a few container names."""
    if data is None:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for k in ("DataElements", "dataElements", "DataElement", "data", "results"):
            v = data.get(k)
            if isinstance(v, list):
                return [d for d in v if isinstance(d, dict)]
            if isinstance(v, dict):
                return [v]
    return []
