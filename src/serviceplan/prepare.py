"""Offline read-only import from a pinned FleetCare Git revision, plus labelled synthetic service history."""

import argparse, hashlib, io, json, subprocess
from pathlib import Path
from datetime import timedelta
import numpy as np
import pandas as pd
from .config import DATA, ROOT, SOURCE_REVISION, POLICY, MODELS
from .schedule import schedule
from .catalog import recommendation


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def materialize(assets, observations, output=DATA, source=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    as_of = str(observations.date.max())[:10]
    occ = []
    quality = []
    for vehicle, h in observations.groupby("vehicle_id", sort=True):
        records, q = schedule(h, as_of)
        occ.extend(records)
        quality.append(dict(vehicle_id=vehicle, **q))
    a = assets.merge(pd.DataFrame(quality), on="vehicle_id", validate="one_to_one")
    f = (
        pd.DataFrame(occ)
        .sort_values(["first_reached_date", "vehicle_id", "target_km"], na_position="last")
        .reset_index(drop=True)
    )
    rng = np.random.default_rng(20261028)
    events = []
    model = a.set_index("vehicle_id").model_id.to_dict()
    odo = observations.set_index(["vehicle_id", "date"]).odometer_km
    for r in f[f.first_reached_date.notna()].itertuples():
        draw = rng.random()
        if draw >= 0.23:
            continue
        day = (
            (pd.Timestamp(r.first_reached_date) + timedelta(days=int(rng.integers(0, 15)))).date().isoformat()
        )
        if day > as_of or (r.vehicle_id, day) not in odo.index:
            continue
        snap = recommendation(model[r.vehicle_id], r.target_km)
        completed = draw < 0.20
        tasks = (
            {
                t["task_id"]: dict(state="Done" if t["mandatory"] else "Not needed", reason="")
                for t in snap["tasks"]
            }
            if completed
            else {}
        )
        parts = (
            {
                p["sku"]: dict(quantity=p["required_quantity"], unit=p["unit"])
                for p in snap["parts"]
                if float(p["required_quantity"]) > 0
            }
            if completed
            else {}
        )
        events.append(
            dict(
                event_id="SYN-" + r.maintenance_id,
                maintenance_id=r.maintenance_id,
                vehicle_id=r.vehicle_id,
                service_date=day,
                odometer_km=float(odo.loc[(r.vehicle_id, day)]),
                decision="Completed" if completed else "Rejected",
                tasks=json.dumps(tasks, sort_keys=True),
                parts=json.dumps(parts, sort_keys=True),
                source="synthetic-package-history-20261028",
                reason="Deterministic fictional prior service"
                if completed
                else "Fictional historical service attempt declined",
            )
        )
    tables = {
        "assets": a,
        "observations": observations,
        "occurrences": f,
        "service_history": pd.DataFrame(events),
    }
    for name, frame in tables.items():
        frame.to_parquet(output / f"{name}.parquet", index=False, compression="zstd")
    catalog = {m: recommendation(m, 10000) for m in MODELS}
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2))
    manifest = dict(
        policy=POLICY,
        as_of=as_of,
        source_revision=SOURCE_REVISION,
        source=source or {},
        seed=20261028,
        synthetic=True,
        counts={k: len(v) for k, v in tables.items()},
        customers=int(a.customer_id.nunique()),
        sha256={
            p.name: digest(p)
            for p in sorted(output.iterdir())
            if p.suffix in (".parquet", ".json") and p.name != "manifest.json"
        },
        precoverage="Milestones at/below the first observed counter have unknown crossing/service history and are not fabricated.",
        precision="Daily first-observed dates, not intraday crossing times",
    )
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fleetcare", type=Path, default=ROOT.parent / "FleetCare-PredictiveMaintenance")
    p.add_argument("--output", type=Path, default=DATA)
    args = p.parse_args()
    blobs = {
        n: subprocess.check_output(
            ["git", "-C", str(args.fleetcare), "show", f"{SOURCE_REVISION}:data/demo/{n}.parquet"]
        )
        for n in ("assets", "daily")
    }
    a = pd.read_parquet(io.BytesIO(blobs["assets"]))[
        ["vehicle_id", "crm_asset_id", "customer_id", "customer_name", "model_id", "country", "city"]
    ]
    o = pd.read_parquet(io.BytesIO(blobs["daily"]))[["vehicle_id", "date", "odometer_km"]]
    o["date"] = o.date.astype(str).str[:10]
    print(
        json.dumps(
            materialize(a, o, args.output, {n: hashlib.sha256(b).hexdigest() for n, b in blobs.items()}),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
