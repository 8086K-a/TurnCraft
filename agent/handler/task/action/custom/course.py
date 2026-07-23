from ..models import ActionResult


async def action_lookup_course_info(
    args: dict, slots: dict, context: dict, **kwargs
) -> ActionResult:
    api = kwargs.get("api")
    if not api:
        return ActionResult(messages=[{"role": "assistant", "content": "API 不可用。"}], end_flow=True)

    focused_object = context.get("focused_object") or {}
    course_name = (
        args.get("course_name")
        or slots.get("course_name", "")
        or (
            focused_object.get("title", "")
            if focused_object.get("type") in {"product", "course"}
            else ""
        )
    )
    if not course_name:
        return ActionResult(messages=[{"role": "assistant", "content": "请告诉我你想了解的课程名称。"}], end_flow=True)

    try:
        data = await api.list_series(keyword=course_name, page=1, size=20)
        series_list = data.get("list", [])
        if not series_list:
            return ActionResult(messages=[{"role": "assistant", "content": f"未找到与「{course_name}」相关的课程。"}], end_flow=True)

        series = series_list[0]
        cohorts = await api.list_series_cohorts(series["seriesId"])
        cohorts_lines = []
        for c in cohorts:
            name = c.get("cohortName", "")
            price = float(c.get("salePrice", 0))
            start = c.get("startDate", "")
            cohorts_lines.append(f"  - {name}：{price:.0f}元，{start}开课")
        cohorts_str = "\n".join(cohorts_lines) if cohorts_lines else "暂无在售班次"

        info = (
            f"课程：{series.get('seriesName', '')}\n"
            f"在售班次：\n{cohorts_str}"
        )
        return ActionResult(slots={"course_info": info})
    except Exception:
        return ActionResult(messages=[{"role": "assistant", "content": "课程查询暂时失败，请稍后重试。"}], end_flow=True)
