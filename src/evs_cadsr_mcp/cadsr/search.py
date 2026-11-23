"""Declared fan-out search over caDSR lookups (proposal 7.1, upstream gap ``cadsr-search``).

caDSR exposes no keyword search. ``cadsr_find_data_elements`` runs the requested routes
(alternate name, question text via reference documents, classification scheme, context)
in parallel under the invocation budget, de-duplicates by ``publicId + version``, caps each
route, and returns a :class:`Coverage` record naming what ran, what was skipped and what
was capped. It never claims to be exhaustive.
"""

from __future__ import annotations

import asyncio

from ..core.config import Settings
from ..core.context import Invocation
from ..core.errors import EvsMcpError, invalid_request
from . import normalise
from .client import CadsrClient, public_id
from .models import Coverage, DataElementSummary, FindDataElementsResult

ROUTES = ("alternateName", "questionText", "classification", "context")


class FanOutSearch:
    def __init__(self, settings: Settings, client: CadsrClient) -> None:
        self.settings = settings
        self.client = client

    async def find(
        self,
        inv: Invocation,
        query: str,
        *,
        by: list[str],
        exact: bool,
        context: str | None,
        classification_scheme_public_id: str | None,
        classification_scheme_version: str | None,
    ) -> FindDataElementsResult:
        bad = [r for r in by if r not in ROUTES]
        if bad:
            raise invalid_request("unknown route(s)", unknown=bad, allowed=list(ROUTES))
        routes = list(dict.fromkeys(by)) or list(ROUTES)
        skipped: list[str] = []
        tasks: dict[str, asyncio.Future] = {}

        async def guarded(coro):
            try:
                return await coro
            except EvsMcpError as exc:
                if exc.code in ("not_found",):
                    return []
                raise

        for r in routes:
            if r == "alternateName":
                tasks[r] = asyncio.ensure_future(guarded(self.client.data_elements_by_alternate_name(inv, query, exact=exact)))
            elif r == "questionText":
                tasks[r] = asyncio.ensure_future(guarded(self.client.data_elements_by_reference_document(inv, query, exact=exact)))
            elif r == "classification":
                if not classification_scheme_public_id:
                    skipped.append("classification (needs classificationSchemePublicId)")
                    continue
                tasks[r] = asyncio.ensure_future(guarded(self.client.data_elements_by_classification(inv, classification_scheme_public_id, classification_scheme_version)))
            elif r == "context":
                if not context:
                    skipped.append("context (needs context)")
                    continue
                tasks[r] = asyncio.ensure_future(guarded(self.client.data_elements_by_context(inv, context)))

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        merged: dict[tuple[str, str | None], DataElementSummary] = {}
        capped: list[str] = []
        ran: list[str] = []
        first_error: BaseException | None = None
        q = query.casefold()
        for route, res in zip(tasks.keys(), results, strict=True):
            if isinstance(res, BaseException):
                first_error = first_error or res
                skipped.append(f"{route} (error: {getattr(res, 'code', type(res).__name__)})")
                continue
            ran.append(route)
            items = res
            if route in ("classification", "context") and query.strip():
                # These routes enumerate a scheme/context; narrow by the query text locally.
                items = [i for i in items if q in str(i.get("longName") or i.get("preferredName") or "").casefold()
                         or q in str(public_id(i) or "")]
            if len(items) > self.settings.cadsr_fanout_cap:
                capped.append(route)
                items = items[: self.settings.cadsr_fanout_cap]
            for raw in items:
                s = normalise.summary(raw, matched_via=route)
                key = (s.publicId, s.version)
                if key not in merged:
                    merged[key] = s
                elif merged[key].matchedVia and route not in merged[key].matchedVia:
                    merged[key].matchedVia = f"{merged[key].matchedVia},{route}"
        if not ran and first_error is not None:
            raise first_error
        coverage = Coverage(routesRun=ran, routesSkipped=skipped, capped=capped)
        return FindDataElementsResult(dataElements=list(merged.values()), coverage=coverage)
