"""Shared order loading and US measurement conversion."""

import json
import math

from fastapi import HTTPException
from sqlalchemy import text


def load_order(db, order_id):
    row = db.execute(text("SELECT * FROM orders WHERE id=:id"), {"id": order_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Order not found.")
    result = dict(row)
    for field in ("recipient", "origin", "shipping", "customs"):
        result[field] = json.loads(result.pop(f"{field}_json") or "null")
    result["packages"] = [
        dict(p)
        for p in db.execute(
            text("SELECT * FROM packages WHERE order_id=:id"), {"id": order_id}
        ).mappings()
    ]
    for package in result["packages"]:
        for metric, us, factor in (
            ("weight_g", "weight_oz", 28.349523125),
            ("length_mm", "length_in", 25.4),
            ("width_mm", "width_in", 25.4),
            ("height_mm", "height_in", 25.4),
        ):
            if package.get(us) is None and package.get(metric) is not None:
                package[us] = package[metric] / factor
            if package.get(us) is not None:
                package[us] = math.ceil(package[us])
    result["items"] = [
        dict(p)
        for p in db.execute(
            text("SELECT * FROM order_items WHERE order_id=:id"), {"id": order_id}
        ).mappings()
    ]
    return result
