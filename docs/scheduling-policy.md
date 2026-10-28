# Scheduling policy `fixed-km-1`

The policy is deterministic, fictional, lifetime-distance based. There is no ML, fault resolution, forecast, rolling-since-service interval, calendar-triggered service or automatic catch-up/reissue.

## Crossing and fixed targets

`next_target_km = (floor(Decimal(current_km) / 1000) + 1) * 1000`. Negative, NaN and infinite values are rejected. At exactly 5,000, that occurrence is reached while the next future target is 6,000. At 4,200 the future row is 5,000 with 800 remaining; the reached 4,000 row remains a distinct requirement.

Sort observations by date. Emit every integer 1,000 multiple satisfying `previous < target <= current`, rather than relying on equality. A jump from 10,200 to 14,999.5 produces 11k/12k/13k/14k rows on the latter observed date. First-observation targets are not backfilled: 1k–10k earlier history is unknown. Occurrence ID is a stable hash of vehicle, target and policy, independent of execution day.

The next greater target is one upcoming row per trustworthy vehicle. At 5,000 use P5000+P1000; at 10,000 use all three; at 11,000 use P1000. Class hierarchy only resolves shared targets; it is not an urgency ranking across unrelated occurrences.

## Dates and clocks

All source dates have UTC day precision. Store previous observation, first observed reaching target, gap length, deadline and actual completion separately. A large gap means the crossing happened somewhere within those observed bounds. Charts break across missing days. No exact time is inferred.

| Example: first observed 2025-12-24 | State if unfulfilled |
|---|---|
| 2025-12-24 through 2025-12-30 | Due |
| 2025-12-31 00:00 UTC onward | Overdue |
| Valid performed service on 2025-12-31 | Completed, late |

Zero additional driving does not pause this seven-day window. `days_overdue` and `km_past_target` are independent. For completed records, days overdue is measured at completion; otherwise at the shared as-of day. A rejected order leaves the requirement Due/Overdue, while its order status is Rejected.

The immutable imported demonstration clock is 2025-12-31. Initialization refuses an unplanned clock change instead of rewriting saved history. Actual order creation/submission timestamps use current UTC; service dates are validated against the demonstration coverage, not against 2026 creation timestamps. Service odometer must lie within the preceding/latest observed daily bounds, at/above the target; 0.000001 km tolerance allows the UI’s six-decimal report precision. A gap widens observed bounds and is disclosed; it is not an exact workshop measurement.

## Quality and fulfilment

Missing odometers are skipped and counted; zero is never substituted. A duplicate date, invalid/negative/decreasing counter marks the stream Invalid and stops trusted processing at that prefix, with no future row or order eligibility. Last trustworthy observation older than seven days is Stale. No readings is Unknown. Source vehicles are Known in this prepared edition; boundary fixtures exercise the other states.

Only all mandatory tasks reported Done, plus compatible actual required parts, qualify Completed. Conditional washer fluid may be Not needed, Done with an amount, or Omitted/Not applicable with a reason. Rating is optional and does not affect fulfilment. A 10k completion covers all included packages **at that target only**. It cannot mark earlier 1k targets done. Rejection records a reason, no performed work, no completion and no replacement order.

One transaction commits final response, order status, service event, completion, every task coverage record and audit entry. Identical normalized retries return the saved response ID; a different final payload conflicts. The immutable snapshot is also reused after a failed creation retry.
