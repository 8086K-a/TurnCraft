from typing import Any


def first_order_item(order: dict[str, Any]) -> dict[str, Any] | None:
    items = (
        order.get("orderItems")
        or order.get("items")
        or order.get("itemList")
        or []
    )
    return items[0] if items else None


def order_item_id(item: dict[str, Any] | None) -> int | None:
    if not item:
        return None
    value = item.get("orderItemId") or item.get("id")
    return int(value) if value is not None else None
