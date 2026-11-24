"""Run the live test suite (EVS + caDSR) with settings from .env.

Refuses to run unless ECM_CADSR_BASE_URL points at caDSR *stage*: live tests must
never hit production caDSR. .env is read with python-dotenv rather than `source .env`,
which mangles the JSON-list settings.

    uv run --no-sync python scripts/run_live_tests.py            # whole live suite
    uv run --no-sync python scripts/run_live_tests.py -k gdc     # extra pytest args pass through
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    env_file = ROOT / ".env"
    if env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                os.environ[key] = value
    # The default caDSR URL is production, so stage must be set explicitly.
    base = os.environ.get("ECM_CADSR_BASE_URL", "")
    if "stage" not in base:
        print("refusing to run: set ECM_CADSR_BASE_URL to caDSR stage (e.g. https://cadsrapi-stage.cancer.gov) "
              f"in .env; got {base or 'the production default'}", file=sys.stderr)
        return 2
    os.environ["ECM_LIVE"] = "1"
    os.chdir(ROOT)
    return pytest.main(["-m", "live", "-p", "no:cacheprovider", "-q", *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
