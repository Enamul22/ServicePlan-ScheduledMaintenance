# Data dictionary

Prepared files in `data/prepared` have SHA256 values in `manifest.json`. The exact fleet Git revision, original asset/daily blob hashes, policy, generation seed (20261028), as-of date and measured counts are recorded there.

| File | Grain and purpose |
|---|---|
| assets.parquet | 1,000 vehicles: original vehicle/CRM/customer/model/location IDs; latest trusted km/date, quality and precoverage flag |
| observations.parquet | 365,000 vehicle/day observed odometer rows; no inferred future values |
| occurrences.parquet | 25,813 stable vehicle/target/policy rows: service level/packages, observed crossing, previous date, deadline, gap, precision |
| service_history.parquet | 5,355 explicitly synthetic package-specific prior events, including task outcomes, quantities, decision, date, odometer, provenance |
| catalog.json | Model-specific 10k combined proposals; runtime computes each level from incremental tasks |
| manifest.json | Source/quality/clock/provenance/checksum/count contract |

## Persisted ServicePlan tables

| Table | Keys / principal fields |
|---|---|
| meta | key/value; schema version, reference hash, immutable demo as_of |
| customers | customer_id (201), fictional customer_name |
| vehicles | vehicle_id; customer FK, model/country/city, current_km, last_date, data_status, precoverage_unknown |
| packages / model_catalog | Incremental package definitions and model compatibility snapshots as JSON |
| users | user_id, unique email, role, customer assignment, salted password hash, enabled flag |
| sessions / login_attempts | Token hash/user/expiry; email failure count and actual UTC time |
| occurrences | maintenance_id; unique vehicle/target/policy; service level, packages, first_reached_date, previous_date, deadline_date, crossing_gap_days, precision |
| export_requests | One per occurrence; Not created implicitly, Pending/Created/Failed, attempt count, safe error, immutable snapshot/customer |
| work_orders | order_id; unique maintenance FK; assigned customer, Open/Completed/Rejected, actual creation time/actor, immutable snapshot |
| responses | One final response/order; decision, demonstration service date, reported_km, finding/action, task/part JSON, optional rating/notes, rejection reason, actual submitted_at, canonical idempotency payload |
| service_events | Source-synthetic and interactive-customer performed service provenance, plus historical synthetic rejection demonstrations |
| completions | One qualifying event/occurrence; actual service date, km, late flag, package coverage, provenance |
| task_records | Unique maintenance/task; package, outcome/reason and qualifying event |
| evaluations | Source revision/policy/as_of/import time/result count |
| audit | Actual UTC event time, actor, entity, kind and JSON detail |
| maintenance_reporting (view) | Left joins; exactly one row/occurrence, retains null feedback before submission |

`maintenance_status` is calculated as Upcoming/Due/Overdue/Completed using the persisted clock and completion. `creation_status`, `work_order_status` and `data_status` are independent. Remaining km belongs only to Upcoming; km past target belongs to reached rows; days overdue is calculated separately. `completed_at` is a service **date**, not the order submission timestamp. No `resolved_fault` or fabricated accuracy field exists.

Snapshots include included packages, unique task IDs/package/mandatory flags, model-compatible SKU requirements, explicit proposed/required quantities and units, fixed policy/target/customer and evidence as-of. Decimal amounts serialize as strings. Units are `L`, `unit` or `set`; unit/set quantities must be whole numbers. Ratings and response fields remain null until a customer submits them; prior synthetic service events do not invent ratings.
