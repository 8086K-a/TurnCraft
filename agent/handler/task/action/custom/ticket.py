from ..models import ActionResult
from ._order_items import first_order_item, order_item_id

_TYPE_MAP = {
    "售后": "after_sales",
    "投诉": "complaint",
    "退款": "refund",
    "after_sales": "after_sales",
    "complaint": "complaint",
    "refund": "refund",
}


async def action_submit_ticket(
    args: dict, slots: dict, context: dict, **kwargs
) -> ActionResult:
    api = kwargs.get("api")
    if not api:
        return ActionResult(messages=[{"role": "assistant", "content": "API 不可用。"}], end_flow=True)

    user_id = context.get("user_id") or args.get("user_id") or slots.get("user_id")
    if not user_id:
        return ActionResult(messages=[{"role": "assistant", "content": "无法获取用户身份信息。"}], end_flow=True)

    ticket_type_raw = slots.get("ticket_type", "")
    ticket_type = _TYPE_MAP.get(ticket_type_raw, ticket_type_raw)
    order_no = slots.get("order_number", "")
    description = slots.get("ticket_description", "")

    if not ticket_type_raw or not order_no or not description:
        return ActionResult(messages=[{"role": "assistant", "content": "工单信息不完整。"}], end_flow=True)

    try:
        profile = await api.get_my_student_profile(user_id)
        student_id = profile.get("studentId", 0)

        order = await api.find_order_by_no(user_id, order_no)
        if not order:
            return ActionResult(messages=[{"role": "assistant", "content": f"未找到订单 {order_no}。"}], end_flow=True)
        item_id = order_item_id(first_order_item(order))

        result = await api.create_service_ticket(
            user_id=user_id,
            ticket_type=ticket_type,
            title=f"{ticket_type_raw}工单",
            content=description,
            student_id=student_id,
            order_item_id=item_id,
        )

        ticket_no = result.get("ticketNo") or result.get("serviceTicketNo", "")
        number_text = f"工单编号：{ticket_no}。" if ticket_no else ""

        return ActionResult(
            slots={
                "ticket_result": (
                    f"你的{ticket_type_raw}工单已提交。"
                    f"{number_text}问题描述：{description}。我们会尽快处理。"
                )
            }
        )
    except Exception:
        return ActionResult(messages=[{"role": "assistant", "content": "工单提交失败，请稍后重试。"}], end_flow=True)
