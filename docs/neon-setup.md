# Neon persistence and manual Streamlit setup

## Permanent target already prepared

Ownership was verified in Enamul Haque’s existing free Frankfurt Neon project **FleetCare** (`old-feather-95627867`, organization `Enamul FDE`). ServicePlan uses a **new, separate PostgreSQL database `serviceplan`, schema `serviceplan`** on the existing default production branch `br-floral-hat-bavf28s9`. It does not use FleetCare’s database, tables, sessions or config. No shared roles, global settings, FleetCare deployment settings or paid plan were changed.

Migration and initialization were first tested on temporary child branch `br-square-band-baovq1li` (`serviceplan-review-20261028`), with its own `serviceplan` database. That review branch expires at 2026-10-28 23:00 UTC and **must not be used for hosting**. Browser/test orders live only there or in isolated fixture schemas. The permanent target was independently migrated/seeded with reference data and zero interactive orders, then reopened through the pooled endpoint. It has no test-branch expiration dependency.

A private handoff file `.env.serviceplan-streamlit.toml` exists only in the developer checkout, ignored by Git, mode 0600. It contains the permanent target’s pooled connection. Do not paste it into an issue, screenshot or chat. `.streamlit/secrets.toml.example` contains placeholders only.

## Manual step for Enamul after review

1. In Streamlit Community Cloud create the app from **Enamul22/ServicePlan-ScheduledMaintenance**, branch **main**, entry point **app.py**, Python **3.12**. This delivery does not create or deploy the hosted app.
2. In that **new ServicePlan app’s** Advanced settings → Secrets, privately copy the complete `[serviceplan]` section from the local ignored `.env.serviceplan-streamlit.toml` file. Do not edit FleetCare’s Secrets. Alternatively obtain the permanent database `serviceplan` pooled connection from Neon Connect and replace the placeholder below.
3. Check database path `/serviceplan`, pooled `-pooler` endpoint, TLS `sslmode=require`, schema `serviceplan` and mode `hosted`.
4. Save/deploy manually. Verify the sidebar says Neon/PostgreSQL and demonstration date 2025-12-31. Create one order, sign in as the assigned customer, submit feedback, sign out/in, choose All, then reboot the app and verify the same response.

```toml
[serviceplan]
mode = "hosted"
database_schema = "serviceplan"
database_url = "postgresql://ROLE:PASSWORD@PERMANENT-ENDPOINT-pooler.eu-central-1.aws.neon.tech/serviceplan?sslmode=require"
```

Environment alternatives: `SERVICEPLAN_MODE=hosted`, `SERVICEPLAN_DATABASE_URL` (pooled), `SERVICEPLAN_DATABASE_SCHEMA=serviceplan`. No generic `DATABASE_URL`/FleetCare secret is read. Missing configuration or a failed connection shows a safe error; it never creates SQLite. The source repository includes all charts/catalogue files required at runtime.

## Offline migrations and repeat initialization

Use a **direct, unpooled** connection, never the application pooler endpoint, for schema migration. Obtain it privately from the same permanent branch/database in Neon. Do not put a URL in shell history:

```sh
source .venv/bin/activate
PYTHONPATH=src python -m serviceplan.database --prompt --schema serviceplan --seed
```

The prompt hides input. Or inject `SERVICEPLAN_DATABASE_URL_DIRECT` privately. Version `001_serviceplan.sql` is idempotent, validates namespace/database isolation, records schema version 1, and refuses unrelated tables or unrecognized versions. Seed imports checksummed reference assets only; existing orders, final responses, task coverage and audit history survive reruns. No automatic operational reseed happens at startup. A clock change requires an explicit future migration.

Neon guidance: [Python/psycopg connection](https://neon.com/docs/guides/python), [connection pooling](https://neon.com/docs/connect/connection-pooling), [secure connections](https://neon.com/docs/connect/connect-securely). App statements use transaction-local search path and no session-dependent prepared statements, compatible with transaction pooling. Remote TLS is mandatory; only disposable localhost CI may disable it.

## Restricting review credentials

Public demo accounts are intentionally documented in README and scoped to fictional customers. To restrict review access, create salted hashes offline:

```sh
PYTHONPATH=src python -m serviceplan.auth
```

Provide a **complete** list of `[[serviceplan.users]]` entries in Secrets (example file), at least one admin plus each desired customer assignment. Or use `SERVICEPLAN_AUTH_FILE` pointing to a private JSON list with those same fields. Configured mode disables omitted users; old sessions cannot bypass a disabled identity. Never commit hashes/private account lists, share sessions, or change passwords through the public UI. Validation errors do not echo private hashes. Sign-out revokes only the current token, not saved workflow records.

## Isolated PostgreSQL testing

`SERVICEPLAN_TEST_POSTGRES_URL` must address a disposable database named `serviceplan_test` or another `serviceplan_*` name. Each test generates and tears down its own `serviceplan_test_*` schema. Optional `SERVICEPLAN_TEST_POOLED_URL` exercises app traffic via pooling while migration stays direct. Neon checks ran on the temporary branch; Actions runs actual PostgreSQL 18 with no private credentials. Do not point tests at FleetCare or use the permanent schema for test fixtures.
