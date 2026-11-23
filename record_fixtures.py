"""Record contract fixtures from the live EVS REST API.

Usage (from the repo root, with the project installed):

    python scripts/record_fixtures.py [--release 26.10d] [--out tests/fixtures/evs]

Each fixture is written as ``{"_note": ..., "_recorded": {...}, "data": ...}`` so the
test harness can keep using ``doc["data"]``. Re-run after each monthly NCIt release and
diff the result to catch upstream drift (proposal Section 12).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://api-evsrest.nci.nih.gov/api/v1"


async def fetch(client: httpx.AsyncClient, path: str, params: dict | None = None):
    r = await client.get(path, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


async def main(release: str | None, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=BASE, timeout=60, headers={"Accept": "application/json"}) as c:
        terms = await fetch(c, "/metadata/terminologies", {"terminology": "ncit"})
        if release is None:
            release = next(t["version"] for t in terms if t.get("latest"))
        tv = f"ncit_{release}"
        stamp = {"recordedAt": datetime.now(UTC).isoformat(), "release": release, "base": BASE}

        def write(name: str, data, note: str) -> None:
            (out / name).write_text(json.dumps({"_note": note, "_recorded": stamp, "data": data}, indent=2) + "\n")
            print("wrote", name)

        write("metadata_terminologies_ncit.json", terms, "GET /metadata/terminologies?terminology=ncit")
        write("metadata_terminologies_latest.json", await fetch(c, "/metadata/terminologies", {"latest": "true"}), "GET /metadata/terminologies?latest=true")
        write("concept_C3224_summary.json", await fetch(c, f"/concept/{tv}/C3224", {"include": "summary"}), f"GET /concept/{tv}/C3224?include=summary")
        write(
            "concept_C3224_relations.json",
            await fetch(c, f"/concept/{tv}/C3224", {"include": "roles,associations,inverseRoles,inverseAssociations,disjointWith,maps,history,parents,children"}),
            f"GET /concept/{tv}/C3224 with itemised relationship flags",
        )
        write("search_melanoma_contains.json", await fetch(c, f"/concept/{tv}/search", {"term": "melanoma", "type": "contains", "include": "minimal", "pageSize": 3}), "search contains")
        write("search_nsclc_match.json", await fetch(c, f"/concept/{tv}/search", {"term": "NSCLC", "type": "match", "include": "summary,synonyms", "pageSize": 5}), "search match")

        misc = {}
        for path, params in [
            (f"/concept/{tv}/C3224/children", None),
            (f"/concept/{tv}/C3224/parents", None),
            (f"/concept/{tv}/roots", {"include": "minimal"}),
            (f"/concept/{tv}/C3224/descendants", {"maxLevel": 1, "pageSize": 4, "fromRecord": 0}),
            (f"/concept/{tv}/C3224/pathsToRoot", None),
            # EVS serves the subset tree and lookups only unpinned; members accept pinning.
            ("/subset/ncit", {"include": "minimal"}),
            ("/subset/ncit/C177537", {"include": "minimal"}),
            (f"/subset/{tv}/C177537/members", {"include": "minimal", "pageSize": 2, "fromRecord": 0}),
            ("/mapset", {"include": "properties"}),
            ("/mapset/NCIt_Maps_To_GDC", {"include": "properties"}),
            ("/mapset/NCIt_Maps_To_GDC/maps", {"pageSize": 2, "fromRecord": 0}),
            ("/mapset/NCIt_Maps_To_MedDRA", {"include": "properties"}),
            ("/mapset/NCIt_Maps_To_MedDRA/maps", {"pageSize": 1, "fromRecord": 0}),
            (f"/history/{tv}/C12345/replacements", None),
        ]:
            try:
                misc[path] = await fetch(c, path, params)
            except httpx.HTTPStatusError as exc:
                misc[path] = {"_error": exc.response.status_code}
            print("fetched", path)
        (out / "misc_endpoints.json").write_text(json.dumps({"_note": "recorded; keys are URL paths", "_recorded": stamp, **misc}, indent=2) + "\n")
        print("NOTE: tests/conftest.py routes by release 26.10d; update FakeEvs if the recorded release differs:", release)


CADSR = "https://cadsrapi.cancer.gov"


async def main_cadsr(out: Path) -> None:
    """Record the caDSR fixtures (no credentials needed for these routes). Slow: a CDE is 6-10 s."""
    out.mkdir(parents=True, exist_ok=True)
    stamp = {"recordedAt": datetime.now(UTC).isoformat(), "base": CADSR}
    async with httpx.AsyncClient(base_url=CADSR, timeout=90, headers={"Accept": "application/json"}) as c:
        de = await fetch(c, "/rad/NCIAPI/1.0/api/DataElement/2192199", {"version": "1.0"})
        (out / "data_element_2192199_v1.json").write_text(json.dumps({"_note": "GET DataElement/2192199?version=1.0", "_recorded": stamp, "data": de}, indent=2) + "\n")
        print("wrote data_element_2192199_v1.json")
        misc: dict = {"_note": "recorded; keys are URL paths (+query for Concept/DataElements)", "_recorded": stamp}
        for key, path, params in [
            ("/rad/NCIAPI/1.0/api/DataElements?publicId=2192199", "/rad/NCIAPI/1.0/api/DataElements", {"publicId": "2192199"}),
            ("/rad/NCIAPI/1.0/api/DataElements/Concept?conceptCode=C17049", "/rad/NCIAPI/1.0/api/DataElements/Concept", {"conceptCode": "C17049", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElements/Concept?conceptCode=C17049&itemTypeFilter=Property", "/rad/NCIAPI/1.0/api/DataElements/Concept", {"conceptCode": "C17049", "itemTypeFilter": "Property", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElements/Concept?conceptCode=C99999", "/rad/NCIAPI/1.0/api/DataElements/Concept", {"conceptCode": "C99999", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElement/9999999", "/rad/NCIAPI/1.0/api/DataElement/9999999", None),
            ("/rad/NCIAPI/1.0/api/DataElements/AlternateName", "/rad/NCIAPI/1.0/api/DataElements/AlternateName", {"name": "race", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElements/ReferenceDocument", "/rad/NCIAPI/1.0/api/DataElements/ReferenceDocument", {"text": "race", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElements/Context", "/rad/NCIAPI/1.0/api/DataElements/Context", {"context": "NCIP", "headerOnly": "true"}),
            ("/rad/NCIAPI/1.0/api/DataElements/getCRDCList", "/rad/NCIAPI/1.0/api/DataElements/getCRDCList", None),
            ("/rad/NCIFormAPI.v2_0:NciFormApiRad/Form/3105395", "/rad/NCIFormAPI.v2_0:NciFormApiRad/Form/3105395", None),
            ("/rad/caDSR.restapi:GetJSON_rad/GetJSON", "/rad/caDSR.restapi:GetJSON_rad/GetJSON", {"query": "Question&DataElement[@publicId=2192199,@version=1.0]"}),
        ]:
            try:
                misc[key] = await fetch(c, path, params)
            except httpx.HTTPStatusError as exc:
                misc[key] = {"_error": exc.response.status_code}
            print("fetched", key)
        (out / "misc_endpoints.json").write_text(json.dumps(misc, indent=2) + "\n")
        print("NOTE: compare recorded parameter names against the [verify] markers in src/evs_cadsr_mcp/cadsr/client.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=None)
    ap.add_argument("--out", default="tests/fixtures/evs", type=Path)
    ap.add_argument("--cadsr", action="store_true", help="record caDSR fixtures into tests/fixtures/cadsr instead")
    a = ap.parse_args()
    if a.cadsr:
        asyncio.run(main_cadsr(Path("tests/fixtures/cadsr") if str(a.out) == "tests/fixtures/evs" else a.out))
    else:
        asyncio.run(main(a.release, a.out))
