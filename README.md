# ServicePlan — Scheduled Maintenance

A fleet service desk by **Enamul Haque**, built with Streamlit, Python and durable Neon PostgreSQL storage. Review fixed kilometre milestones, explicitly create a work order, and let the assigned customer report completed service or rejection. Saved orders, feedback and task coverage survive sign-out and app restart.

This independent portfolio application uses a fictional fleet and fictional schedules, tasks and parts. It makes no claim of manufacturer approval, predictive accuracy, savings or suitability for real vehicles. Version **1.0.0**.

![Maintenance overview](docs/screenshots/maintenance-overview.jpg)

## Workflow

1. Sign in as administrator. **Maintenance overview** shows all observed outstanding milestones plus each vehicle’s next upcoming milestone. Search/filter the complete dataset; download all matching records, independently of the 25-row display pages.
2. Select a row. Review **Usage & schedule evidence**, **Recommended actions**, and **Parts & consumables**. The chart shows that vehicle’s actual prepared daily odometer readings, target and first observed crossing.
3. For a reached, outstanding occurrence, select **Create work order**. Creation is explicit and duplicate-safe; the order saves its recommendation, evidence date, target, policy, customer, tasks and parts.
4. Sign in separately as the assigned customer. **Work order overview** shows only that customer’s orders. Open an order and select Completed or Rejected.
5. Completed requires every mandatory task, compatible parts/units/amounts, an observed service-date/odometer context, finding and action. Washer fluid is conditional; no issue need not consume it. Rejection requires a reason and records no performed service. Rating is optional.
6. Sign out and back in. Open is the initial filter; **View all saved orders**, Completed, Rejected and All expose retained history. Refresh rereads the shared database. The administrator sees the same response on the same maintenance occurrence.

![Schedule evidence](docs/screenshots/schedule-evidence.jpg)
![Customer service response](docs/screenshots/customer-response.jpg)
![Retained completed history](docs/screenshots/saved-history.jpg)
![Saved service feedback after restart](docs/screenshots/saved-feedback.jpg)

## Schedules and data

Targets are lifetime odometer multiples of 1,000 km. At a shared target, the largest applicable level labels **one** combined occurrence/order:

| Target | Packages |
|---|---|
| Divisible by 10,000 | P10000 + P5000 + P1000 |
| Otherwise divisible by 5,000 | P5000 + P1000 |
| Other 1,000 multiples | P1000 |

P1000 is inspection/basic consumables; P5000 adds oil, filter, sealing washer and findings; P10000 adds air filter, plug set and extended inspection. Packages are incremental. A unique task is included once; genuinely distinct tasks consuming wipes sum their quantities. Liquids use decimal litres. See [catalogue](docs/catalogue.md).

`next_target = (floor(current_km / 1000) + 1) * 1000`. At 4,200 → 5,000 (800 remaining); 9,700 → 10,000 (300); 25,100 → 26,000 (900). Completion at 5,400 does not move the 6,000 target. Major service does not fulfil earlier missed occurrences.

A crossing is `previous < target <= current`, enumerating all crossed targets. Due begins on the first observed crossing day. **Completion deadline = crossing + 7 calendar days; Overdue starts at 00:00 UTC on the deadline**, including days without driving. Completed records its actual service day and lateness separately. Rejection leaves the requirement outstanding. Upcoming has no crossing or deadline.

The shared server demonstration date is **2025-12-31**. It controls eligibility, status and allowed service dates; real submission/audit timestamps are recorded separately. Daily readings establish an observation date, not an exact intraday crossing time. Milestones already below the first available reading have unknown earlier history. Resets/decreases are quarantined; missing/stale counters are explicit and cannot create orders. See [policy](docs/scheduling-policy.md).

Prepared data: **1,000 vehicles, 201 customers, 365,000 daily observations, 25,813 occurrences** (24,813 reached + 1,000 upcoming). Fleet source: [FleetCare](https://github.com/Enamul22/FleetCare-PredictiveMaintenance), pinned main revision `0f3663e31ea6610eb2a00256ca0d984ebc7c586b`. No FleetCare operational database or sessions are copied. An explicit seeded package-specific history contains 5,355 synthetic events: 4,658 Completed and 697 Rejected. These are source demonstrations, **not customer feedback or ratings**. Baseline maintenance status: 19,509 Overdue, 646 Due, 1,000 Upcoming, 4,658 Completed. Interactive responses are initially empty.

## Run locally

Python **3.12** (verified 3.12.14):

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
SERVICEPLAN_MODE=local streamlit run app.py
```

Explicit local mode uses a persistent `serviceplan.sqlite` in the project directory (ignored by Git). Override with `SERVICEPLAN_DB=/absolute/path/serviceplan.sqlite`. It is clearly labelled in the UI. Prepared Parquet assets are included: no FleetCare checkout, generation job, private file, paid API or ML key is needed to run the clean clone.

Default **hosted** mode requires a valid configured PostgreSQL URL and initialized ServicePlan schema. Missing/unavailable configuration fails safely; it never substitutes SQLite or a new browser-specific store. Neon has already been verified and a permanent separate ServicePlan database initialized; see [manual hosting setup](docs/neon-setup.md). Streamlit has **not** been deployed.

### Synthetic demonstration sign-ins

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@serviceplan.example` | `serviceplan-admin-demo` |
| Assigned customer | `customerXXXX@serviceplan.example` for `CUS-XXXX` | `serviceplan-customer-demo` |

These are public, fictional portfolio accounts. Find the customer ID on the selected occurrence. Customer access is enforced in backend queries, evidence and submissions; no role picker grants access. Administrators can inspect orders but cannot respond as customers. For private review, replace the complete account list using generated password hashes as described in [Neon setup](docs/neon-setup.md).

## Verify and regenerate

```sh
python -m pytest -q
ruff check .
ruff format --check .
# Also exercise PostgreSQL; use a separate serviceplan_test database (TLS remotely).
export SERVICEPLAN_TEST_POSTGRES_URL='postgresql://USER:PASSWORD@HOST/serviceplan_test?sslmode=require'
# Optional separate pooled endpoint:
# export SERVICEPLAN_TEST_POOLED_URL='...'
python -m pytest -q
# Rebuild source assets only, against the pinned reference revision:
PYTHONPATH=src python -m serviceplan.prepare --fleetcare /path/to/FleetCare-PredictiveMaintenance
```

Each PG test creates its own `serviceplan_test_*` schema and removes only that disposable fixture. Never point tests at FleetCare. GitHub Actions runs PostgreSQL 18 with disposable loopback-only credentials; no Neon secret is used in CI. [Verification report](docs/verification.md) distinguishes local, actual Neon, browser, clean-clone and remote CI evidence.

[Architecture](docs/architecture.md) · [Data dictionary](docs/data-dictionary.md) · [Source/adaptation](docs/source-adaptation.md) · [Progress log](docs/progress.md)
