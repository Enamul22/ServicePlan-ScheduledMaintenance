from streamlit.testing.v1 import AppTest
from serviceplan.service import Service
from serviceplan.config import ROOT
from conftest import create


def button(app, label):
    return next(b for b in app.button if b.label == label)


def sign_in(app, email, password):
    app.text_input(key="sp_email").set_value(email)
    app.text_input(key="sp_password").set_value(password)
    button(app, "Sign in").click().run()
    assert not app.exception


def test_hosted_missing_configuration_fails_safely(monkeypatch):
    monkeypatch.setenv("SERVICEPLAN_MODE", "hosted")
    monkeypatch.delenv("SERVICEPLAN_DATABASE_URL", raising=False)
    at = AppTest.from_file(ROOT / "app.py").run()
    assert not at.exception
    assert "requires its own Neon" in at.error[0].value
    assert not at.text_input


def test_customer_ui_completion_relogin_admin_readback(tmp_path, tiny, monkeypatch):
    monkeypatch.setenv("SERVICEPLAN_MODE", "local")
    monkeypatch.setenv("SERVICEPLAN_DB", str(tmp_path / "ui.sqlite"))
    s = Service(mode="local", path=tmp_path / "ui.sqlite", data=tiny)
    a = s.login("admin@serviceplan.example", "serviceplan-admin-demo")
    r, oid = create(s, a)
    at = AppTest.from_file(ROOT / "app.py", default_timeout=30)
    at.session_state["sp_service"] = s
    at.run()
    sign_in(at, "customer0000@serviceplan.example", "serviceplan-customer-demo")
    assert at.title[0].value == "Work order overview"
    assert len(at.dataframe[0].value) == 1
    at.session_state["sp_order"] = oid
    at.run()
    assert not at.exception
    at.radio(key="sp_decision_" + oid).set_value("Completed").run()
    mandatory = next(m for m in at.multiselect if m.label == "Mandatory tasks completed")
    mandatory.set_value([t["task_id"] for t in s.order(a, oid)["snapshot"]["tasks"] if t["mandatory"]])
    for n in at.number_input:
        if n.label == "Reported service odometer (km)":
            n.set_value(9700.0)
        elif "(required " in n.label:
            required = n.label.split("(required ")[1].rstrip(")")
            n.set_value(float(required))
    next(x for x in at.selectbox if x.label == "Finding").select("No issue")
    next(x for x in at.selectbox if x.label == "Action performed").select("Scheduled service performed")
    next(x for x in at.selectbox if x.label == "Rating (optional)").select(5)
    button(at, "Submit response").click().run()
    assert not at.exception and not at.error
    assert s.order(a, oid)["status"] == "Completed"
    button(at, "Sign out").click().run()
    # Main creates a fresh service after sign-out against the same local persistent file.
    sign_in(at, "customer0000@serviceplan.example", "serviceplan-customer-demo")
    assert any("Completed: 1" in x.value for x in at.caption)
    button(at, "View all saved orders").click().run()
    assert at.selectbox(key="sp_order_status").value == "All"
    assert at.dataframe[0].value["Order status"].tolist() == ["Completed"]
    button(at, "Sign out").click().run()
    sign_in(at, "admin@serviceplan.example", "serviceplan-admin-demo")
    assert at.title[0].value == "Maintenance overview"
    at.session_state["sp_selected"] = r["maintenance_id"]
    at.run()
    assert not at.exception
    assert any("5 / 5" in x.value for x in at.markdown)
    assert not any(b.label == "Submit response" for b in at.button)
