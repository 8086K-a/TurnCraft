from ..models import ActionResult
from ._order_items import first_order_item, order_item_id


async def action_submit_refund(
    args: dict, slots: dict, context: dict, **kwargs
) -> ActionResult:
    api = kwargs.get("api")
    if not api:
        return ActionResult(messages=[{"role": "assistant", "content": "API 不可用。"}], end_flow=True)

    user_id = context.get("user_id") or args.get("user_id") or slots.get("user_id")
    if not user_id:
        return ActionResult(messages=[{"role": "assistant", "content": "无法获取用户身份信息。"}], end_flow=True)

    order_no = slots.get("order_number")
    reason = slots.get("refund_reason", "")
    refund_type = slots.get("refund_type", "personal_reason")

    if not order_no:
        return ActionResult(messages=[{"role": "assistant", "content": "没有提供订单号。"}], end_flow=True)

    try:
        order = await api.find_order_by_no(user_id, order_no)
        if not order:
            return ActionResult(messages=[{"role": "assistant", "content": f"未找到订单 {order_no}。"}], end_flow=True)

        item = first_order_item(order)
        item_id = order_item_id(item)
        if item_id is None:
            return ActionResult(messages=[{"role": "assistant", "content": "该订单没有可申请退款的订单项。"}], end_flow=True)
        amount = float((item or {}).get("payableAmount") or order.get("payableAmount", 0))

        result = await api.create_refund_request(
            user_id=user_id,
            order_item_id=item_id,
            refund_type=refund_type,
            reason=reason,
            amount=amount,
        )
        refund_no = result.get("refundRequestNo") or result.get("refundNo", "")
        number_text = f"退款申请编号：{refund_no}。" if refund_no else ""

        return ActionResult(
            slots={
                "refund_result": (
                    f"订单{order_no}的退款申请已提交。"
                    f"{number_text}退款类型：{refund_type}，原因：{reason}。后续会尽快处理。"
                )
            }
        )
    except Exception:
        return ActionResult(messages=[{"role": "assistant", "content": "退款申请提交失败，请稍后重试。"}], end_flow=True)
