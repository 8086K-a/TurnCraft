import logging

from jinja2 import Template

from agent.prompts.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

CLARIFY_MESSAGES = {
    "object_intent": {
        "product": "你想了解这个商品的课程信息、价格，还是其他内容？",
        "order": "你想查询这个订单的状态，还是申请售后？",
    },
    "multiple_intents": "我同时听到了几个需求，你想先处理哪一个？",
    "invalid_plan": "我还不确定你的需求，请具体说明想办理什么或查询什么。",
    "unknown": "我还不确定你的需求，请具体说明想办理什么或查询什么。",
}


class ClarifyResponder:
    def __init__(self, llm=None):
        self._llm = llm
        self._template = Template(load_prompt("clarify_respond")) if llm else None

    def _get_raw_message(self, reason: str, focused_object=None) -> str:
        if reason == "object_intent" and focused_object:
            return CLARIFY_MESSAGES["object_intent"].get(focused_object.type, "你想了解这个商品或订单的什么信息？")
        return CLARIFY_MESSAGES.get(reason, "我还不确定你的需求，请具体说明想办理什么或查询什么。")

    async def respond(self, reason: str, focused_object=None, user_message=None, history="") -> str:
        raw = self._get_raw_message(reason, focused_object)
        if not self._llm or not self._template:
            return raw
        focused_str = None
        if focused_object:
            focused_str = str(focused_object.model_dump(mode="json") if hasattr(focused_object, "model_dump") else focused_object)
        user_text = ""
        if user_message:
            user_text = user_message.text or str(user_message.object.model_dump() if user_message.object else "")
        try:
            prompt = self._template.render(
                reason=reason,
                clarify_message=raw,
                focused_object=focused_str,
                history=history,
                user_message=user_text,
            )
            response = await self._llm.ainvoke(prompt)
            text = response.content.strip() if hasattr(response, "content") else str(response).strip()
            if text:
                return text
        except Exception:
            logger.exception("Failed to generate clarify response")
        return raw
