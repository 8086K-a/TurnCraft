from ..models import ActionResult


def action_response(args: dict, slots: dict, context: dict, **kwargs) -> ActionResult:
    text = args.get("text", "")
    return ActionResult(messages=[{"role": "assistant", "content": text}])


def action_listen(args: dict, slots: dict, context: dict, **kwargs) -> ActionResult:
    return ActionResult(need_listen=True)
