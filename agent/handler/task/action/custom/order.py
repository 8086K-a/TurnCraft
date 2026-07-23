import traceback

from loguru import logger
from ..models import ActionResult
from ._order_items import first_order_item

_STATUS_MAP = {
    "pending": "待支付",
    "paid": "已支付",
    "completed": "已完成",
    "cancelled": "已取消",
    "partial_refunded": "部分退款",
    "refunded": "已退款",
}


async def action_lookup_order_status(
    args: dict, slots: dict, context: dict, **kwargs
) -> ActionResult:
    api = kwargs.get("api")
    if not api:
        return ActionResult(messages=[{"role": "assistant", "content": "API 不可用。"}], end_flow=True)

    user_id = context.get("user_id") or args.get("user_id") or slots.get("user_id")
    if not user_id:
        return ActionResult(messages=[{"role": "assistant", "content": "无法获取用户身份信息。"}], end_flow=True)

    order_no = slots.get("order_number") or args.get("order_number")
    if not order_no:
        return ActionResult(messages=[{"role": "assistant", "content": "没有提供订单号。"}], end_flow=True)

    try:
        order = await api.find_order_by_no(user_id, order_no)
        if not order:
            return ActionResult(messages=[{"role": "assistant", "content": f"未找到订单 {order_no}。"}], end_flow=True)

        status = _STATUS_MAP.get(order.get("orderStatusCode", ""), order.get("orderStatusCode", ""))
        summary = f"金额：{float(order.get('payableAmount', 0)):.2f}元"

        pmt = order.get("paymentSummary") or {}
        if pmt.get("paidAt"):
            summary += f"，支付时间：{pmt['paidAt']}"

        item = first_order_item(order)
        course_name = (item or {}).get("courseName") or (item or {}).get("seriesName")
        if course_name:
            summary = f"报名课程：{course_name}，{summary}"

        return ActionResult(slots={"order_status": status, "order_summary": summary})
    except Exception:
        logger.error("订单查询异常 user_id={} order_no={}\n{}", user_id, order_no, traceback.format_exc())
        return ActionResult(messages=[{"role": "assistant", "content": "订单查询暂时失败，请稍后重试。"}], end_flow=True)
