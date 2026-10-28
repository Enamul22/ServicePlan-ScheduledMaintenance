import json, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
from serviceplan.service import Service, ConflictError
from serviceplan.database import migrate
from serviceplan.config import ROOT
from serviceplan.reporting import filter_rows, page_slice
from conftest import create, customer, payload


def test_explicit_idempotent_creation_and_join_filters(shared):
    s, a, target = shared
    f = s.maintenance(a)
    assert f.order_id.isna().all() and f.rating.isna().all()
    assert s.db.execute("select count(*) from export_requests").fetchone()[0] == 0
    r, oid = create(s, a)
    assert s.create_order(a, r["maintenance_id"])["order_id"] == oid
    assert s.db.execute("select count(*) from work_orders").fetchone()[0] == 1
    upcoming = f[f.maintenance_status == "Upcoming"].iloc[0]
    with pytest.raises(ValueError):
        s.create_order(a, upcoming.maintenance_id)
    f = s.maintenance(a)
    assert len(f) == len(f.maintenance_id.unique())
    g = filter_rows(f, {"maintenance_status": "All", "customer_id": "CUS-0000", "service_level": "5000"})
    assert len(g) == 1
    visible, _, pages = page_slice(f, 2, 3)
    assert len(visible) == 3 and pages > 1
    assert len(pd.read_csv(__import__("io").StringIO(g.to_csv(index=False)))) == len(g)


def test_cross_session_completion_atomic_and_fixed_future(shared, monkeypatch):
    s, a, target = shared
    r, oid = create(s, a)
    other = Service(**target)
    c = customer(other, r)
    wrong = other.login("customer0001@serviceplan.example", "serviceplan-customer-demo")
    for fn in [
        lambda: other.order(wrong, oid),
        lambda: other.evidence(wrong, r["maintenance_id"], oid),
        lambda: other.respond(wrong, oid, {}),
        lambda: other.maintenance(c),
        lambda: other.create_order(c, r["maintenance_id"]),
        lambda: other.respond(a, oid, {}),
    ]:
        with pytest.raises(PermissionError):
            fn()
    p = payload(other, c, oid)
    rid = other.respond(c, oid, p)
    assert other.respond(c, oid, p) == rid
    f = s.item(a, r["maintenance_id"])
    assert (
        f["maintenance_status"] == "Completed"
        and f["work_order_status"] == "Completed"
        and f["late"] == 1
        and f["rating"] == 4
        and f["notes"] == p["notes"]
    )
    assert s.db.execute(
        "select count(*) from task_records where maintenance_id=?", (r["maintenance_id"],)
    ).fetchone()[0] == len(other.order(c, oid)["snapshot"]["tasks"])
    assert set(s.maintenance(a).query('maintenance_status=="Upcoming"').target_km) == {10000}
    assert (
        s.item(
            a, s.maintenance(a).query('vehicle_id=="VEH-0001" and target_km==4000').maintenance_id.iloc[0]
        )["maintenance_status"]
        == "Overdue"
    )
    before = other.order(c, oid)["snapshot"]
    monkeypatch.setattr(s, "snapshot", lambda _: dict(changed=True))
    assert s.create_order(a, r["maintenance_id"])["order_id"] == oid
    assert other.order(c, oid)["snapshot"] == before
    with pytest.raises(ConflictError):
        other.respond(c, oid, payload(other, c, oid, notes="different"))
    s.logout(a)
    other.logout(c)
    s.db.close()
    other.db.close()
    fresh = Service(**target)
    a2 = fresh.login("admin@serviceplan.example", "serviceplan-admin-demo")
    c2 = customer(fresh, r)
    assert fresh.order(c2, oid)["response"]["rating"] == 4
    # New process opens the same saved database, reruns initialization and verifies exact fulfilment.
    env = dict(
        os.environ,
        PYTHONPATH=str(ROOT / "src"),
        SP_CHECK_TARGET=json.dumps({k: str(v) for k, v in target.items()}),
        SP_CHECK_ID=oid,
    )
    code = """import json,os
from serviceplan.service import Service
s=Service(**json.loads(os.environ['SP_CHECK_TARGET']));t=s.login('admin@serviceplan.example','serviceplan-admin-demo');o=s.order(t,os.environ['SP_CHECK_ID']);assert o['status']=='Completed' and o['response']['rating']==4 and o['maintenance']['maintenance_status']=='Completed';assert s.db.execute('select count(*) from task_records where maintenance_id=?',(o['maintenance_id'],)).fetchone()[0]>0;print('persisted');s.db.close()"""
    check = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert check.returncode == 0, check.stderr
    assert "persisted" in check.stdout
    if fresh.backend == "postgresql":
        migrate(os.environ["SERVICEPLAN_TEST_POSTGRES_URL"], fresh.schema)
    assert fresh.order(a2, oid)["response"]["response_id"] == rid
    fresh.db.close()


def test_rejection_nulls_and_no_reissue(shared):
    s, a, target = shared
    r, oid = create(s, a)
    c = customer(s, r)
    with pytest.raises(ValueError):
        s.respond(c, oid, dict(decision="Rejected", service_date=s.as_of))
    p = dict(
        decision="Rejected",
        service_date=s.as_of,
        rejection_reason="Not accepted",
        notes="No work performed",
        rating=None,
    )
    rid = s.respond(c, oid, p)
    assert s.respond(c, oid, p) == rid
    r = s.item(a, r["maintenance_id"])
    assert (
        r["maintenance_status"] == "Overdue"
        and r["work_order_status"] == "Rejected"
        and r["actual_parts"] is None
        and r["task_outcomes"] is None
        and r["rating"] is None
    )
    assert (
        s.db.execute(
            "select count(*) from completions where maintenance_id=?", (r["maintenance_id"],)
        ).fetchone()[0]
        == 0
    )
    assert s.create_order(a, r["maintenance_id"])["order_id"] == oid
    s.db.close()
    new = Service(**target)
    a = new.login("admin@serviceplan.example", "serviceplan-admin-demo")
    assert new.order(a, oid)["response"]["rejection_reason"] == "Not accepted"
    new.db.close()


def test_validation_rollback_dates_parts_and_partial(shared, monkeypatch):
    s, a, target = shared
    r, oid = create(s, a)
    c = customer(s, r)
    p = payload(s, c, oid)
    for bad in [
        dict(task_outcomes={}),
        dict(actual_parts={}),
        dict(service_date="2026-01-01"),
        dict(reported_km=100),
        dict(rating=True),
        dict(actual_parts={"SP-WRONG": dict(quantity="1", unit="unit")}),
    ]:
        with pytest.raises(ValueError):
            s.respond(c, oid, {**p, **bad})
    assert s.order(c, oid)["status"] == "Open"
    original = s.log

    def fail(kind, *args, **kwargs):
        if kind == "customer_response_saved":
            raise RuntimeError("Interrupted write")
        original(kind, *args, **kwargs)

    monkeypatch.setattr(s, "log", fail)
    with pytest.raises(RuntimeError):
        s.respond(c, oid, p)
    assert (
        s.order(c, oid)["response"] is None
        and s.item(a, r["maintenance_id"])["maintenance_status"] == "Overdue"
    )
    assert (
        s.db.execute(
            "select count(*) from task_records where maintenance_id=?", (r["maintenance_id"],)
        ).fetchone()[0]
        == 0
    )


def test_fail_create_concurrency_and_conflicting_final(shared):
    s, a, target = shared
    r = s.maintenance(a).query('vehicle_id=="VEH-0001" and target_km==5000').iloc[0].to_dict()
    assert not s.create_order(a, r["maintenance_id"], fail_export=True)["ok"]
    assert s.item(a, r["maintenance_id"])["creation_status"] == "Failed"
    connections = [Service(**target), Service(**target)]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda x: x.create_order(a, r["maintenance_id"]), connections))
    assert len({r["order_id"] for r in results}) == 1
    oid = results[0]["order_id"]
    c = customer(s, r)

    def respond(pair):
        x, n = pair
        try:
            return x.respond(c, oid, payload(x, c, oid, notes=n))
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(respond, zip(connections, ["one", "two"])))
    assert (
        results.count("conflict") == 1 and s.db.execute("select count(*) from responses").fetchone()[0] == 1
    )
    for x in connections:
        x.db.close()
