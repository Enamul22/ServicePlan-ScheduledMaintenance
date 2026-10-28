import pytest
import psycopg
from serviceplan.service import Service
from serviceplan.storage import PostgresStore, StorageError, validate_url
from serviceplan.auth import hash_password, verify_password


def test_hosted_no_fallback_isolation_tls(monkeypatch):
    monkeypatch.delenv("SERVICEPLAN_DATABASE_URL", raising=False)
    with pytest.raises(StorageError, match="requires its own"):
        Service(mode="hosted")
    for url, schema in [
        ("postgresql://a:b@example.com/neondb?sslmode=require", "serviceplan"),
        ("postgresql://a:b@example.com/serviceplan?sslmode=require", "fleetcare"),
        ("postgresql://a:b@example.com/serviceplan?sslmode=disable", "serviceplan"),
    ]:
        with pytest.raises(StorageError):
            PostgresStore(url, schema)
    assert validate_url("postgresql://a:b@localhost/serviceplan_test?sslmode=disable") == "disable"


def test_private_users_hash_throttling_revocation(tmp_path, tiny):
    h = hash_password("private-test-only")
    assert verify_password("private-test-only", h) and not verify_password("wrong", h)
    cfg = [
        dict(
            user_id="owner", email="owner@example.test", display_name="Owner", role="admin", password_hash=h
        ),
        dict(
            user_id="client",
            email="client@example.test",
            display_name="Client",
            role="customer",
            customer_id="CUS-0000",
            password_hash=h,
        ),
    ]
    s = Service(mode="local", path=tmp_path / "auth.sqlite", data=tiny, auth_config=cfg)
    assert s.auth_mode == "configured"
    with pytest.raises(PermissionError):
        s.login("admin@serviceplan.example", "serviceplan-admin-demo")
    t = s.login("client@example.test", "private-test-only")
    assert s.principal(t)["customer_id"] == "CUS-0000"
    assert s.db.execute("select token_hash from sessions").fetchone()[0] != t
    s.logout(t)
    with pytest.raises(PermissionError):
        s.principal(t)
    for _ in range(5):
        with pytest.raises(PermissionError):
            s.login("client@example.test", "wrong")
    with pytest.raises(PermissionError, match="Too many"):
        s.login("client@example.test", "private-test-only")
    with pytest.raises(ValueError, match="Invalid private") as exc:
        s.configure_users([dict(password_hash="SECRET_DO_NOT_ECHO")])
    assert "SECRET_DO_NOT_ECHO" not in str(exc.value)
    with pytest.raises(ValueError, match="unique"):
        s.configure_users(cfg + cfg)
    s.db.close()


def test_reference_refresh_preserves_interactive_final(shared):
    from conftest import create, customer, payload

    s, a, _ = shared
    r, oid = create(s, a)
    c = customer(s, r)
    rid = s.respond(c, oid, payload(s, c, oid))
    snapshot = s.order(c, oid)["snapshot"]
    with s.atomic():
        s.db.execute("update meta set value='refresh-request' where key='reference_hash'")
    s.seed()
    assert s.order(c, oid)["response"]["response_id"] == rid
    assert s.order(c, oid)["snapshot"] == snapshot
    assert s.item(a, r["maintenance_id"])["maintenance_status"] == "Completed"


def test_postgres_reconnect_read_and_write_boundary():
    # Lost idle connection is retried before yielding; an uncertain write body is never replayed.
    from contextlib import contextmanager

    class Conn:
        closed = False

        def __init__(self, fail):
            self.fail = fail

        @contextmanager
        def transaction(self):
            yield

        def execute(self, *args):
            if self.fail:
                self.fail = False
                raise psycopg.OperationalError("stale idle socket")

        def close(self):
            self.closed = True

    db = PostgresStore("postgresql://x:y@example.test/serviceplan?sslmode=require")
    conns = [Conn(True), Conn(False)]
    db._connect = lambda: conns[0] if not conns[0].closed else conns[1]
    entered = []
    with db.transaction():
        entered.append("once")
    assert entered == ["once"] and conns[0].closed
    with pytest.raises(StorageError, match="could not be confirmed"):
        with db.transaction():
            entered.append("uncertain")
            raise psycopg.OperationalError("lost during write")
    assert entered == ["once", "uncertain"]
