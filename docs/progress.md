# Progress / decisions / checks

2026-10-28 (Europe/Helsinki)

- Read the complete ServicePlan contract. Verified Enamul22 account ID 135505234; pinned current reviewed FleetCare main at 0f3663e. Created a separate sibling application; FleetCare checkout remained clean.
- Chose reviewed psycopg adapter, independent schema/database and modest PBKDF2 sessions; no new auth provider/framework or ML. Hosted mode fails closed; SQLite must be explicit.
- Prepared 1,000 vehicles / 201 customers / 365,000 observations and 25,813 stable occurrences; unknown precoverage preserved. Explicit deterministic package history supplies completed/late/rejected examples without synthetic interactive feedback.
- Completed scheduling, catalogue, ownership, immutable order and atomic task/service response flows. A late 5k service leaves the fixed future milestones unchanged. Added saved counts/history shortcut, refresh and separate demonstration/submission clocks.
- Verified isolated real-Neon database before initializing the permanent separate serviceplan database/schema in Enamul’s existing project. No FleetCare table/global role/deployment change. Temporary branch has an expiry; permanent handoff uses the existing default branch.
- Local and PostgreSQL tests exercise concurrency, rollback, retry reconciliation, ownership, snapshot preservation, logout/relogin, fresh Python process and repeated migrations/reference import. Streamlit AppTest checks completion and retained history across sign-in.
- Browser/interface, clean-clone and GitHub CI verification are recorded in verification.md with measured outcomes.
- Deployment intentionally left to Enamul after review; private permanent connection handoff is ignored and permission-restricted.

- Final navigation review preserved administrator sort/date context and customer All-history context across detail/back navigation. Added UI create/reject and invalid-counter inspection checks. Real browser restart retained the exact completed response. Initial GitHub CI passed all 28 tests against PostgreSQL 18; final validation includes the added UI check.
