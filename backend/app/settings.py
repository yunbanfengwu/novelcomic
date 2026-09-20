"""pydantic-settings 配置，读 backend/.env。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    DATABASE_URL: str = "postgresql://postgres:123456@localhost:5432/novelcomic"

    LLM_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen2.5-72B-Instruct"

    GRSAI_BASE_URL: str = "https://grsai.dakka.com.cn/v1"
    GRSAI_API_KEY: str = ""
    GRSAI_IMAGE_MODEL: str = "nano-banana-fast"
    GRSAI_VIDEO_MODEL: str = "veo3.1-fast"

    # 阿里云百炼（DashScope）：全线走 OpenAI 兼容模式，与火山方舟并列的第二家厂商
    # （免费额度 / Token Plan 资源包）。工作空间专属 Key 有自己的 maas 域名，写在 .env 里覆盖。
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_TEXT_MODEL: str = "qwen-plus"

    MINIMAX_BASE_URL: str = "https://api.minimaxi.com/v1"
    MINIMAX_API_KEY: str = ""

    ARK_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    ARK_API_KEY: str = ""
    ARK_VIDEO_MODEL: str = "doubao-seedance-1-5-pro"

    # 火山方舟私域素材库（Assets API，AK/SK V4 签名，与 ARK_API_KEY 不同凭证）
    VOLC_AK: str = ""
    VOLC_SK: str = ""
    VOLC_ASSET_HOST: str = "open.volcengineapi.com"   # OpenAPI 网关
    VOLC_ASSET_REGION: str = "cn-beijing"
    VOLC_ASSET_SERVICE: str = "ark"
    VOLC_ASSET_VERSION: str = "2024-01-01"
    # 素材所属项目，须与生视频 API Key 所属项目一致（默认 default）
    ARK_PROJECT_NAME: str = "default"

    # 阿里云 OSS 转存（配置来源 cocc-work）
    OSS_ACCESS_KEY: str = ""
    OSS_SECRET_KEY: str = ""
    OSS_ENDPOINT: str = "oss-cn-beijing.aliyuncs.com"
    OSS_BUCKET: str = ""
    OSS_BASE_URL: str = ""


settings = Settings()
