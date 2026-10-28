"""Authorized scheduling workflow. Operational writes stay in ServicePlan's own store."""

import hashlib, json, os, secrets
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd
from .config import DATA, POLICY
from .storage import SQLiteStore, PostgresStore, StorageError
from .auth import UserConfig, hash_password, verify_password
from .catalog import recommendation
from .schedule import validate_tasks, validate_parts

SCHEMA = """
create table if not exists meta(key text primary key,value text);
create table if not exists customers(customer_id text primary key,customer_name text);
create table if not exists vehicles(vehicle_id text primary key,customer_id text references customers,model_id text,country text,city text,current_km double precision,last_date text,data_status text,precoverage_unknown integer);
create table if not exists packages(package_id text primary key,definition text);
create table if not exists model_catalog(model_id text primary key,snapshot text);
create table if not exists users(user_id text primary key,email text unique,display_name text,role text check(role in ('admin','customer')),customer_id text references customers,password_hash text,enabled integer default 1);
create table if not exists sessions(token_hash text primary key,user_id text references users,expires_at text);
create table if not exists login_attempts(email text primary key,failures integer,last_at text);
create table if not exists occurrences(maintenance_id text primary key,vehicle_id text references vehicles,target_km integer,service_level integer,packages text,first_reached_date text,previous_date text,deadline_date text,crossing_gap_days integer,precision text,policy text,unique(vehicle_id,target_km,policy));
create table if not exists service_events(event_id text primary key,maintenance_id text references occurrences,service_date text,odometer_km double precision,decision text,tasks text,parts text,source text,reason text);
create table if not exists completions(maintenance_id text primary key references occurrences,event_id text unique,completed_at text,odometer_km double precision,late integer,packages text,source text);
create table if not exists task_records(maintenance_id text references occurrences,task_id text,package_id text,state text,reason text,event_id text,primary key(maintenance_id,task_id));
create table if not exists export_requests(maintenance_id text primary key references occurrences,state text,attempts integer,error text,snapshot text,customer_id text,requested_at text);
create table if not exists work_orders(order_id text primary key,maintenance_id text unique references occurrences,customer_id text references customers,status text check(status in ('Open','Completed','Rejected')),created_at text,created_by text,snapshot text);
create table if not exists responses(response_id text primary key,order_id text unique references work_orders,user_id text,decision text,service_date text,reported_km double precision,finding text,action text,task_outcomes text,actual_parts text,rating integer check(rating between 1 and 5),notes text,rejection_reason text,submitted_at text,payload text);
create table if not exists evaluations(evaluation_id text primary key,as_of text,source_revision text,policy text,row_count integer,imported_at text);
create table if not exists audit(id integer primary key,at text,kind text,entity_id text,detail text,actor text);
create view if not exists maintenance_reporting as
select o.*,v.customer_id,c.customer_name,v.model_id,v.country,v.city,v.current_km,v.last_date,v.data_status,v.precoverage_unknown,
co.completed_at,co.late,co.source completion_source,co.packages covered_packages,
coalesce(x.state,'Not created') creation_status,w.order_id,w.status work_order_status,w.created_at order_created_at,
r.decision response_decision,r.service_date,r.reported_km,r.finding,r.action,r.task_outcomes,r.actual_parts,r.rating,r.notes,r.rejection_reason,r.submitted_at
from occurrences o left join vehicles v on o.vehicle_id=v.vehicle_id
left join customers c on v.customer_id=c.customer_id
left join completions co on o.maintenance_id=co.maintenance_id
left join export_requests x on o.maintenance_id=x.maintenance_id
left join work_orders w on o.maintenance_id=w.maintenance_id
left join responses r on w.order_id=r.order_id;
"""


class ConflictError(ValueError):
    pass


def now():
    return pd.Timestamp.now(tz="UTC").isoformat()


def encoded(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


def frame_status(f, as_of):
    f = f.copy()
    f["maintenance_status"] = "Upcoming"
    reached = f.first_reached_date.notna()
    f.loc[reached, "maintenance_status"] = "Due"
    f.loc[reached & f.deadline_date.fillna("9999-12-31").le(as_of), "maintenance_status"] = "Overdue"
    f.loc[f.completed_at.notna() & f.completed_at.fillna("9999-12-31").le(as_of), "maintenance_status"] = (
        "Completed"
    )
    f["remaining_km"] = (f.target_km - f.current_km).where(~reached)
    f["km_past_target"] = (f.current_km - f.target_km).clip(lower=0).where(reached)
    f["days_overdue"] = [
        max(0, (pd.Timestamp(d if d else as_of) - pd.Timestamp(deadline)).days) if deadline else 0
        for d, deadline in zip(f.completed_at, f.deadline_date)
    ]
    return f


class Service:
    def __init__(
        self, mode=None, path=None, database_url=None, database_schema=None, data=DATA, auth_config=None
    ):
        self.data = Path(data)
        mode = mode or os.environ.get("SERVICEPLAN_MODE", "hosted")
        self.schema = database_schema or os.environ.get("SERVICEPLAN_DATABASE_SCHEMA", "serviceplan")
        if mode == "local":
            self.db = SQLiteStore(
                path or os.environ.get("SERVICEPLAN_DB", str(self.data.parents[1] / "serviceplan.sqlite"))
            )
            self.db.executescript(SCHEMA)
        elif mode == "hosted":
            url = database_url or os.environ.get("SERVICEPLAN_DATABASE_URL")
            if not url:
                raise StorageError(
                    "ServicePlan hosted mode requires its own Neon PostgreSQL URL. Configure [serviceplan].database_url; local mode must be selected explicitly."
                )
            self.db = PostgresStore(url, self.schema)
            if "meta" not in self.db.tables():
                self.db.close()
                raise StorageError(
                    "ServicePlan database is not initialized. Run the offline ServicePlan migration first."
                )
            version = self.db.execute("select value from meta where key='schema_version'").fetchone()
            if not version or version[0] != "1":
                self.db.close()
                raise StorageError("ServicePlan schema migration is required")
        else:
            raise ValueError("Mode must be hosted or local")
        self.backend = self.db.backend
        self.seed()
        self.as_of = self.db.execute("select value from meta where key='as_of'").fetchone()[0]
        if auth_config is None and os.environ.get("SERVICEPLAN_AUTH_FILE"):
            auth_config = json.loads(Path(os.environ["SERVICEPLAN_AUTH_FILE"]).read_text())
        self.configure_users(auth_config)

    @contextmanager
    def atomic(self):
        with self.db.transaction():
            yield

    def log(self, kind, entity, detail, actor="system"):
        self.db.execute(
            "insert into audit(at,kind,entity_id,detail,actor) values (?,?,?,?,?)",
            (now(), kind, entity, encoded(detail), actor),
        )

    def seed(self):
        m = json.loads((self.data / "manifest.json").read_text())
        finger = hashlib.sha256((self.data / "manifest.json").read_bytes()).hexdigest()
        with self.atomic():
            old = self.db.execute("select value from meta where key='reference_hash'").fetchone()
            if old and old[0] == finger:
                return
            # Every source checksum is checked before writing any reference records.
            for name, sha in m["sha256"].items():
                if hashlib.sha256((self.data / name).read_bytes()).hexdigest() != sha:
                    raise ValueError("Prepared reference checksum mismatch")
            existing = self.db.execute("select value from meta where key='as_of'").fetchone()
            if existing and existing[0] != m["as_of"]:
                raise ValueError(
                    "A different demonstration clock requires an explicit offline migration; history was preserved"
                )
            a = pd.read_parquet(self.data / "assets.parquet")
            o = pd.read_parquet(self.data / "occurrences.parquet")
            events = pd.read_parquet(self.data / "service_history.parquet")
            self.db.executemany(
                "insert into customers values (?,?) on conflict(customer_id) do update set customer_name=excluded.customer_name",
                list(
                    a[["customer_id", "customer_name"]].drop_duplicates().itertuples(index=False, name=None)
                ),
            )
            self.db.executemany(
                "insert into vehicles values (?,?,?,?,?,?,?,?,?) on conflict(vehicle_id) do update set current_km=excluded.current_km,last_date=excluded.last_date,data_status=excluded.data_status",
                [
                    (
                        r.vehicle_id,
                        r.customer_id,
                        r.model_id,
                        r.country,
                        r.city,
                        r.current_km,
                        r.last_date,
                        r.data_status,
                        int(r.precoverage_unknown),
                    )
                    for r in a.itertuples()
                ],
            )
            catalogs = json.loads((self.data / "catalog.json").read_text())
            self.db.executemany(
                "insert into model_catalog values (?,?) on conflict(model_id) do update set snapshot=excluded.snapshot",
                [(k, encoded(v)) for k, v in catalogs.items()],
            )
            from .catalog import TASKS

            self.db.executemany(
                "insert into packages values (?,?) on conflict(package_id) do update set definition=excluded.definition",
                [(k, encoded(v)) for k, v in TASKS.items()],
            )
            cols = [
                "maintenance_id",
                "vehicle_id",
                "target_km",
                "service_level",
                "packages",
                "first_reached_date",
                "previous_date",
                "deadline_date",
                "crossing_gap_days",
                "precision",
            ]
            values = [
                [None if pd.isna(v) else v for v in row] + [POLICY]
                for row in o[cols].itertuples(index=False, name=None)
            ]
            self.db.executemany(
                "insert into occurrences values (?,?,?,?,?,?,?,?,?,?,?) on conflict(maintenance_id) do nothing",
                values,
            )
            # Validate explicit synthetic package history; never turn generic inspections into completion.
            model = a.set_index("vehicle_id").model_id.to_dict()
            occ = o.set_index("maintenance_id").to_dict("index")
            ev = []
            co = []
            tr = []
            protected = {r[0] for r in self.db.execute("select maintenance_id from work_orders").fetchall()}
            for r in events.itertuples():
                if r.maintenance_id in protected:
                    continue
                snap = recommendation(model[r.vehicle_id], int(occ[r.maintenance_id]["target_km"]))
                tasks = json.loads(r.tasks)
                parts = json.loads(r.parts)
                if r.decision == "Completed":
                    validate_tasks(snap, tasks)
                    validate_parts(snap, parts)
                    co.append(
                        (
                            r.maintenance_id,
                            r.event_id,
                            r.service_date,
                            r.odometer_km,
                            int(r.service_date >= occ[r.maintenance_id]["deadline_date"]),
                            encoded(snap["packages"]),
                            r.source,
                        )
                    )
                    tr.extend(
                        (
                            r.maintenance_id,
                            t["task_id"],
                            t["package_id"],
                            tasks[t["task_id"]]["state"],
                            tasks[t["task_id"]]["reason"],
                            r.event_id,
                        )
                        for t in snap["tasks"]
                    )
                ev.append(
                    (
                        r.event_id,
                        r.maintenance_id,
                        r.service_date,
                        r.odometer_km,
                        r.decision,
                        r.tasks,
                        r.parts,
                        r.source,
                        r.reason,
                    )
                )
            self.db.executemany(
                "insert into service_events values (?,?,?,?,?,?,?,?,?) on conflict(event_id) do nothing", ev
            )
            self.db.executemany(
                "insert into completions values (?,?,?,?,?,?,?) on conflict(maintenance_id) do nothing", co
            )
            self.db.executemany(
                "insert into task_records values (?,?,?,?,?,?) on conflict(maintenance_id,task_id) do nothing",
                tr,
            )
            for key, value in [("reference_hash", finger), ("as_of", m["as_of"])]:
                self.db.execute(
                    "insert into meta values (?,?) on conflict(key) do update set value=excluded.value",
                    (key, value),
                )
            self.db.execute(
                "insert into evaluations values (?,?,?,?,?,?) on conflict(evaluation_id) do nothing",
                (finger, m["as_of"], m["source_revision"], POLICY, len(o), now()),
            )
            self.log("reference_imported", finger, m["counts"])

    def configure_users(self, config):
        self.auth_mode = "configured" if config is not None else "public_demo"
        if config is None:
            ah = hash_password("serviceplan-admin-demo")
            ch = hash_password("serviceplan-customer-demo")
            config = [
                dict(
                    user_id="SP-admin",
                    email="admin@serviceplan.example",
                    display_name="Demo administrator",
                    role="admin",
                    password_hash=ah,
                )
            ] + [
                dict(
                    user_id="SP-" + r["customer_id"],
                    email=f"customer{r['customer_id'][-4:]}@serviceplan.example",
                    display_name=r["customer_name"],
                    role="customer",
                    customer_id=r["customer_id"],
                    password_hash=ch,
                )
                for r in self.db.execute("select * from customers").fetchall()
            ]
        try:
            users = [UserConfig.model_validate(c) for c in config]
        except (ValueError, TypeError):
            raise ValueError(
                "Invalid private user configuration; verify IDs, roles and generated password hashes"
            ) from None
        customer_ids = {r[0] for r in self.db.execute("select customer_id from customers").fetchall()}
        if (
            len({u.user_id for u in users}) != len(users)
            or len({u.email.lower() for u in users}) != len(users)
            or any(u.customer_id and u.customer_id not in customer_ids for u in users)
        ):
            raise ValueError("Private users require unique IDs/emails and existing customer assignments")
        if not any(u.role == "admin" for u in users):
            raise ValueError("Configure at least one administrator")
        with self.atomic():
            if self.auth_mode == "configured":
                self.db.execute("update users set enabled=0")
            statement = "insert into users values (?,?,?,?,?,?,1) on conflict(user_id) " + (
                "do nothing"
                if self.auth_mode == "public_demo"
                else "do update set email=excluded.email,display_name=excluded.display_name,role=excluded.role,customer_id=excluded.customer_id,password_hash=excluded.password_hash,enabled=1"
            )
            self.db.executemany(
                statement,
                [
                    (u.user_id, u.email.lower(), u.display_name, u.role, u.customer_id, u.password_hash)
                    for u in users
                ],
            )

    def login(self, email, password):
        email = email.strip().lower()
        token = None
        with self.atomic():
            old = self.db.execute("select * from login_attempts where email=?", (email,)).fetchone()
            recent = old and (pd.Timestamp(now()) - pd.Timestamp(old["last_at"])).total_seconds() < 300
            if recent and old["failures"] >= 5:
                raise PermissionError("Too many attempts; try again after five minutes")
            user = self.db.execute("select * from users where email=? and enabled=1", (email,)).fetchone()
            if user and verify_password(password, user["password_hash"]):
                token = "sp_" + secrets.token_urlsafe(32)
                self.db.execute(
                    "insert into sessions values (?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        user["user_id"],
                        (pd.Timestamp(now()) + pd.Timedelta(hours=8)).isoformat(),
                    ),
                )
                self.db.execute("delete from login_attempts where email=?", (email,))
                self.log("signed_in", user["user_id"], {}, user["user_id"])
            else:
                self.db.execute(
                    "insert into login_attempts values (?,?,?) on conflict(email) do update set failures=excluded.failures,last_at=excluded.last_at",
                    (email, old["failures"] + 1 if recent else 1, now()),
                )
        if not token:
            raise PermissionError("Sign-in failed. Check your email and password.")
        return token

    def principal(self, token):
        if not isinstance(token, str) or not token.startswith("sp_"):
            raise PermissionError("Sign in to ServicePlan")
        r = self.db.execute(
            "select u.* from users u join sessions s on u.user_id=s.user_id where s.token_hash=? and s.expires_at>? and u.enabled=1",
            (hashlib.sha256(token.encode()).hexdigest(), now()),
        ).fetchone()
        if not r:
            raise PermissionError("Sign in to ServicePlan")
        return {k: r[k] for k in ("user_id", "email", "display_name", "role", "customer_id")}

    def logout(self, token):
        with self.atomic():
            self.db.execute(
                "delete from sessions where token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)
            )

    def admin(self, token):
        u = self.principal(token)
        if u["role"] != "admin":
            raise PermissionError("Administrator access required")
        return u

    def maintenance(self, token):
        self.admin(token)
        return frame_status(
            self.db.frame("select * from maintenance_reporting order by vehicle_id,target_km"), self.as_of
        )

    def item(self, token, mid):
        self.admin(token)
        return self._item(mid)

    def _item(self, mid):
        f = self.db.frame("select * from maintenance_reporting where maintenance_id=?", (mid,))
        if f.empty:
            raise ValueError("Maintenance occurrence not found")
        return (
            frame_status(f, self.as_of)
            .iloc[0]
            .where(pd.notna(frame_status(f, self.as_of).iloc[0]), None)
            .to_dict()
        )

    def orders(self, token):
        u = self.principal(token)
        query = "select m.* from maintenance_reporting m join work_orders w on m.order_id=w.order_id"
        params = ()
        if u["role"] == "customer":
            query += " where w.customer_id=?"
            params = (u["customer_id"],)
        return frame_status(self.db.frame(query + " order by w.created_at desc", params), self.as_of)

    def order(self, token, oid):
        u = self.principal(token)
        r = self.db.execute("select * from work_orders where order_id=?", (oid,)).fetchone()
        if not r or (u["role"] == "customer" and r["customer_id"] != u["customer_id"]):
            raise PermissionError("Order unavailable for this account")
        result = dict(r)
        result["snapshot"] = json.loads(result["snapshot"])
        result["maintenance"] = self._item(r["maintenance_id"])
        r = self.db.execute("select * from responses where order_id=?", (oid,)).fetchone()
        result["response"] = dict(r) if r else None
        return result

    def snapshot(self, item):
        s = recommendation(item["model_id"], int(item["target_km"]))
        s.update(
            customer_id=item["customer_id"],
            vehicle_id=item["vehicle_id"],
            maintenance_id=item["maintenance_id"],
            first_reached_date=item["first_reached_date"],
            deadline_date=item["deadline_date"],
            evidence_as_of=self.as_of,
            current_km=item["current_km"],
        )
        return s

    def create_order(self, token, mid, fail_export=False):
        u = self.admin(token)
        with self.atomic():
            old = self.db.execute(
                "select order_id from work_orders where maintenance_id=?", (mid,)
            ).fetchone()
            if old:
                return dict(ok=True, order_id=old[0])
            item = self._item(mid)
            if item["maintenance_status"] not in ("Due", "Overdue") or item["data_status"] != "Known":
                raise ValueError(
                    "Only reached, unfulfilled occurrences with known current data can create an order"
                )
            request = self.db.execute(
                "select * from export_requests where maintenance_id=?", (mid,)
            ).fetchone()
            if not request:
                self.db.execute(
                    "insert into export_requests values (?,'Pending',0,null,?,?,?)",
                    (mid, encoded(self.snapshot(item)), item["customer_id"], now()),
                )
            self.db.execute(
                "update export_requests set state='Pending',attempts=attempts+1,error=null where maintenance_id=?",
                (mid,),
            )
            if fail_export:
                self.db.execute(
                    "update export_requests set state='Failed',error='Mock receiver temporarily unavailable' where maintenance_id=?",
                    (mid,),
                )
                self.log("export_failed", mid, {}, u["user_id"])
                return dict(ok=False, error="Could not create the order. Retry this occurrence.")
            request = self.db.execute(
                "select * from export_requests where maintenance_id=?", (mid,)
            ).fetchone()
            oid = "SP-WO-" + hashlib.sha256(mid.encode()).hexdigest()[:14].upper()
            self.db.execute(
                "insert into work_orders values (?,?,?,'Open',?,?,?)",
                (oid, mid, request["customer_id"], now(), u["user_id"], request["snapshot"]),
            )
            self.db.execute("update export_requests set state='Created' where maintenance_id=?", (mid,))
            self.log("order_created", oid, dict(maintenance_id=mid), u["user_id"])
            return dict(ok=True, order_id=oid)

    def evidence(self, token, mid, order_id=None):
        if self.principal(token)["role"] == "admin":
            item = self.item(token, mid)
        else:
            order = self.order(token, order_id)
            if order["maintenance_id"] != mid:
                raise PermissionError("Evidence does not belong to this order")
            item = order["maintenance"]
        f = pd.read_parquet(
            self.data / "observations.parquet", filters=[("vehicle_id", "==", item["vehicle_id"])]
        )
        return f[f.date <= self.as_of].copy()

    def history(self, token, mid, order_id=None):
        self.evidence(token, mid, order_id)
        return self.db.frame(
            "select * from service_events where maintenance_id=? order by service_date", (mid,)
        )

    def service_context(self, token, oid, day):
        order = self.order(token, oid)
        f = self.evidence(token, order["maintenance_id"], oid).sort_values("date")
        same = f[f.date == str(day)]
        if same.empty:
            raise ValueError("Choose a service date with an actual recorded end-of-day reading")
        before = f[f.date < str(day)]
        return float(before.odometer_km.iloc[-1] if len(before) else same.odometer_km.iloc[0]), float(
            same.odometer_km.iloc[-1]
        )

    def validate_response(self, token, order, payload):
        decision = payload.get("decision")
        day = str(payload.get("service_date", ""))
        rating = payload.get("rating")
        if decision not in ("Completed", "Rejected"):
            raise ValueError("Choose Completed or Rejected")
        if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
            raise ValueError("Rating must be blank or an integer 1–5")
        try:
            day = pd.Timestamp(day).date().isoformat()
        except (ValueError, TypeError):
            raise ValueError("A valid demonstration service/response date is required") from None
        if day > self.as_of or day < order["maintenance"]["first_reached_date"]:
            raise ValueError("Use a date from the observed crossing through the shared demonstration date")
        d = dict(
            decision=decision,
            service_date=day,
            rating=rating,
            notes=str(payload.get("notes") or "").strip(),
            rejection_reason=None,
            reported_km=None,
            finding=None,
            action=None,
            task_outcomes=None,
            actual_parts=None,
        )
        if decision == "Rejected":
            reason = str(payload.get("rejection_reason") or "").strip()
            if not reason:
                raise ValueError("A rejection reason is required")
            d["rejection_reason"] = reason
            return d
        if payload.get("finding") not in (
            "Normal wear",
            "Abnormal wear",
            "No issue",
            "Unknown",
            "Incorrect recommendation",
        ):
            raise ValueError("Select a finding; Unknown is available")
        if payload.get("action") not in ("Scheduled service performed", "Inspection and service performed"):
            raise ValueError("Select the performed service action")
        tasks = validate_tasks(order["snapshot"], payload.get("task_outcomes"))
        parts = validate_parts(order["snapshot"], payload.get("actual_parts"))
        for t in order["snapshot"]["tasks"]:
            if not t["mandatory"]:
                for p in t["parts"]:
                    used = Decimal(parts.get(p["sku"], {}).get("quantity", "0"))
                    if (tasks[t["task_id"]]["state"] == "Done") != (used > 0):
                        raise ValueError("Conditional task and actual consumable must agree")
        try:
            km = Decimal(str(payload.get("reported_km")))
        except InvalidOperation:
            raise ValueError("Report the service odometer") from None
        lo, hi = self.service_context(token, order["order_id"], day)
        if (
            not km.is_finite()
            or km + Decimal("0.000001") < max(Decimal(str(lo)), Decimal(order["maintenance"]["target_km"]))
            or km > Decimal(str(hi)) + Decimal("0.000001")
        ):
            raise ValueError(
                "Reported service odometer must fit the recorded daily bounds and reached target"
            )
        d.update(
            reported_km=float(km),
            finding=payload["finding"],
            action=payload["action"],
            task_outcomes=tasks,
            actual_parts=parts,
        )
        return d

    def respond(self, token, oid, payload):
        u = self.principal(token)
        if u["role"] != "customer":
            raise PermissionError("Only the assigned customer can submit a response")
        order = self.order(token, oid)
        d = self.validate_response(token, order, payload)
        canonical = encoded(d)
        with self.atomic():
            order = self.order(token, oid)
            old = order["response"]
            if old:
                if old["payload"] == canonical:
                    return old["response_id"]
                raise ConflictError("A different final response is already saved. Refresh to review it.")
            if order["status"] != "Open":
                raise ConflictError("This order is already final")
            rid = "SP-RESP-" + hashlib.sha256(oid.encode()).hexdigest()[:16]
            self.db.execute(
                "insert into responses values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    oid,
                    u["user_id"],
                    d["decision"],
                    d["service_date"],
                    d["reported_km"],
                    d["finding"],
                    d["action"],
                    encoded(d["task_outcomes"]) if d["task_outcomes"] is not None else None,
                    encoded(d["actual_parts"]) if d["actual_parts"] is not None else None,
                    d["rating"],
                    d["notes"],
                    d["rejection_reason"],
                    now(),
                    canonical,
                ),
            )
            self.db.execute("update work_orders set status=? where order_id=?", (d["decision"], oid))
            if d["decision"] == "Completed":
                mid = order["maintenance_id"]
                snap = order["snapshot"]
                self.db.execute(
                    "insert into service_events values (?,?,?,?,?,?,?,?,?)",
                    (
                        rid,
                        mid,
                        d["service_date"],
                        d["reported_km"],
                        "Completed",
                        encoded(d["task_outcomes"]),
                        encoded(d["actual_parts"]),
                        "interactive-customer",
                        d["notes"],
                    ),
                )
                self.db.execute(
                    "insert into completions values (?,?,?,?,?,?,?)",
                    (
                        mid,
                        rid,
                        d["service_date"],
                        d["reported_km"],
                        int(d["service_date"] >= snap["deadline_date"]),
                        encoded(snap["packages"]),
                        "interactive-customer",
                    ),
                )
                self.db.executemany(
                    "insert into task_records values (?,?,?,?,?,?)",
                    [
                        (
                            mid,
                            t["task_id"],
                            t["package_id"],
                            d["task_outcomes"][t["task_id"]]["state"],
                            d["task_outcomes"][t["task_id"]]["reason"],
                            rid,
                        )
                        for t in snap["tasks"]
                    ],
                )
            self.log("customer_response_saved", oid, d, u["user_id"])
            return rid

    def audit(self, token):
        self.admin(token)
        return self.db.frame("select * from audit order by id desc limit 100")
