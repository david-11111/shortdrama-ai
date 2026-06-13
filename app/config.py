from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/saas_db"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    jwt_secret: str = "change-me-in-production"
    jwt_expire_minutes: int = 30
    jwt_refresh_expire_days: int = 7
    ark_api_keys: str = ""
    seedance_api_keys: str = ""
    seedream_api_keys: str = ""
    doubao_api_keys: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_video_model: str = "seedance-1-0"
    ark_image_model: str = "seedream-3-0"
    ark_text_model: str = "doubao-1-5-pro-32k"
    llm_planner_provider: str = "auto"
    llm_coordination_enabled: bool = False
    llm_error_reflection_enabled: bool = False
    requirement_llm_timeout_seconds: float = 8.0
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    kling_api_keys: str = ""
    kling_base_url: str = "https://api.klingai.com/v1"
    kling_access_key: str = ""
    kling_secret_key: str = ""
    ark_tts_model: str = "volcano-tts-mega"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # 对象存储 (TOS / S3 兼容)
    oss_endpoint: str = "https://tos-cn-beijing.volces.com"
    oss_access_key: str = ""
    oss_secret_key: str = ""
    oss_bucket: str = "shortdrama-ai"
    oss_region: str = "cn-beijing"
    oss_cdn_domain: str = ""  # 如 "https://cdn.example.com"，为空则用 bucket 直链

    # 微信支付
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_key: str = ""
    wechat_cert_serial: str = ""
    wechat_private_key_path: str = ""
    wechat_notify_url: str = ""

    # 支付宝
    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_public_key: str = ""
    alipay_notify_url: str = ""
    alipay_return_url: str = ""

    # 邮件通知
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "ShortDrama AI"
    smtp_use_ssl: bool = True
    vision_review_provider: str = ""
    platform_daily_cost_limit_yuan: float = 300.0
    platform_daily_cost_warn_ratio: float = 0.8
    user_daily_credit_limit: int = 1000
    batch_max_items: int = 100

    # ComfyUI (本地/自建 GPU 视频生成)
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_api_key: str = ""
    ltx_api_base_url: str = ""
    ltx_api_key: str = ""
    inference_api_base_url: str = "http://127.0.0.1:8100"
    inference_api_key: str = "sk-default-dev-key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def ark_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.ark_api_keys.split(",") if key.strip()]

    @property
    def ark_api_key(self) -> str:
        return self.ark_api_key_list[0] if self.ark_api_key_list else ""

    @property
    def kling_api_key_list(self) -> list[str]:
        return [key.strip() for key in self.kling_api_keys.split(",") if key.strip()]

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        env = (self.app_env or "").strip().lower()
        if env in {"prod", "production"}:
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false in production.")
            if not self.jwt_secret or self.jwt_secret == "change-me-in-production":
                raise ValueError("JWT_SECRET must be set to a non-default value in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ffmpeg/ffprobe 路径（供 cover/probe/scene_detect/video_edit 服务使用）
import shutil as _shutil
import os as _os

def _resolve_binary(name: str) -> str:
    env_val = _os.environ.get(name.upper(), "")
    if env_val and _os.path.exists(env_val):
        return env_val
    found = _shutil.which(name)
    return found or name

FFMPEG = _resolve_binary("ffmpeg")
FFPROBE = _resolve_binary("ffprobe")
