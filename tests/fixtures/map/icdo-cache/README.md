A pre-seeded ICD-O cache (the layout `map/icdo_sync.py` writes) for offline tests.

The two mapping files are real rows copied from EVS's ICD-O-3.1 files (published 2026-07-11,
CRLF line endings kept), except one test-only row: `9990/3` -> C17649, which the fake EVS
marks retired, so the retired-concept path is exercised. Tests never sync into this
directory (`icdo_sync_interval_s=0`).
