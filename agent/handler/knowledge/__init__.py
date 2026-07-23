MOCK_KNOWLEDGE = {
    "课程咨询": "我们的课程涵盖编程、数据分析、人工智能等多个方向。编程课程分为入门班、项目班和就业强化班三种层次，采用直播或录播形式授课，学费从2499元到6999元不等。",
    "报名流程": "报名流程：选择课程→联系客服确认班次→支付学费→开通学习账号→等待开课。支持支付宝、微信、银行转账支付。",
    "退款政策": "开课7天内无理由全额退款；开课30天内按已上课时比例退款；开课超过30天不予退款。退款周期为3-5个工作日。",
    "学习方式": "支持直播互动、录播回放、在线作业、模拟考试等多种学习方式。直播课有回放，录播课可反复观看。",
}

KNOWLEDGE_INTENTS = tuple(MOCK_KNOWLEDGE)


async def handle_knowledge(intents: list[str], user_message: str) -> str:
    for intent in intents:
        if intent in MOCK_KNOWLEDGE:
            return MOCK_KNOWLEDGE[intent]
    return "目前知识库中暂无相关信息，请咨询客服获取更多详情。"
