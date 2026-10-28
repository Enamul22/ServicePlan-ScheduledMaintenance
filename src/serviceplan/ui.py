"""Two authenticated workspaces with explicit order creation and customer fulfilment."""

import json, math
from datetime import date
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from .config import DATA, MODELS
from .service import Service
from .storage import StorageError
from .reporting import filter_rows, page_slice

LABELS = {
    "maintenance_id": "Maintenance ID",
    "vehicle_id": "Vehicle",
    "customer_id": "Customer ID",
    "customer_name": "Customer",
    "model_id": "Model",
    "country": "Country",
    "city": "City",
    "service_level": "Service (km)",
    "packages": "Included packages",
    "target_km": "Target (km)",
    "current_km": "Latest observed km",
    "remaining_km": "Remaining km",
    "km_past_target": "Km past target",
    "first_reached_date": "First observed crossing",
    "deadline_date": "Completion deadline",
    "days_overdue": "Days overdue",
    "maintenance_status": "Maintenance status",
    "creation_status": "Order creation",
    "order_id": "Work order",
    "work_order_status": "Order status",
    "completed_at": "Service completed",
    "late": "Completed late",
    "data_status": "Usage data",
    "response_decision": "Customer decision",
    "service_date": "Reported service date",
    "finding": "Finding",
    "action": "Action",
    "rating": "Rating",
    "notes": "Notes",
    "rejection_reason": "Rejection reason",
}


def main():
    st.set_page_config(page_title="ServicePlan · Scheduled Maintenance", page_icon="🛠️", layout="wide")
    st.markdown(
        """<style>.block-container{padding-top:4.5rem;max-width:1600px}h1{letter-spacing:-1.2px}[data-testid="stMetric"]{background:#fff;border:1px solid #dce5ea;padding:12px;border-radius:8px}.eyebrow{color:#147d92;font-size:12px;font-weight:700;letter-spacing:2px}</style>""",
        unsafe_allow_html=True,
    )
    if "sp_service" not in st.session_state:
        try:
            try:
                cfg = dict(st.secrets["serviceplan"])
            except (KeyError, StreamlitSecretNotFoundError):
                cfg = {}
            st.session_state.sp_service = Service(
                mode=cfg.get("mode"),
                path=cfg.get("db_path"),
                database_url=cfg.get("database_url"),
                database_schema=cfg.get("database_schema"),
                auth_config=cfg.get("users"),
            )
        except (ValueError, OSError) as e:
            st.error(str(e))
            st.stop()
    s = st.session_state.sp_service
    token = st.session_state.get("sp_token")
    if not token:
        sign_in(s)
        return
    try:
        u = s.principal(token)
    except PermissionError:
        st.session_state.pop("sp_token", None)
        st.rerun()
    except StorageError as e:
        st.error(str(e))
        if st.button("Retry database connection"):
            st.rerun()
        return
    if st.session_state.get("sp_workspace_next"):
        st.session_state.sp_workspace = st.session_state.pop("sp_workspace_next")
    with st.sidebar:
        st.markdown("### 🛠 ServicePlan")
        st.caption("SCHEDULED MAINTENANCE")
        st.write(u["display_name"])
        st.caption("Administrator" if u["role"] == "admin" else "Customer · " + u["customer_id"])
        if u["role"] == "admin":
            workspace = st.radio(
                "Workspace", ["Maintenance overview", "Work order overview"], key="sp_workspace"
            )
        else:
            workspace = "Work order overview"
            st.markdown("**Work order overview**")
        if st.button("Refresh saved changes", key="sp_refresh"):
            st.rerun()
        if st.button("Sign out"):
            try:
                s.logout(token)
            except StorageError as e:
                st.error(str(e))
                return
            s.db.close()
            st.session_state.clear()
            st.rerun()
        st.divider()
        st.caption(
            "Demonstration date: "
            + s.as_of
            + " (UTC). Service dates use this shared 2025 clock; submission time is recorded separately."
        )
        st.caption(
            "Saved history uses Neon/PostgreSQL."
            if s.backend == "postgresql"
            else "Explicit local demo mode · SQLite. Use Neon for hosted persistence."
        )
        st.caption(
            "Independent synthetic portfolio demonstration by Enamul Haque. Fictional maintenance policies, tasks and parts."
        )
    st.markdown('<div class="eyebrow">SERVICEPLAN / SCHEDULED MAINTENANCE</div>', unsafe_allow_html=True)
    try:
        if workspace == "Maintenance overview":
            if st.session_state.get("sp_selected"):
                maintenance_detail(s, token, u)
            else:
                maintenance_overview(s, token)
        else:
            if st.session_state.get("sp_order"):
                order_detail(s, token, u)
            else:
                orders(s, token)
    except (ValueError, PermissionError) as e:
        st.error(str(e))


def sign_in(s):
    a, b = st.columns([1.3, 1])
    with a:
        st.markdown('<div class="eyebrow">SERVICEPLAN / SCHEDULED MAINTENANCE</div>', unsafe_allow_html=True)
        st.title("The next service, clearly planned.")
        st.write(
            "Review fixed kilometre milestones, share maintenance work orders, and retain the customer’s service history."
        )
        st.caption("Independent synthetic portfolio demonstration · Enamul Haque")
    with b:
        st.subheader("Sign in")
        with st.form("sp_signin"):
            email = st.text_input("Email", key="sp_email")
            pw = st.text_input("Password", type="password", key="sp_password")
            submit = st.form_submit_button("Sign in", type="primary")
        if submit:
            try:
                st.session_state.sp_token = s.login(email, pw)
                st.rerun()
            except (PermissionError, StorageError) as e:
                st.error(str(e))
        if s.auth_mode == "public_demo":
            with st.expander("Synthetic demo accounts"):
                st.write("Admin: `admin@serviceplan.example` / `serviceplan-admin-demo`")
                st.write(
                    "Customer: `customerXXXX@serviceplan.example` / `serviceplan-customer-demo`, using CUS-XXXX."
                )
                st.caption(
                    "Public fictional identities. Configure private review credentials to restrict access."
                )


def display(f, cols):
    d = f.reindex(columns=cols).copy()
    if "packages" in d:
        d["packages"] = d.packages.map(lambda x: ", ".join(json.loads(x)))
    if "model_id" in d:
        d["model_id"] = d.model_id.map(MODELS)
    return d.rename(columns=LABELS).astype(object).where(pd.notna(d.rename(columns=LABELS)), "")


def back(key, label):
    if st.button(label):
        st.session_state.pop(key, None)
        st.session_state.sp_epoch = st.session_state.get("sp_epoch", 0) + 1
        st.rerun()


def maintenance_overview(s, t):
    st.title("Maintenance overview")
    st.write("Review observed kilometre milestones and create an order for reached, outstanding service.")
    frame = s.maintenance(t)
    manifest = json.loads((DATA / "manifest.json").read_text())
    st.caption(
        f"{manifest['counts']['assets']:,} vehicles · {manifest['customers']} customers · 2025 daily odometer history · evaluation {s.as_of} UTC"
    )
    saved = st.session_state.get("sp_filters", {})
    filters = {}
    c = st.columns([2, 1])
    filters["search"] = c[0].text_input(
        "Search vehicle, customer, maintenance or order", value=saved.get("search", ""), key="sp_search"
    )
    opts = ["Needs attention & planning", "Upcoming", "Due", "Overdue", "Completed", "All"]
    filters["maintenance_status"] = c[1].selectbox(
        "Maintenance status",
        opts,
        index=opts.index(saved.get("maintenance_status", opts[0])),
        key="sp_status",
    )
    with st.expander("More filters and sorting"):
        cols = st.columns(4)
        for i, (label, col) in enumerate(
            [
                ("Vehicle", "vehicle_id"),
                ("Customer", "customer_id"),
                ("Country", "country"),
                ("Model", "model_id"),
                ("Service level", "service_level"),
                ("Order creation", "creation_status"),
                ("Order status", "work_order_status"),
            ]
        ):
            options = ["All"] + [str(x) for x in sorted(frame[col].dropna().unique())]
            value = str(saved.get(col, "All"))
            filters[col] = cols[i % 4].selectbox(
                label, options, index=options.index(value) if value in options else 0, key="sp_f_" + col
            )
        filters["sort"] = st.selectbox(
            "Sort", ["Oldest outstanding first", "Target km", "Vehicle"], key="sp_sort"
        )
        if st.checkbox("Filter first-observed crossing dates", key="sp_use_dates"):
            dates = st.date_input(
                "Crossing date range (UTC)",
                value=(date(2025, 1, 1), date.fromisoformat(s.as_of)),
                key="sp_dates",
            )
            if len(dates) == 2:
                filters.update(date_from=dates[0].isoformat(), date_to=dates[1].isoformat())
    if filters != saved:
        st.session_state.sp_page = 1
        st.session_state.sp_page_epoch = st.session_state.get("sp_page_epoch", 0) + 1
    st.session_state.sp_filters = filters
    f = filter_rows(frame, filters)
    c = st.columns(3)
    c[0].metric("Calculated occurrences", f"{len(frame):,}")
    c[1].metric("Matching occurrences", f"{len(f):,}")
    c[2].metric("Outstanding reached", f"{frame.maintenance_status.isin(['Due', 'Overdue']).sum():,}")
    feedback = st.checkbox("Show customer response columns", key="sp_show_feedback")
    evidence_columns = st.checkbox("Show usage and schedule columns", key="sp_show_usage")
    st.download_button(
        "Download all filtered results",
        f.to_csv(index=False).encode(),
        file_name="serviceplan-filtered-maintenance.csv",
        mime="text/csv",
    )
    if f.empty:
        st.info(
            "No maintenance matches these filters. Saved history remains available under All or Completed."
        )
        return
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=max(1, math.ceil(len(f) / 25)),
        value=min(st.session_state.get("sp_page", 1), max(1, math.ceil(len(f) / 25))),
        step=1,
        key=f"sp_page_{st.session_state.get('sp_page_epoch', 0)}",
    )
    st.session_state.sp_page = page
    visible, _, pages = page_slice(f, page)
    st.caption(
        f"{len(f):,} matching / {len(frame):,} total · page {page} of {pages}. Select a row to review it."
    )
    cols = [
        "maintenance_id",
        "vehicle_id",
        "customer_name",
        "service_level",
        "target_km",
        "maintenance_status",
        "deadline_date",
        "days_overdue",
        "work_order_status",
    ]
    if evidence_columns:
        cols += [
            "model_id",
            "customer_id",
            "country",
            "city",
            "packages",
            "current_km",
            "remaining_km",
            "km_past_target",
            "first_reached_date",
            "creation_status",
            "data_status",
        ]
    if feedback:
        cols += ["response_decision", "service_date", "finding", "rating", "notes", "rejection_reason"]
    event = st.dataframe(
        display(visible, cols),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"sp_maintenance_{page}_{st.session_state.get('sp_epoch', 0)}",
    )
    if event.selection.rows:
        st.session_state.sp_selected = visible.iloc[event.selection.rows[0]].maintenance_id
        st.rerun()
    with st.expander("Evaluation and audit · administrator"):
        st.write(
            f"Fixed lifetime targets · {manifest['policy']} · source {manifest['source_revision'][:7]} · pre-coverage service history unknown."
        )
        st.dataframe(s.audit(t), hide_index=True)


def summary(item):
    st.subheader(f"{int(item['service_level']):,}-km scheduled maintenance · {item['vehicle_id']}")
    st.write(
        f"**{item['customer_name']}** · {item['customer_id']} · {MODELS[item['model_id']]} · {item['city']}, {item['country']}"
    )
    st.caption(
        f"Target {int(item['target_km']):,} km · {item['maintenance_status']} · usage data: {item['data_status']}"
    )


def actions(snap):
    st.subheader("Recommended actions")
    st.caption(
        "Included packages: " + ", ".join(snap["packages"]) + " · fictional fixed-km policy " + snap["policy"]
    )
    for i, t in enumerate(snap["tasks"], 1):
        st.write(f"{i}. **{t['name']}** — {'Mandatory' if t['mandatory'] else 'Conditional: only if needed'}")


def parts(snap):
    st.subheader("Parts & consumables")
    st.dataframe(
        pd.DataFrame(snap["parts"])[["name", "sku", "quantity", "required_quantity", "unit"]].rename(
            columns={
                "name": "Part",
                "sku": "Compatible ID",
                "quantity": "Proposed quantity",
                "required_quantity": "Mandatory quantity",
                "unit": "Unit",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Model-compatible fictional proposals. Conditional washer fluid is used only when needed. Distinct checklist tasks share cleaning wipes; quantities are summed once per unique task."
    )


def schedule_evidence(s, t, item, oid=None):
    f = s.evidence(t, item["maintenance_id"], oid).sort_values("date")
    plot = f.copy()
    plot["date"] = pd.to_datetime(plot.date)
    gaps = plot.date.diff().dt.days.gt(1)
    extra = pd.DataFrame({"date": plot.date[gaps] - pd.Timedelta(hours=12), "odometer_km": float("nan")})
    plot = pd.concat([plot, extra]).sort_values("date")
    fig = go.Figure(
        go.Scatter(
            x=plot.date,
            y=plot.odometer_km,
            name="Observed end-of-day odometer",
            connectgaps=False,
            line=dict(color="#137e92"),
        )
    )
    fig.add_hline(
        y=item["target_km"],
        line_dash="dash",
        line_color="#c38431",
        annotation_text=f"Fixed target {item['target_km']:,} km",
    )
    if item["first_reached_date"]:
        fig.add_vline(x=pd.Timestamp(item["first_reached_date"]).timestamp() * 1000, line_dash="dot")
    fig.update_layout(
        height=330,
        xaxis_title="Observed date (UTC, day precision)",
        yaxis_title="Lifetime odometer (km)",
        margin=dict(t=25, l=0, r=0, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)
    if item["maintenance_status"] == "Upcoming":
        st.write(
            f"**Upcoming:** {item['remaining_km']:,.3f} km remain to the next fixed target. The threshold has not been observed; there is no start date or completion deadline yet."
        )
    else:
        st.write(
            f"**First observed reaching the target:** {item['first_reached_date']} · **Completion deadline:** {item['deadline_date']}"
        )
        st.write(
            "Completed service is recorded for this target only."
            if item["maintenance_status"] == "Completed"
            else f"This requirement is {item['maintenance_status'].lower()}. The seven-day window runs from crossing, even when the vehicle is not driven. Earlier missed services remain separate."
        )
        if item["completed_at"]:
            st.write(
                f"**Service completed:** {item['completed_at']} · {'Late' if item['late'] else 'Within the seven-day window'} · {item['completion_source']}"
            )
    current = f"{item['current_km']:,.6f} km" if item["current_km"] is not None else "not established"
    st.caption(
        f"Latest trusted odometer: {current} on {item['last_date'] or 'unknown date'}; data status {item['data_status']}; shared demonstration date {s.as_of}. No future usage is estimated."
    )
    if item["data_status"] != "Known":
        st.warning(
            "Usage is stale, unknown or invalid. Review source data before proceeding; new work orders are blocked."
        )
    st.info(
        "Daily readings show the first observed crossing date, not an exact crossing time. Milestones already below the first available reading have unknown earlier history. Generic inspections are not treated as scheduled-service completion."
    )
    if item["crossing_gap_days"] and item["crossing_gap_days"] > 1:
        st.caption(
            f"Crossing is bounded by observations {item['previous_date']}–{item['first_reached_date']}; {item['crossing_gap_days']} days apart."
        )
    history = s.history(t, item["maintenance_id"], oid)
    if not history.empty:
        st.subheader("Service history for this occurrence")
        st.dataframe(history[["service_date", "decision", "source", "reason"]], hide_index=True)


def maintenance_detail(s, t, u):
    item = s.item(t, st.session_state.sp_selected)
    back("sp_selected", "← Back to maintenance")
    summary(item)
    if item["order_id"]:
        st.success(f"Created · {item['order_id']} · {item['work_order_status']}")
        if st.button("Open work order", type="primary"):
            st.session_state.sp_order = item["order_id"]
            st.session_state.sp_workspace_next = "Work order overview"
            st.rerun()
    elif item["maintenance_status"] in ("Due", "Overdue") and item["data_status"] == "Known":
        st.caption("Assigned demo customer: customer" + item["customer_id"][-4:] + "@serviceplan.example")
        if st.button("Create work order", type="primary"):
            result = s.create_order(t, item["maintenance_id"])
            if result["ok"]:
                st.rerun()
            else:
                st.error(result["error"])
    else:
        st.info(
            "This row is for planning or recorded history. Only reached, unfulfilled requirements with known usage can create an order."
        )
    snap = s.order(t, item["order_id"])["snapshot"] if item["order_id"] else s.snapshot(item)
    tabs = st.tabs(["Usage & schedule evidence", "Recommended actions", "Parts & consumables"])
    with tabs[0]:
        schedule_evidence(s, t, item)
    with tabs[1]:
        actions(snap)
    with tabs[2]:
        parts(snap)
    if item["order_id"]:
        r = s.order(t, item["order_id"])["response"]
        if r:
            readback(r)


def orders(s, t):
    st.title("Work order overview")
    st.write("Review saved service recommendations and record the performed service or rejection.")
    f = s.orders(t)
    counts = f.work_order_status.value_counts()
    st.caption(
        f"Saved orders · Open: {counts.get('Open', 0)} · Completed: {counts.get('Completed', 0)} · Rejected: {counts.get('Rejected', 0)}. Sign-out does not delete history."
    )
    if st.session_state.pop("sp_show_history", False):
        st.session_state.sp_order_status = "All"
    if "sp_order_status" not in st.session_state:
        st.session_state.sp_order_status = "Open"
    c = st.columns([1, 2])
    status = c[0].selectbox("Order status", ["Open", "Completed", "Rejected", "All"], key="sp_order_status")
    q = c[1].text_input("Search order or vehicle", key="sp_order_search")
    if status == "Open" and counts.get("Completed", 0) + counts.get("Rejected", 0):
        st.info("Completed and rejected orders remain saved in history.")
        st.button("View all saved orders", on_click=lambda: st.session_state.update(sp_show_history=True))
    filtered = f if status == "All" else f[f.work_order_status == status]
    if q:
        filtered = filtered[
            filtered[["order_id", "vehicle_id"]]
            .fillna("")
            .agg(" ".join, axis=1)
            .str.contains(q, case=False, regex=False)
        ]
    st.caption(f"{len(filtered)} matching / {len(f)} assigned orders.")
    if filtered.empty:
        st.info(
            "No orders match this selection. Use All to see history or Refresh saved changes for newly created orders."
        )
        return
    page = st.number_input(
        "Page",
        min_value=1,
        max_value=max(1, math.ceil(len(filtered) / 25)),
        step=1,
        value=1,
        key="sp_order_page",
    )
    visible, _, _ = page_slice(filtered, page)
    e = st.dataframe(
        display(
            visible, ["order_id", "vehicle_id", "service_level", "target_km", "country", "work_order_status"]
        ),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"sp_order_rows_{page}_{st.session_state.get('sp_epoch', 0)}",
    )
    if e.selection.rows:
        st.session_state.sp_order = visible.iloc[e.selection.rows[0]].order_id
        st.rerun()


def readback(r):
    st.subheader("Customer response")
    st.write(f"**{r['decision']}** · service/response date {r['service_date']} (demonstration clock)")
    if r["decision"] == "Rejected":
        st.write("**Rejection reason:** " + r["rejection_reason"])
    else:
        st.write(f"Finding: {r['finding']} · {r['action']} · reported odometer {r['reported_km']:,.6f} km")
        st.dataframe(
            pd.DataFrame([dict(task=k, **v) for k, v in json.loads(r["task_outcomes"]).items()]),
            hide_index=True,
        )
        st.dataframe(
            pd.DataFrame([dict(part=k, **v) for k, v in json.loads(r["actual_parts"]).items()]),
            hide_index=True,
        )
    st.write("Rating: " + (f"{r['rating']} / 5" if r["rating"] is not None else "Not rated"))
    st.write("Notes: " + (r["notes"] or "—"))
    st.caption(
        "Actual submission recorded at " + r["submitted_at"] + "; completion covers only this fixed target."
    )


def order_detail(s, t, u):
    order = s.order(t, st.session_state.sp_order)
    back("sp_order", "← Back to work orders")
    st.title(order["order_id"])
    summary(order["maintenance"])
    st.write("**" + order["status"] + "** · created " + order["created_at"])
    tabs = st.tabs(["Actions & consumables", "Usage & schedule evidence"])
    with tabs[0]:
        actions(order["snapshot"])
        parts(order["snapshot"])
    with tabs[1]:
        schedule_evidence(s, t, order["maintenance"], order["order_id"])
        st.caption("Saved recommendation evidence date: " + order["snapshot"]["evidence_as_of"])
    if order["response"]:
        readback(order["response"])
    elif u["role"] == "customer":
        response_form(s, t, order)
    else:
        st.info("Awaiting the assigned customer’s response. Administrators cannot submit as customers.")


def response_form(s, t, order):
    st.subheader("Customer service response")
    snap = order["snapshot"]
    decision = st.radio(
        "Decision",
        ["Completed", "Rejected"],
        index=None,
        horizontal=True,
        key="sp_decision_" + order["order_id"],
    )
    day = st.date_input(
        "Service / response date (demonstration UTC)",
        value=date.fromisoformat(s.as_of),
        min_value=date.fromisoformat(snap["first_reached_date"]),
        max_value=date.fromisoformat(s.as_of),
        key="sp_service_date",
    )
    if decision == "Completed":
        try:
            lo, hi = s.service_context(t, order["order_id"], day.isoformat())
            st.caption(
                f"Recorded daily bounds for this date: {lo:,.6f}–{hi:,.6f} km. Report the workshop reading within these observed bounds; daily source precision is shown, not an intraday measurement."
            )
        except ValueError as e:
            st.warning(str(e))
    with st.form("sp_response"):
        outcomes = {}
        actual = {}
        km = None
        finding = None
        action = None
        reason = ""
        if decision == "Completed":
            mandatory = {x["task_id"]: x for x in snap["tasks"] if x["mandatory"]}
            done = st.multiselect(
                "Mandatory tasks completed",
                list(mandatory),
                format_func=lambda x: mandatory[x]["name"],
                default=[],
            )
            for x in snap["tasks"]:
                if x["mandatory"]:
                    outcomes[x["task_id"]] = dict(
                        state="Done" if x["task_id"] in done else "Pending", reason=""
                    )
                else:
                    state = st.selectbox(
                        x["name"],
                        ["Not needed", "Done", "Omitted", "Not applicable"],
                        key="sp_cond_" + x["task_id"],
                    )
                    why = st.text_input("Reason if omitted / not applicable", key="sp_reason_" + x["task_id"])
                    outcomes[x["task_id"]] = dict(state=state, reason=why)
            c = st.columns(3)
            km = c[0].number_input(
                "Reported service odometer (km)", min_value=0.0, value=None, step=0.001, format="%.6f"
            )
            finding = c[1].selectbox(
                "Finding",
                ["Unknown", "Normal wear", "Abnormal wear", "No issue", "Incorrect recommendation"],
                index=None,
            )
            action = c[2].selectbox(
                "Action performed",
                ["Scheduled service performed", "Inspection and service performed"],
                index=None,
            )
            st.markdown("**Actual parts & consumables** · enter quantities used; zero means not used.")
            columns = st.columns(3)
            for i, p in enumerate(snap["parts"]):
                q = columns[i % 3].number_input(
                    f"{p['name']} · {p['unit']} (required {p['required_quantity']})",
                    min_value=0.0,
                    max_value=float(p["quantity"]),
                    value=0.0,
                    step=0.1 if p["unit"] == "L" else 1.0,
                    key="sp_qty_" + p["sku"],
                )
                if q > 0:
                    actual[p["sku"]] = dict(quantity=str(q), unit=p["unit"])
        elif decision == "Rejected":
            reason = st.text_area("Rejection reason (required)")
        rating = st.selectbox("Rating (optional)", ["Not rated", 1, 2, 3, 4, 5])
        notes = st.text_area("Notes (optional)", max_chars=4000)
        submit = st.form_submit_button("Submit response", type="primary", disabled=decision is None)
    if submit:
        try:
            s.respond(
                t,
                order["order_id"],
                dict(
                    decision=decision,
                    service_date=day.isoformat(),
                    reported_km=km,
                    finding=finding,
                    action=action,
                    task_outcomes=outcomes,
                    actual_parts=actual,
                    rejection_reason=reason,
                    rating=None if rating == "Not rated" else rating,
                    notes=notes,
                ),
            )
            st.rerun()
        except (ValueError, PermissionError) as e:
            st.error(str(e))
