import os, uuid
import pandas as pd
import pytest
from psycopg import sql
from serviceplan.config import DATA
from serviceplan.prepare import materialize
from serviceplan.service import Service
from serviceplan.database import migrate
from serviceplan.storage import PostgresStore


@pytest.fixture(scope="session")
def tiny(tmp_path_factory):
    out = tmp_path_factory.mktemp("prepared")
    a = (
        pd.read_parquet(DATA / "assets.parquet")
        .head(2)[
            ["vehicle_id", "crm_asset_id", "customer_id", "customer_name", "model_id", "country", "city"]
        ]
        .copy()
    )
    a.loc[a.index[1], "customer_id"] = "CUS-0001"
    a.loc[a.index[1], "customer_name"] = "Separate customer"
    rows = []
    for v in a.vehicle_id:
        for day, km in [
            ("2025-12-01", 0.0),
            ("2025-12-02", 1200.0),
            ("2025-12-03", 5100.0),
            ("2025-12-04", 5400.0),
            ("2025-12-31", 9700.0),
        ]:
            rows.append(dict(vehicle_id=v, date=day, odometer_km=km))
    materialize(a, pd.DataFrame(rows), out)
    # This focused fixture starts without historical performance; full-data tests verify seeded history.
    f = pd.read_parquet(out / "service_history.parquet").iloc[:0]
    f.to_parquet(out / "service_history.parquet", index=False, compression="zstd")
    import hashlib, json

    m = json.loads((out / "manifest.json").read_text())
    m["counts"]["service_history"] = 0
    m["sha256"]["service_history.parquet"] = hashlib.sha256(
        (out / "service_history.parquet").read_bytes()
    ).hexdigest()
    (out / "manifest.json").write_text(json.dumps(m, indent=2))
    return out


@pytest.fixture(params=["sqlite", "postgresql"])
def shared(request, tmp_path, monkeypatch, tiny):
    if request.param == "sqlite":
        target = dict(mode="local", path=tmp_path / "serviceplan.sqlite", data=tiny)
    else:
        direct = os.environ.get("SERVICEPLAN_TEST_POSTGRES_URL")
        if not direct:
            pytest.skip("Set ServicePlan-only PostgreSQL test URL")
        schema = "serviceplan_test_" + uuid.uuid4().hex[:14]
        migrate(direct, schema)
        target = dict(
            mode="hosted",
            database_url=os.environ.get("SERVICEPLAN_TEST_POOLED_URL", direct),
            database_schema=schema,
            data=tiny,
        )
    s = Service(**target)
    a = s.login("admin@serviceplan.example", "serviceplan-admin-demo")
    try:
        yield s, a, target
    finally:
        s.db.close()
        if request.param == "postgresql":
            db = PostgresStore(direct, schema)
            try:
                db._connect().execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
            finally:
                db.close()


def customer(s, item):
    return s.login(f"customer{item['customer_id'][-4:]}@serviceplan.example", "serviceplan-customer-demo")


def create(s, a, target_km=5000):
    f = s.maintenance(a)
    r = f[(f.target_km == target_km) & (f.vehicle_id == "VEH-0001")].iloc[0].to_dict()
    o = s.create_order(a, r["maintenance_id"])["order_id"]
    return r, o


def payload(s, c, oid, **changes):
    order = s.order(c, oid)
    snap = order["snapshot"]
    _, km = s.service_context(c, oid, s.as_of)
    p = dict(
        decision="Completed",
        service_date=s.as_of,
        reported_km=km,
        finding="No issue",
        action="Scheduled service performed",
        task_outcomes={
            t["task_id"]: dict(state="Done" if t["mandatory"] else "Not needed", reason="")
            for t in snap["tasks"]
        },
        actual_parts={
            p["sku"]: dict(quantity=p["required_quantity"], unit=p["unit"])
            for p in snap["parts"]
            if float(p["required_quantity"]) > 0
        },
        rating=4,
        notes="partial is ordinary feedback",
    )
    p.update(changes)
    return p
