import json, hashlib
from decimal import Decimal
import pandas as pd
import pytest
from serviceplan.catalog import packages, recommendation
from serviceplan.schedule import next_target, schedule, maintenance_status, validate_parts
from serviceplan.config import DATA
from serviceplan.prepare import materialize


@pytest.mark.parametrize(
    "km,target,pkgs,remaining",
    [
        (4200, 5000, ["P5000", "P1000"], 800),
        (9700, 10000, ["P10000", "P5000", "P1000"], 300),
        (25100, 26000, ["P1000"], 900),
        (5000, 6000, ["P1000"], 1000),
        (999.999999, 1000, ["P1000"], 0.000001),
        (Decimal("1000.001"), 2000, ["P1000"], Decimal("999.999")),
    ],
)
def test_fixed_targets(km, target, pkgs, remaining):
    assert next_target(km) == target
    assert packages(target) == pkgs
    assert abs(Decimal(target) - Decimal(str(km)) - Decimal(str(remaining))) < Decimal(".00000001")
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            next_target(bad)


def h(values, dates=None):
    return pd.DataFrame(
        dict(
            vehicle_id="TEST",
            date=dates or pd.date_range("2025-01-01", periods=len(values)),
            odometer_km=values,
        )
    )


def test_crossings_no_equality_precoverage_gaps_no_drive():
    f, q = schedule(h([10200, 14999.5, 16100], ["2025-01-01", "2025-01-03", "2025-01-10"]), "2025-01-10")
    assert [r["target_km"] for r in f] == [11000, 12000, 13000, 14000, 15000, 16000, 17000]
    assert f[0]["first_reached_date"] == "2025-01-03" and f[0]["crossing_gap_days"] == 2
    assert q["precoverage_unknown"] and all(r["target_km"] > 10200 for r in f)
    r = f[0]
    assert maintenance_status(r, "2025-01-09") == "Due"
    assert maintenance_status(r, "2025-01-10") == "Overdue"
    assert maintenance_status(r, "2025-01-10", "2025-01-10") == "Completed"
    assert schedule(h([0, 1100, 1100]), "2025-01-03")[0][0]["first_reached_date"] == "2025-01-02"
    assert maintenance_status(schedule(h([0, 1100, 1100]), "2025-01-03")[0][0], "2025-01-09") == "Overdue"


def test_invalid_missing_stale_and_stable_ids():
    r, q = schedule(h([0, 1100, 100]), "2025-01-03")
    assert q["data_status"] == "Invalid" and q["current_km"] is None and [x["target_km"] for x in r] == [1000]
    r, q = schedule(h([0, None, 1100]), "2025-01-20")
    assert (
        q["data_status"] == "Stale"
        and q["missing_readings"] == 1
        and r[0]["first_reached_date"] == "2025-01-03"
    )
    assert schedule(h([None, None]), "2025-01-20")[1]["data_status"] == "Unknown"
    assert schedule(h([0, 5400]), "2025-01-02")[0][-1]["target_km"] == 6000
    assert schedule(h([0, 5400]), "2025-01-02")[0] == schedule(h([0, 5400]), "2025-01-02")[0]


def test_package_inheritance_parts_and_units():
    s = recommendation("ALD", 10000)
    assert len({t["task_id"] for t in s["tasks"]}) == 10
    assert s["packages"] == ["P10000", "P5000", "P1000"]
    p = {x["sku"]: x for x in s["parts"]}
    assert p["SP-ALD-WIPE"]["quantity"] == "5"
    assert p["SP-ALD-OIL"]["quantity"] == "3.5"
    assert p["SP-ALD-PLUG"]["unit"] == "set"
    assert recommendation("ELM", 5000)["parts"][0]["quantity"] == "6.3"
    actual = {
        x["sku"]: dict(quantity=x["required_quantity"], unit=x["unit"])
        for x in s["parts"]
        if Decimal(x["required_quantity"]) > 0
    }
    assert validate_parts(s, actual)["SP-ALD-OIL"]["quantity"] == "3.5"
    actual["SP-ALD-OIL"]["unit"] = "unit"
    with pytest.raises(ValueError):
        validate_parts(s, actual)


def test_full_data_source_counts_and_integrity():
    m = json.loads((DATA / "manifest.json").read_text())
    assert m["counts"]["assets"] == 1000 and m["customers"] == 201 and m["counts"]["observations"] == 365000
    for name, sha in m["sha256"].items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == sha
    a = pd.read_parquet(DATA / "assets.parquet")
    o = pd.read_parquet(DATA / "occurrences.parquet")
    obs = pd.read_parquet(DATA / "observations.parquet")
    hist = pd.read_parquet(DATA / "service_history.parquet")
    assert o.maintenance_id.is_unique and o[o.first_reached_date.isna()].vehicle_id.nunique() == 1000
    assert (
        o[o.first_reached_date.notna()]
        .deadline_date.eq(
            (
                pd.to_datetime(o[o.first_reached_date.notna()].first_reached_date) + pd.Timedelta(days=7)
            ).dt.strftime("%Y-%m-%d")
        )
        .all()
    )
    assert hist.decision.eq("Completed").any() and hist.decision.eq("Rejected").any()
    assert obs.groupby("vehicle_id").odometer_km.diff().dropna().ge(0).all()
    assert set(a.model_id) == {"ALD", "BIR", "CED", "ELM"}


def test_preparation_reproducible(tiny, tmp_path):
    a = pd.read_parquet(tiny / "assets.parquet").drop(
        columns=["data_status", "current_km", "last_date", "precoverage_unknown", "missing_readings"]
    )
    obs = pd.read_parquet(tiny / "observations.parquet")
    m1 = materialize(a, obs, tmp_path / "a")
    m2 = materialize(a, obs, tmp_path / "b")
    assert m1 == m2
