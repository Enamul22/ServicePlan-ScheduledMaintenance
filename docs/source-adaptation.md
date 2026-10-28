# Source and adaptation record

Read-only reference: **Enamul22/FleetCare-PredictiveMaintenance**, latest main verified and pinned at `0f3663e31ea6610eb2a00256ca0d984ebc7c586b` for this build. FleetCare’s local checkout was not pulled, checked out, edited or used as a writable database.

Adapted patterns:

- Reviewed SQLite/psycopg adapter (`storage.py`): named/positional records, bound parameters, transaction-local search path, bounded reconnection before body entry, no write replay, single-writer transaction semantics. ServicePlan adds strict database/schema namespace guards and its own application name.
- PBKDF2/opaque sessions and private account config (`auth.py`); independent users, token prefix, UI state keys and SERVICEPLAN-only configuration. No credential files/passwords/sessions copied.
- Streamlit table/detail/back navigation, two workspaces, explicit saved-history counts and filters, immutable order snapshots, atomic/idempotent final response approach, backend ownership tests. FleetCare anomaly/detector/ML/simulator logic was excluded.

Fleet source `data/demo/assets.parquet` and `daily.parquet` was read with `git show` at the pinned revision. Only vehicle/CRM/customer/model/location and daily odometer fields were retained. Prepared outputs are included for clean-clone use; source SHA256s and output checksums are in the manifest. No FleetCare generic INSPECTION-v1 completion was imported as scheduled service.

Package-specific prior service is generated offline with seed **20261028**, stable sorted iteration and explicit `synthetic-package-history` provenance. Of supported crossings, a deterministic selection receives completed or rejected demonstrations, including late service. Other supported occurrences remain outstanding. No preferred status count is forced. These events are separate from interactive work orders/feedback and contain no invented customer rating. Unknown precoverage milestones remain unknown rather than receiving a fake crossing.

Regeneration requires a read-only FleetCare Git checkout containing the pinned object; runtime does not. Run `PYTHONPATH=src python -m serviceplan.prepare --fleetcare /path/to/checkout` and tests. Byte reproducibility is verified on focused fixtures with the locked pandas/pyarrow stack. Review a new manifest explicitly before importing; the server refuses an unplanned as-of change. No FleetCare live database is queried or modified by preparation.
