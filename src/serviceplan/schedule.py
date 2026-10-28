"""Pure deterministic fixed lifetime-kilometre scheduling, using observed crossings only."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import pandas as pd
from .config import POLICY
from .catalog import level, packages


def next_target(value):
    try:
        x = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Odometer must be a non-negative finite number") from None
    if not x.is_finite() or x < 0:
        raise ValueError("Odometer must be a non-negative finite number")
    return (int((x / 1000).to_integral_value(rounding=ROUND_FLOOR)) + 1) * 1000


def occurrence_id(vehicle, target):
    return "SP-" + hashlib.sha256(f"{vehicle}|{target}|{POLICY}".encode()).hexdigest()[:18]


def schedule(history, as_of):
    """One vehicle. Invalid decreases quarantine current eligibility, never reset the counter."""
    as_of = pd.Timestamp(as_of).date()
    h = history.copy()
    h["date"] = pd.to_datetime(h.date).dt.date
    h = h[h.date <= as_of].sort_values("date")
    if h.empty:
        return [], dict(data_status="Unknown", current_km=None, last_date=None, precoverage_unknown=True)
    rows = []
    previous = None
    invalid = False
    missing = 0
    for r in h.itertuples():
        try:
            km = Decimal(str(r.odometer_km))
        except InvalidOperation:
            km = Decimal("NaN")
        if not km.is_finite():
            missing += 1
            continue
        if km < 0 or (previous and (r.date == previous[0] or km < previous[1])):
            invalid = True
            break
        if previous:
            for target in range(next_target(previous[1]), int(km // 1000) * 1000 + 1, 1000):
                rows.append(
                    dict(
                        maintenance_id=occurrence_id(r.vehicle_id, target),
                        vehicle_id=r.vehicle_id,
                        target_km=target,
                        service_level=level(target),
                        packages=json.dumps(packages(target)),
                        first_reached_date=r.date.isoformat(),
                        previous_date=previous[0].isoformat(),
                        deadline_date=(r.date + timedelta(days=7)).isoformat(),
                        crossing_gap_days=(r.date - previous[0]).days,
                        precision="first observed date (daily end-of-day)",
                    )
                )
        previous = (r.date, km)
    if not previous:
        return [], dict(
            data_status="Invalid" if invalid else "Unknown",
            current_km=None,
            last_date=None,
            precoverage_unknown=True,
        )
    status = "Invalid" if invalid else "Stale" if (as_of - previous[0]).days > 7 else "Known"
    if not invalid:
        target = next_target(previous[1])
        rows.append(
            dict(
                maintenance_id=occurrence_id(h.vehicle_id.iloc[0], target),
                vehicle_id=h.vehicle_id.iloc[0],
                target_km=target,
                service_level=level(target),
                packages=json.dumps(packages(target)),
                first_reached_date=None,
                previous_date=previous[0].isoformat(),
                deadline_date=None,
                crossing_gap_days=None,
                precision="future target; crossing not observed",
            )
        )
    return rows, dict(
        data_status=status,
        current_km=None if invalid else float(previous[1]),
        last_date=previous[0].isoformat(),
        precoverage_unknown=True,
        missing_readings=missing,
    )


def maintenance_status(row, as_of, completed_at=None):
    if completed_at and pd.Timestamp(completed_at).date() <= pd.Timestamp(as_of).date():
        return "Completed"
    if not row["first_reached_date"]:
        return "Upcoming"
    return "Overdue" if pd.Timestamp(as_of).date() >= pd.Timestamp(row["deadline_date"]).date() else "Due"


def validate_parts(snapshot, actual):
    if not isinstance(actual, dict):
        raise ValueError("Report actual parts and quantities")
    proposed = {p["sku"]: p for p in snapshot["parts"]}
    parsed = {}
    for sku, item in actual.items():
        if sku not in proposed or not isinstance(item, dict) or item.get("unit") != proposed[sku]["unit"]:
            raise ValueError("Part/model or unit does not match this saved order")
        try:
            q = Decimal(str(item["quantity"]))
        except (KeyError, InvalidOperation):
            raise ValueError("Invalid part quantity") from None
        if not q.is_finite() or q <= 0 or q > Decimal(proposed[sku]["quantity"]):
            raise ValueError("Part quantity exceeds the saved compatible proposal")
        if item["unit"] in ("unit", "set") and q != q.to_integral_value():
            raise ValueError("Unit and set quantities must be whole numbers")
        parsed[sku] = dict(quantity=str(q.normalize()), unit=item["unit"])
    for sku, p in proposed.items():
        if Decimal(parsed.get(sku, {}).get("quantity", "0")) < Decimal(p["required_quantity"]):
            raise ValueError("Report the required parts/consumables for all mandatory service tasks")
    return parsed


def validate_tasks(snapshot, outcomes):
    if not isinstance(outcomes, dict) or set(outcomes) != {t["task_id"] for t in snapshot["tasks"]}:
        raise ValueError("Report an outcome for every saved task")
    normalized = {}
    for t in snapshot["tasks"]:
        item = outcomes[t["task_id"]]
        if not isinstance(item, dict):
            raise ValueError("Invalid task outcome")
        state = item.get("state")
        reason = str(item.get("reason") or "").strip()
        if t["mandatory"] and state != "Done":
            raise ValueError("All mandatory tasks must be completed before final submission")
        if state not in ("Done", "Not needed", "Omitted", "Not applicable"):
            raise ValueError("Choose a valid task outcome")
        if state in ("Omitted", "Not applicable") and not reason:
            raise ValueError("Explain omitted/not-applicable conditional tasks")
        normalized[t["task_id"]] = dict(state=state, reason=reason)
    return normalized
