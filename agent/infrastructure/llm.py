from functools import lru_cache
from langchain.chat_models import init_chat_model
from agent.config.config_loader import settings


@lru_cache(maxsize=1)
def get_llm():
    return init_chat_model(
        model_provider="openai",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
    )

if __name__ == '__main__':
    print(get_llm().invoke("你是谁").content)