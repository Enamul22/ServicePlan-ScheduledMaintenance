"""Pure complete-result filters and pagination; downloads use the same filtered rows."""


def filter_rows(frame, filters):
    f = frame.copy()
    status = filters.get("maintenance_status", "Needs attention & planning")
    if status == "Needs attention & planning":
        f = f[f.maintenance_status != "Completed"]
    elif status != "All":
        f = f[f.maintenance_status == status]
    for c in (
        "vehicle_id",
        "customer_id",
        "country",
        "model_id",
        "service_level",
        "creation_status",
        "work_order_status",
    ):
        v = filters.get(c, "All")
        if v != "All":
            f = f[f[c].astype(str) == str(v)]
    q = filters.get("search", "").strip()
    if q:
        text = (
            f[["maintenance_id", "vehicle_id", "customer_id", "customer_name", "country", "city", "order_id"]]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
        )
        f = f[text.str.contains(q, case=False, regex=False)]
    if filters.get("date_from"):
        f = f[f.first_reached_date.fillna("0000").ge(filters["date_from"])]
    if filters.get("date_to"):
        f = f[f.first_reached_date.fillna("9999").le(filters["date_to"])]
    sort = filters.get("sort", "Oldest outstanding first")
    if sort == "Target km":
        return f.sort_values(["target_km", "vehicle_id"])
    if sort == "Vehicle":
        return f.sort_values(["vehicle_id", "target_km"])
    f["_order"] = f.maintenance_status.map({"Overdue": 0, "Due": 1, "Upcoming": 2, "Completed": 3})
    return f.sort_values(
        ["_order", "first_reached_date", "vehicle_id", "target_km"], na_position="last"
    ).drop(columns="_order")


def page_slice(frame, page, size=25):
    pages = max(1, (len(frame) + size - 1) // size)
    page = min(max(1, int(page)), pages)
    return frame.iloc[(page - 1) * size : page * size], page, pages
