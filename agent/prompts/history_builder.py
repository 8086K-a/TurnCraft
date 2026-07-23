from agent.domain.message import UserMessage, BotMessage, MessageObject, MessageType


class HistoryBuilder:

    @staticmethod
    def build(turns: list) -> str:
        """
        构建对话历史
        :return:
        USER: <user_message>
        BOT: <bot_message>
        BOT: <bot_message>
        USER: <user_message>
        BOT: <bot_message>
        """
        messages: list[str] = []
        for turn in turns:
            user_message = getattr(turn, "input_message", getattr(turn, "user_message", None))
            if user_message is None:
                continue
            rendered_user_message = HistoryBuilder._render_user_message(user_message)
            messages.append(f"USER: {rendered_user_message}")
            bot_msgs = getattr(turn, "assistant_messages", getattr(turn, "bot_messages", []))
            for bot_message in bot_msgs:
                rendered_bot_message = HistoryBuilder._render_bot_message(bot_message)
                messages.append(f"BOT: {rendered_bot_message}")

        return "\n".join(messages)

    @staticmethod
    def _render_text(text: str) -> str:
        return text.strip()

    @staticmethod
    def _render_object(object: MessageObject) -> str:
        # [订单对象 id=A1001,title='小米手机', attr1=value1, attr2=value2, attr3=value3 ]
        labels = {
            "order": "订单对象",
            "course": "课程对象",
            "cohort": "班次对象",
        }
        label = labels.get(object.type, "业务对象")
        id = object.id
        title = object.title
        attributes = object.attributes
        attributes_str = ", ".join([f"{key}={value}" for key, value in attributes.items()])
        return f"[{label} id={id}, title={title}, {attributes_str}]"

    @staticmethod
    def _render_user_message(user_message: UserMessage) -> str:
        if user_message.type == MessageType.TEXT:
            return HistoryBuilder._render_text(user_message.text)
        else:
            return HistoryBuilder._render_object(user_message.object)

    @staticmethod
    def _render_bot_message(bot_message: BotMessage):
        if bot_message.text:
            return HistoryBuilder._render_text(bot_message.text)
        else:
            return HistoryBuilder._render_object(bot_message.object)
