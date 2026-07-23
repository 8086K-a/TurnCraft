from ..models import ActionResult


async def action_lookup_learning_progress(
    args: dict, slots: dict, context: dict, **kwargs
) -> ActionResult:
    api = kwargs.get("api")
    if not api:
        return ActionResult(messages=[{"role": "assistant", "content": "API 不可用。"}], end_flow=True)

    user_id = context.get("user_id") or args.get("user_id") or slots.get("user_id")
    if not user_id:
        return ActionResult(messages=[{"role": "assistant", "content": "无法获取用户身份信息。"}], end_flow=True)

    cohort_name = slots.get("cohort_name") or args.get("cohort_name", "")
    if not cohort_name:
        return ActionResult(messages=[{"role": "assistant", "content": "没有提供班次名称。"}], end_flow=True)

    try:
        data = await api.list_my_cohorts(user_id, page=1, size=100)
        cohorts = data.get("list", [])
        target = None
        for c in cohorts:
            if cohort_name in c.get("cohortName", ""):
                target = c
                break
        if not target:
            return ActionResult(messages=[{"role": "assistant", "content": f"未找到班次「{cohort_name}」。"}], end_flow=True)

        progress = await api.get_my_cohort_progress(user_id, target["cohortId"])
        parts = []
        if progress.get("attendanceSummary"):
            a = progress["attendanceSummary"]
            parts.append(f"出勤：{a.get('presentCount', 0)}次出勤 / {a.get('absentCount', 0)}次缺勤")
        if progress.get("videoSummary"):
            v = progress["videoSummary"]
            parts.append(f"视频：{v.get('completedCount', 0)}/{v.get('totalCount', 0)}个已完成")
        if progress.get("homeworkSummary"):
            h = progress["homeworkSummary"]
            parts.append(f"作业：{h.get('submittedCount', 0)}/{h.get('totalCount', 0)}次已提交")
        if progress.get("examSummary"):
            e = progress["examSummary"]
            parts.append(f"考试：{e.get('submittedCount', 0)}/{e.get('totalCount', 0)}次已参加")

        summary = "；".join(parts) if parts else "暂无学习数据。"
        return ActionResult(slots={"learning_progress_summary": summary})
    except Exception:
        return ActionResult(messages=[{"role": "assistant", "content": "学习进度查询暂时失败，请稍后重试。"}], end_flow=True)
