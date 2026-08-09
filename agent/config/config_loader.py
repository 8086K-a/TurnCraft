from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# 定位到项目根目录的 .env 文件
env_path = Path(__file__).resolve().parents[2] / '.env'


class Settings(BaseSettings):
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    db_url: str = Field(default="", validation_alias="DATABASE_URL")
    commerce_api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="COMMERCE_API_BASE_URL",
    )
    # ---- 工具路由 / embedding 相关配置 ----
    embedding_model: str = "text-embedding-v4"
    embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    )
    embedding_enabled: bool = True
    embedding_timeout: float = 10.0
    router_top_k: int = 8
    router_cache_size: int = 512
    router_low_threshold: float = 0.40
    router_ambiguity_delta: float = 0.20
    model_config = {
        "env_file": str(env_path),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
if __name__ == '__main__':
    print(settings.llm_base_url)
