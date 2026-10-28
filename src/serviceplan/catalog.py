"""Incremental fictional packages. A task appears once even through repeated inheritance."""

from decimal import Decimal
from .config import MODELS, POLICY

TASKS = {
    "P1000": [
        (
            "BASIC",
            "Complete the basic inspection checklist",
            True,
            [
                ("BASIC-KIT", "Basic service consumables kit", "1", "unit"),
                ("WIPE", "Cleaning wipe", "2", "unit"),
            ],
        ),
        ("FLUID-CHECK", "Inspect fluid levels and record findings", True, []),
        ("CONNECTION", "Check connections and visible condition", True, []),
        ("WASHER", "Top up washer fluid if needed", False, [("WASHER", "Washer fluid", "1", "L")]),
    ],
    "P5000": [
        ("OIL", "Replace engine oil", True, [("OIL", "Engine oil", "capacity", "L")]),
        (
            "FILTER",
            "Replace oil filter and sealing washer",
            True,
            [("FILTER", "Oil filter", "1", "unit"), ("SEAL", "Sealing washer", "1", "unit")],
        ),
        ("FINDINGS", "Record lubrication inspection findings", True, []),
    ],
    "P10000": [
        ("AIR", "Replace engine air filter", True, [("AIR", "Engine air filter", "1", "unit")]),
        ("PLUG", "Replace spark-plug set", True, [("PLUG", "Spark-plug set", "1", "set")]),
        (
            "EXTENDED",
            "Complete extended inspection checklist",
            True,
            [("WIPE", "Cleaning wipe", "3", "unit")],
        ),
    ],
}
CAPACITY = {"ALD": "3.5", "BIR": "4.2", "CED": "5.6", "ELM": "6.3"}


def level(target):
    if target <= 0 or target % 1000:
        raise ValueError("Target must be a positive 1,000-km milestone")
    return 10000 if target % 10000 == 0 else 5000 if target % 5000 == 0 else 1000


def packages(target):
    return (
        ["P10000", "P5000", "P1000"]
        if level(target) == 10000
        else ["P5000", "P1000"]
        if level(target) == 5000
        else ["P1000"]
    )


def recommendation(model, target):
    if model not in MODELS:
        raise ValueError("Unknown vehicle model")
    tasks, parts = {}, {}
    for package in packages(target):
        for tid, name, mandatory, items in TASKS[package]:
            if tid in tasks:
                continue
            requirements = []
            for family, label, quantity, unit in items:
                quantity = Decimal(CAPACITY[model] if quantity == "capacity" else quantity)
                sku = f"SP-{model}-{family}"
                requirements.append(dict(sku=sku, quantity=str(quantity), unit=unit))
                if sku not in parts:
                    parts[sku] = dict(
                        sku=sku, name=label, quantity="0", required_quantity="0", unit=unit, model_id=model
                    )
                parts[sku]["quantity"] = str(Decimal(parts[sku]["quantity"]) + quantity)
                if mandatory:
                    parts[sku]["required_quantity"] = str(Decimal(parts[sku]["required_quantity"]) + quantity)
            tasks[tid] = dict(
                task_id=tid, package_id=package, name=name, mandatory=mandatory, parts=requirements
            )
    return dict(
        policy=POLICY,
        service_level=level(target),
        target_km=target,
        packages=packages(target),
        tasks=list(tasks.values()),
        parts=list(parts.values()),
    )
