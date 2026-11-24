---
name: run-live-tests
description: Run the evs-cadsr-mcp live test suite against the real NCI EVS API and caDSR stage, using credentials from .env. Use after changing upstream calls, client code, or anything the offline fakes can't prove, or when asked to run live tests.
---

# Run the live tests

Live tests (`pytest -m live`) call the real EVS REST API and caDSR. caDSR must be **stage**;
production caDSR is never used for testing.

## Run

```bash
uv run --no-sync python scripts/run_live_tests.py          # whole live suite (~30 s)
uv run --no-sync python scripts/run_live_tests.py -k gdc   # extra pytest arguments pass through
```

[`scripts/run_live_tests.py`](../../../scripts/run_live_tests.py) loads `.env` with python-dotenv,
refuses to run unless `ECM_CADSR_BASE_URL` contains `stage`, sets `ECM_LIVE=1` and runs pytest.

## Setup (once)

`.env` (git-ignored; copy `.env.example`) needs:

```dotenv
ECM_CADSR_BASE_URL=https://cadsrapi-stage.cancer.gov
ECM_CADSR_USERNAME=<user>          # for the LOV and CDE Match tests
ECM_CADSR_PASSWORD=<password>
```

Don't print or echo these values, and never `source .env` in a shell (it breaks the JSON-list
settings). The tests build `Settings(_env_file=None)`, so values reach them only through the
environment, which the script sets.

## Reading failures

- **Connection errors to `cadsrapi-stage.cancer.gov`** (DNS "nodename nor servname"): stage is
  reachable only on the NIH network or VPN. Check with
  `curl -sS -o /dev/null -w '%{http_code}\n' https://cadsrapi-stage.cancer.gov/`; EVS tests still
  pass off-network.
- **`release_not_available` or changed counts:** EVS publishes monthly and serves only the latest
  few releases, so live numbers drift. Fix assertions that pin a count; don't pin old releases.
- **404 or schema changes from caDSR:** compare against the API, then update the client and
  re-record fixtures with `uv run --no-sync python scripts/record_fixtures.py --cadsr`.

Report the result as `N passed / M failed`, naming each failure and whether it's the network,
upstream drift, or a real regression.
