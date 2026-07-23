class ClarifyResponder:
    def respond(self, reason: str, focused_object=None) -> str:
        if reason == "object_intent":
            if focused_object and focused_object.type == "product":
                return "你想了解这个商品的课程信息、价格，还是其他内容？"
            if focused_object and focused_object.type == "order":
                return "你想查询这个订单的状态、物流，还是申请售后？"
        if reason == "multiple_intents":
            return "我同时听到了几个需求，你想先处理哪一个？"
        return "我还不确定你的需求，请具体说明想办理什么或查询什么。"
