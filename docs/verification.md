# Verification report

Build date: 2026-10-28. Python 3.12.14, locked dependencies; source FleetCare main `0f3663e31ea6610eb2a00256ca0d984ebc7c586b`.

## Automated checks actually run

- **28 passed, zero skipped** against the real isolated Neon branch, SQLite parity and Streamlit AppTest; elapsed 120.34 seconds. Machine-readable [JUnit report](evidence/neon-tests.xml). No external-secret test was counted as passing when skipped.
- Local-only run: **22 passed, 6 skipped** (the six PostgreSQL variants require an explicit isolated URL). Ruff lint and format checks passed.
- Domain tests: hierarchy/composition, exact and decimal boundaries, 4,200/9,700/25,100 examples, multiple crossings, unknown precoverage, gaps/stale/invalid/decreasing data, no-driving overdue boundary, late service and unchanged future targets, model capacities/units/deduplication, reproducible preparation and full dataset counts/checksums.
- Service tests parameterized for SQLite and real Neon: no automatic orders, one-row joins/null feedback, full-result filtering/pagination/CSV counts, owned evidence/query/write access, forbidden admin impersonation, explicit duplicate-safe creates, failed-create retry, simultaneous creates/conflicting final responses, validation, injected-failure rollback, immutable snapshots and refreshed reference imports preserving interactive fulfilment.
- Persistence regression: separate admin/customer service connections create/complete; both sign out; connections close; new logins read the exact rating/response/task coverage; a new Python subprocess reruns initialization and verifies the same order/fulfilment; direct migration rerun preserves response. Rejected records remain outstanding with no performed tasks/parts and cannot be silently reissued.
- Authentication/storage checks: no hosted fallback, database/schema isolation, TLS validation, private config validation without hash disclosure, password verification, throttling, session revocation, bounded idle reconnection and no uncertain-write replay.
- Streamlit AppTest: safe missing-hosted-config error; separate customer completion form; mandatory tasks/parts/finding/action/rating; sign out/in and View all saved orders; admin readback of the same response with no submit permission.

## Actual Neon targets

Ownership verified against Enamul’s existing project before any mutation. Review database: `serviceplan` / `serviceplan` on temporary branch `br-square-band-baovq1li`. Tests use random `serviceplan_test_*` schemas there, not FleetCare. The complete prepared dataset initialized through a pooled endpoint: **25,813** unique rows, baseline states **19,509 Overdue / 646 Due / 1,000 Upcoming / 4,658 Completed**.

After isolated checks, the permanent dedicated **serviceplan database / serviceplan schema** was initialized on the existing default branch `br-floral-hat-bavf28s9`. A pooled application connection verified the same full reference result and **zero interactive work orders**. It is independent of the temporary branch expiry. Private permanent handoff has mode 0600 and is Git-ignored. No FleetCare database connection/table writes, role changes, resets, checkout edits or hosting changes were performed. FleetCare Git working tree remained clean; remote source main was rechecked unchanged.

## Browser review

Chrome, actual running Streamlit app connected to the **isolated Neon review database**, independent admin/customer tabs:

- Admin full overview: counts, filters, 25-row pagination, CSV, selectable native table; detail/chart for VEH-0008 target 71,000, first observed crossing 2025-01-02, deadline 2025-01-09, model-compatible saved actions/parts.
- Explicit Create produced **SP-WO-A1136050A5FCED**. Separate customer CUS-0001 saw one assigned Open order. Completed form reported every mandatory P1000 task, basic kit 1 unit, wipes 2 units, no unnecessary washer fluid, observed odometer 94,444.619067 km on 2025-12-31, finding No issue, service action, rating **4**, explicit synthetic review note.
- Save showed Completed/late on the exact admin occurrence after Refresh. Customer readback displayed task states, actual parts, exact note and rating. Both accounts signed out.
- A fresh Python process independently verified that browser-created order, response, rating 4, Completed join and four task records. Browser history after actual Streamlit restart is checked below in final delivery evidence.

Screenshots in [screenshots](screenshots/): maintenance-overview.jpg, maintenance-table.jpg, schedule-evidence.jpg, customer-response.jpg and saved-history.jpg. These show fictional records only and no database credentials.

## Clean-clone and GitHub CI

Final clean-clone locked installation, startup and remote CI outcomes are appended after execution. Streamlit hosting is deliberately **not deployed/configured** by this task. Enamul must supply the permanent `[serviceplan]` Secrets to the new app manually as described in [Neon setup](neon-setup.md). No deployment URL or production-host restart is claimed.
